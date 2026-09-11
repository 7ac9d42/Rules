#!/usr/bin/env python3
"""真实规则下验证 Tunnel 的 TCP/UDP 出站、端口边界、手选隔离与重启保留。

所有节点、DIRECT、UDP 中继都替换为回环标签；不下载订阅，不接管 DNS/TUN。
地址预期独立取自官方全球端点清单，IPv6 的 ::10 是十六进制，不包含 ::a。
https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
不证明真实 cloudflared、QUIC、运营商链路或代理节点可用性。
"""

import argparse
from contextlib import ExitStack
import http.client
import ipaddress
import json
import os
from pathlib import Path
import runpy
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse


ROOT = Path(__file__).resolve().parent.parent
RR = runpy.run_path(str(Path(__file__).with_name('test-real-rule-routing.py')))
UDP = runpy.run_path(str(Path(__file__).with_name('test-rematch-udp.py')))
TUNNEL = 'Cloudflare Tunnel'
GENERAL = '通用代理'
MANUAL = '机场名称1-fixture'
OTHER_MANUAL = '机场名称3-fixture'
TCP_ONLY = '机场名称4-仅TCP-fixture'
HOME = '自建/家宽节点'
HOME_NODE = 'home-node-fixture'
HOME_TCP = 'home-tcp-fixture'
DOMAINS = ['region1.v2.argotunnel.com', 'region2.v2.argotunnel.com',
           'cftunnel.com', 'h2.cftunnel.com', 'quic.cftunnel.com']
IPS = [f'198.41.192.{n}' for n in (167, 67, 57, 107, 27, 7, 227, 47, 37, 77)]
IPS += [f'198.41.200.{n}' for n in (13, 193, 33, 233, 53, 63, 113, 73, 43, 23)]
IPS += [f'2606:4700:{region}::{n}' for region in ('a0', 'a8')
        for n in ('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')]
# 第三列是入口；预期不从待测规则生成。
CASES = [(host, 7844, TUNNEL) for host in DOMAINS + IPS]
CASES += [(host, 443, GENERAL) for host in IPS]
CASES += [(host, 443, 'DIRECT') for host in DOMAINS]
CASES += [('9.9.9.9', 7844, GENERAL), ('198.41.192.1', 7844, GENERAL),
          ('2606:4700:a0::a', 7844, GENERAL),
          ('demo.trycloudflare.com', 7844, 'DIRECT'),
          ('demo.trycloudflare.com', 443, 'DIRECT'),
          ('update.argotunnel.com', 443, 'DIRECT'),
          ('unknown.argotunnel.com', 7844, 'DIRECT'),
          ('unknown.cftunnel.com', 7844, 'DIRECT')]
WITNESSES = [CASES[0], CASES[5], CASES[25],
             ('198.41.192.167', 443, GENERAL), ('9.9.9.9', 7844, GENERAL),
             ('demo.trycloudflare.com', 443, 'DIRECT')]


def udp_request(mixed, host, port, sockets):
    # 保留源端口，防止新用例复用 Mihomo 的旧 UDP NAT 出口。
    sock = sockets.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    sock.bind(('127.0.0.1', 0))
    try:
        ip = ipaddress.ip_address(host)
        destination = bytes([1 if ip.version == 4 else 4]) + ip.packed
    except ValueError:
        destination = b'\x03' + bytes([len(host)]) + host.encode()
    with socket.create_connection(('127.0.0.1', mixed), timeout=3) as control:
        control.sendall(b'\x05\x01\x00')
        assert UDP['read'](control, 2) == b'\x05\x00'
        control.sendall(b'\x05\x03\x00\x01' + b'\x00' * 6)
        assert UDP['read'](control, 3) == b'\x05\x00\x00'
        relay = UDP['address'](control)
        sock.settimeout(1)
        sock.sendto(b'\x00\x00\x00' + destination + struct.pack('!H', port) + b'fixture', relay)
        response = sock.recv(4096)
        kind = response[3]
        size = 10 if kind == 1 else 7 + response[4] if kind == 3 else 22
        return response[size:].decode()


def stop(core):
    core.terminate()
    try:
        core.wait(timeout=5)
    except subprocess.TimeoutExpired:
        core.kill()
        core.wait(timeout=5)


def run_protocol(args, source, protocol):
    checks, core = [], None
    with tempfile.TemporaryDirectory(prefix='mihomo-tunnel-') as directory, ExitStack() as stack:
        runtime = Path(directory)
        providers, evidence, manifest_sha = RR['prepare_rules'](
            source, args.rules_dir, args.google_fallback, runtime)

        def serve(server):
            threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
            return server

        node_names = {key: f'机场名称{int(key[-2:])}-fixture' for key in source['proxy-providers']}
        labels = ['DIRECT', GENERAL, 'OTHER', *node_names.values(), TCP_ONLY]
        http_server = serve(RR['Server'](('127.0.0.1', 0), RR['Handler']))
        http_server.labels = {f'label{i}': label for i, label in enumerate(labels)}
        http_server.hosts = {host for host, _, _ in CASES}
        outlets = {}
        for i, label in enumerate(labels):
            if protocol == 'tcp' or label == TCP_ONLY:
                outlets[label] = {'type': 'http', 'server': '127.0.0.1',
                                  'port': http_server.server_address[1], 'username': f'label{i}', 'password': 'fixture'}
            else:
                relay = serve(UDP['Relay'](('127.0.0.1', 0), UDP['Echo']))
                relay.label = label
                server = serve(RR['Server'](('127.0.0.1', 0), UDP['Control']))
                server.relay = relay
                outlets[label] = {'type': 'socks5', 'udp': True, 'server': '127.0.0.1',
                                  'port': server.server_address[1]}
        proxy_providers = {}
        for key, name in node_names.items():
            nodes = [dict(outlets[name], name=name)]
            if key == 'Airport_01':
                nodes.append(dict(outlets[MANUAL], name=HOME_NODE))
            if key == 'Airport_04':
                nodes.append(dict(outlets[TCP_ONLY], name=TCP_ONLY))
                nodes.append(dict(outlets[TCP_ONLY], name=HOME_TCP))
            path = runtime / f'{key}.json'
            path.write_text(json.dumps({'proxies': nodes}, ensure_ascii=False))
            proxy_providers[key] = {'type': 'file', 'path': str(path), 'health-check': {'enable': False}}

        groups = []
        for group in source['proxy-groups']:
            if group['name'] in (TUNNEL, GENERAL, HOME, 'GLOBAL'):
                # 保留入口候选、use 和筛选；去掉公网测速 URL，夹具不探测网络。
                controlled = {key: group[key] for key in ('name', 'type', 'proxies', 'use', 'filter', 'empty-fallback') if key in group}
                controlled['proxies'] = [RR['DIRECT_PROXY'] if p == 'DIRECT' else p for p in group.get('proxies', [])]
                groups.append(controlled)
            else:
                outlet = GENERAL if group['name'] in ('机场名称3优先', 'Cloudflare-自动', 'GitHub-自动') else 'OTHER'
                groups.append({'name': group['name'], 'type': 'select', 'proxies': ['fixture-' + outlet]})
        mixed, controller = RR['free_port'](), RR['free_port']()
        fixture = {'mixed-port': mixed, 'external-controller': f'127.0.0.1:{controller}',
                   'bind-address': '127.0.0.1', 'allow-lan': False, 'mode': 'rule', 'log-level': 'warning',
                   'ipv6': True, 'dns': {'enable': False}, 'tun': {'enable': False}, 'sniffer': {'enable': False},
                   'profile': {'store-selected': source['profile']['store-selected'], 'store-fake-ip': False},
                   'hosts': {host: '9.9.9.9' for host, _, _ in CASES if not host[0].isdigit()},
                   'proxies': source['proxies'] + [dict(outlets[label], name='fixture-' + label)
                                                  for label in ('DIRECT', GENERAL, 'OTHER')],
                   'proxy-providers': proxy_providers, 'proxy-groups': groups,
                   'rules': RR['local_direct'](source['rules']), 'rule-providers': providers,
                   'sub-rules': {name: RR['local_direct'](rules) for name, rules in source['sub-rules'].items()}}
        config = runtime / 'config.json'
        config.write_text(json.dumps(fixture, ensure_ascii=False))

        def api(path, body=None, method="PUT"):
            if body is None:
                return RR['get_json'](controller, path)
            connection = http.client.HTTPConnection('127.0.0.1', controller, timeout=3)
            try:
                connection.request(method, path, json.dumps(body), {'Content-Type': 'application/json'})
                response = connection.getresponse()
                assert response.status == 204, response.read()
            finally:
                connection.close()

        def group(name):
            return api('/proxies/' + urllib.parse.quote(name, safe=''))

        def choose(name, target):
            api('/proxies/' + urllib.parse.quote(name, safe=''), {'name': target})
            assert group(name)['now'] == target

        def start():
            with (runtime / 'core.log').open('a') as log:
                process = subprocess.Popen([args.mihomo, '-d', directory, '-f', str(config)], stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 15
            try:
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        loaded = api('/providers/rules')['providers']
                        choices = group(TUNNEL)['all']
                        if set(loaded) == set(providers) and all(p['ruleCount'] for p in loaded.values()) and TCP_ONLY in choices:
                            return process
                    except (OSError, http.client.HTTPException):
                        pass
                    time.sleep(.1)
                raise AssertionError((runtime / 'core.log').read_text()[-3000:])
            except BaseException:
                stop(process)
                raise

        def tcp_request(host, port):
            authority = f'[{host}]' if ':' in host else host
            return RR['get_json'](mixed, f'http://{authority}:{port}/tunnel-test')['policy']

        def expect(phase, cases, tunnel, general):
            for host, port, entry in cases:
                wanted = {TUNNEL: tunnel, GENERAL: general, 'DIRECT': 'DIRECT'}[entry]
                actual = tcp_request(host, port) if protocol == 'tcp' else udp_request(mixed, host, port, stack)
                assert actual == wanted, (protocol, phase, host, port, wanted, actual)
                checks.append({'phase': phase, 'host': host, 'port': port, 'outlet': actual})

        try:
            validation = subprocess.run([args.mihomo, '-t', '-d', directory, '-f', str(config)], capture_output=True, text=True, timeout=15)
            assert validation.returncode == 0, validation.stdout + validation.stderr
            core = start()
            version = api('/version')
            assert group(TUNNEL)['now'] == RR['DIRECT_PROXY']
            assert set(group(TUNNEL)['all']) == {
                *(RR['DIRECT_PROXY'] if p == 'DIRECT' else p for p in source['Direct_Select']['proxies']),
                *node_names.values(), TCP_ONLY, HOME_NODE, HOME_TCP}
            expect('default', CASES, 'DIRECT', GENERAL)
            for candidate, outlet in [('机场名称1优先-自动', 'OTHER'), ('机场名称3优先-自动', GENERAL),
                                      ('日本·机场名称3优先', 'OTHER')]:
                choose(TUNNEL, candidate)
                expect('tunnel-automatic-' + candidate, WITNESSES, outlet, GENERAL)
            choose(HOME, HOME_NODE)
            choose(TUNNEL, HOME)
            expect('tunnel-shared-home', WITNESSES, MANUAL, GENERAL)
            choose(TUNNEL, MANUAL)
            expect('tunnel-manual', CASES, MANUAL, GENERAL)
            choose(GENERAL, OTHER_MANUAL)
            expect('general-independent', WITNESSES, MANUAL, OTHER_MANUAL)
            choose(TUNNEL, '机场名称3优先-自动')
            choose('GLOBAL', MANUAL)
            stop(core)
            core = None
            core = start()
            assert group(TUNNEL)['now'] == '机场名称3优先-自动' and group(GENERAL)['now'] == OTHER_MANUAL
            expect('restart', WITNESSES, GENERAL, OTHER_MANUAL)
            choose(TUNNEL, RR['DIRECT_PROXY'])
            expect('tunnel-direct-independent', WITNESSES, 'DIRECT', OTHER_MANUAL)
            assert group('GLOBAL')['now'] == MANUAL
            api('/configs', {'mode': 'global'}, method='PATCH')
            for host, port, _ in WITNESSES:
                actual = tcp_request(host, port) if protocol == 'tcp' else udp_request(mixed, host, port, stack)
                assert actual == MANUAL, ('global-single-node', host, port, actual)
                checks.append({'phase': 'global-single-node', 'host': host, 'port': port, 'outlet': actual})
            api('/configs', {'mode': 'rule'}, method='PATCH')
            expect('return-to-rule', WITNESSES, 'DIRECT', OTHER_MANUAL)


            for candidate in (TCP_ONLY, HOME):
                choose(HOME, HOME_TCP)
                choose(TUNNEL, candidate)
                for host in (DOMAINS[0], IPS[0], IPS[20]):
                    assert tcp_request(host, 7844) == TCP_ONLY
                    checks.append({'phase': 'tcp-only-node-tcp', 'host': host, 'port': 7844, 'outlet': TCP_ONLY})
                    if protocol == 'udp':
                        try:
                            actual = udp_request(mixed, host, 7844, stack)
                        except socket.timeout:
                            checks.append({'phase': 'tcp-only-node-udp', 'host': host, 'port': 7844, 'outlet': 'REJECT/no relay response'})
                        else:
                            raise AssertionError(('不支持UDP的手选节点发生规则下落', host, actual))
                    assert group(TUNNEL)['now'] == candidate
        finally:
            if core is not None:
                stop(core)
        return {'protocol': protocol, 'mihomo': version, 'provider_count': len(providers),
                'manifest_sha256': manifest_sha, 'providers': evidence, 'checks': checks}


def main():
    signal.signal(signal.SIGTERM, RR['interrupted'])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('MIHOMO_DESIGN_CONFIG', ROOT / 'configfull_new.yaml')))
    parser.add_argument('--rules-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--mihomo', default=os.environ.get('MIHOMO_BIN', 'mihomo'))
    parser.add_argument('--google-fallback', type=Path, default=ROOT / 'rules/Domain/google.mrs')
    args = parser.parse_args()
    source, config_sha = RR['load_config'](args.config)
    tunnel = next(g for g in source['proxy-groups'] if g['name'] == TUNNEL)
    assert tunnel == dict(source['Direct_Select'], name=TUNNEL)
    assert set(tunnel['use']) == set(source['proxy-providers'])
    assert tunnel['filter'] == '.*' and tunnel['empty-fallback'] == 'REJECT'
    assert 'interval' not in tunnel and source['profile']['store-selected'] is True
    addresses = source['rule-providers']['cloudflare_tunnel_ip']
    assert addresses['type'] == 'inline' and addresses['behavior'] == 'ipcidr'
    assert len(addresses['payload']) == 40
    assert set(addresses['payload']) == {f'{ip}/{128 if ":" in ip else 32}' for ip in IPS}
    results = [run_protocol(args, source, protocol) for protocol in ('tcp', 'udp')]
    report = {'config': str(args.config.resolve()), 'config_sha256': config_sha, 'results': results,
              'scope': '真实公开规则与内联端点；回环TCP/UDP，关闭DNS/TUN/嗅探；不证明公网QUIC、真实节点或健康回退。HTTP节点UDP超时证明未落回任何回环出口，不单独模拟REJECT的数据包实现。'}
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS: {args.config.name}，{sum(len(r["checks"]) for r in results)} 次 Tunnel TCP/UDP 检查；40精确地址、端口边界、手选隔离、重启与不支持UDP的节点。')


if __name__ == '__main__':
    main()
