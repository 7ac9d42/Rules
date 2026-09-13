#!/usr/bin/env python3
"""官方核心 UDP 规则模式：真实 SOCKS5 UDP 中继验证业务手选与层级地区偏好。

复用候选的主规则、子规则和 rematch；自动健康池替换为带标签的回环出口。
这里只验证 UDP 转发选路，健康/地区回退由 test-config-design.py 覆盖。
"""
import argparse
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import runpy
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request

D = runpy.run_path(str(Path(__file__).with_name('test-config-design.py')))
H = D['H']


def read(sock, size):
    result = b''
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise OSError('SOCKS control closed')
        result += chunk
    return result


def address(sock):
    kind = read(sock, 1)[0]
    if kind == 1:
        host = socket.inet_ntoa(read(sock, 4))
    elif kind == 3:
        host = read(sock, read(sock, 1)[0]).decode()
    else:
        raise ValueError(kind)
    return host, struct.unpack('!H', read(sock, 2))[0]


class Relay(socketserver.ThreadingUDPServer):
    daemon_threads = True


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        packet, sock = self.request
        if packet[:3] != b'\x00\x00\x00':
            return
        kind = packet[3]
        size = 10 if kind == 1 else 7 + packet[4] if kind == 3 else 22
        sock.sendto(packet[:size] + self.server.label.encode(), self.client_address)


class DirectEcho(socketserver.BaseRequestHandler):
    def handle(self):
        _, sock = self.request
        sock.sendto(b'UNEXPECTED_DIRECT', self.client_address)


class Control(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(10)
        try:
            assert read(sock, 1) == b'\x05'
            read(sock, read(sock, 1)[0])
            sock.sendall(b'\x05\x00')
            assert read(sock, 3) == b'\x05\x03\x00'
            address(sock)
            host, port = self.server.relay.server_address
            sock.sendall(b'\x05\x00\x00\x01' + socket.inet_aton(host) + struct.pack('!H', port))
            while sock.recv(1):
                pass
        except (OSError, AssertionError, ValueError):
            return


def request(mixed, host, udp_sockets, target_port=12345):
    # 新 SOCKS 关联不清除旧 UDP NAT；整轮持有源端口，避免复用后继承旧出口。
    udp = udp_sockets.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    udp.bind(('127.0.0.1', 0))
    with socket.create_connection(('127.0.0.1', mixed), timeout=3) as control:
        control.sendall(b'\x05\x01\x00')
        assert read(control, 2) == b'\x05\x00'
        control.sendall(b'\x05\x03\x00\x01' + b'\x00' * 6)
        assert read(control, 3) == b'\x05\x00\x00'
        target = address(control)
        packet = b'\x00\x00\x00\x03' + bytes([len(host)]) + host.encode() + struct.pack('!H', target_port) + b'fixture'
        udp.settimeout(3)
        udp.sendto(packet, target)
        response = udp.recv(4096)
        kind = response[3]
        size = 10 if kind == 1 else 7 + response[4] if kind == 3 else 22
        return response[size:].decode()


def main(config_path=D['CONFIG']):
    source = D['load_source'](config_path)
    with_home = 'Airport_02' in source['proxy-providers']
    high_japan = '日本·机场名称2优先' if with_home else '日本·机场名称1优先'
    high = {family: ('home-' if with_home else 'quality-') + family for family in ('generic', 'cf', 'github')}
    high_jp = {family: ('jp-high-' if with_home else 'jp-normal-') + family for family in ('generic', 'cf', 'github')}
    servers, core, checks = [], None, []
    with tempfile.TemporaryDirectory(prefix='mihomo-rematch-udp-') as directory, ExitStack() as udp_sockets:
        try:
            # 标签区分自动路径；这里不模拟各路径中的节点健康与延迟。
            route_labels = {
                'AI-机场名称1-日本': 'ai-jp-cf',
                '机场名称1优先': 'quality-generic', '机场名称3优先': 'cost-generic',
                'Cloudflare-机场名称1优先': 'quality-cf', 'Cloudflare-自动': 'cost-cf',
                'GitHub-机场名称1优先': 'quality-github', 'GitHub-自动': 'cost-github',
                '纯下载-自动': 'download',
                '日本-机场名称1优先': 'jp-normal-generic',
                'Cloudflare-日本-地区优先': 'jp-normal-cf',
                'GitHub-日本-地区优先': 'jp-normal-github',
                '日本-成本优先': 'jp-cost-generic',
                'Cloudflare-日本-成本优先': 'jp-cost-cf',
                'GitHub-日本-成本优先': 'jp-cost-github',
                '家宽优先': 'home-generic',
                'Cloudflare-家宽优先': 'home-cf',
                'GitHub-家宽优先': 'home-github',
                '日本-高要求': 'jp-high-generic',
                'Cloudflare-日本-高要求': 'jp-high-cf',
                'GitHub-日本-高要求': 'jp-high-github',
            }
            manual_labels = ('manual', 'manual-dev', 'manual-download', 'manual-general', 'manual-finance',
                             'manual-ms', 'manual-netflix', 'manual-disney', 'manual-comm', 'manual-social', 'manual-game', 'direct')
            groups, labels = [], set(manual_labels)
            for group in source['proxy-groups']:
                if group['type'] == 'select':
                    choices = group.get('proxies', []) + ['fixture-' + label for label in manual_labels]
                else:
                    family = 'cf' if group['name'].startswith('Cloudflare-') else 'github' if group['name'].startswith(('GitHub-', '纯下载-')) else 'generic'
                    label = route_labels.get(group['name'], family)
                    labels.add(label)
                    choices = ['fixture-' + label]
                choices.append('fixture-no-udp')
                groups.append({'name': group['name'], 'type': 'select',
                               'proxies': ['fixture-direct' if p == 'DIRECT' else p for p in choices]})
            fixture_proxies = []
            for label in sorted(labels):
                relay = Relay(('127.0.0.1', 0), Echo)
                relay.label = label
                server = D['Server'](('127.0.0.1', 0), Control)
                server.relay = relay
                for item in (relay, server):
                    threading.Thread(target=item.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
                    servers.append(item)
                fixture_proxies.append({'name': 'fixture-' + label, 'type': 'socks5', 'udp': True,
                                        'server': '127.0.0.1', 'port': server.server_address[1]})
            fixture_proxies.append({'name': 'fixture-no-udp', 'type': 'http',
                                    'server': '127.0.0.1', 'port': servers[0].server_address[1]})
            providers = {name: {'type': 'inline', 'behavior': provider['behavior'], 'payload': []}
                         for name, provider in source['rule-providers'].items()}
            docker_r2 = 'docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com'
            members = {
                'cloudflare_domain': ['cf.invalid', 'dev.cf.invalid', 'paypal.cf.invalid',
                                      'wise.cf.invalid', 'ordinary.cf.invalid', 'microsoft.cf.invalid',
                                      'netflix.cf.invalid', 'disney.cf.invalid', 'reddit.cf.invalid',
                                      'discord.cf.invalid', 'appletv.cf.invalid', 'blocked.cf.invalid', docker_r2],
                'github_domain': ['gh.invalid', 'download.invalid', 'wise.gh.invalid'],
                'dev_download_domain': ['dev.invalid', 'dev.cf.invalid'],
                'pure_download_domain': ['download.invalid'],
                'google_domain': ['ordinary.invalid', 'ordinary.cf.invalid'],
                'fcm_domain': ['fcm.invalid'],
                'googlevpn_domain': ['googlevpn.invalid'],
                'microsoft_domain': ['microsoft.invalid', 'microsoft.cf.invalid'],
                'onedrive_domain': ['onedrive.invalid'],
                'netflix_domain': ['netflix.invalid', 'netflix.cf.invalid'],
                'disney_domain': ['disney.invalid', 'disney.cf.invalid'],
                'reddit_domain': ['reddit.invalid', 'reddit.cf.invalid'],
                'telegram_domain': ['telegram.invalid'],
                'line_domain': ['line.invalid'],
                'discord_domain': ['discord.cf.invalid'],
                'signal_domain': ['signal.invalid'],
                'communication_domain': ['communication.invalid'],
                'tiktok_domain': ['tiktok.invalid'],
                'youtube_domain': ['youtube.invalid'],
                'appleTV_domain': ['appletv.cf.invalid'],
                'meta_domain': ['meta.invalid'],
                'social_media_non_cn_domain': ['x.invalid', 'reddit.invalid', 'reddit.cf.invalid'],
                'TVB_domain': ['mytv2.invalid'],
                'steam_domain': ['steam.invalid'],
                'Epic_domain': ['epic.invalid'],
                'ai!cn_domain': ['ai.invalid'],
                'paypal_domain': ['paypal.invalid', 'paypal.cf.invalid'],
                'Wise_domain': ['wise.invalid', 'wise.cf.invalid', 'wise.gh.invalid'],
                'talkatone_domain': ['talk.invalid'],
                'banAd_core_domain': ['blocked.cf.invalid'],
            }
            members['communication_domain'] += ['whatsapp.invalid', 'viber.invalid']
            members['meta_domain'] += ['whatsapp.invalid']
            members['ecommerce_domain'] = ['viber.invalid']
            members['social_media_non_cn_domain'] += ['social-ms.invalid']
            members['microsoft_domain'] += ['social-ms.invalid', 'ms-ip-overlap.invalid']
            members['cn_domain'] = ['cn-ip-overlap.invalid']
            members['bilibili_ip'] = ['106.75.74.76/32']
            for name, payload in members.items():
                providers[name]['payload'] = payload
            hosts = ['unknown.invalid', 'registry-1.docker.io', 'huggingface.co', 'mytv.com.hk',
                     *{host for payload in members.values() for host in payload}]
            # Every real-IP witness still exits through a loopback proxy.
            hosts.extend(['opencode.ai', 'origin-tracker.githubusercontent.com',
                          'copilotprodattachments.blob.core.windows.net'])
            ip_hosts = dict.fromkeys(['cn-ip-overlap.invalid', 'ms-ip-overlap.invalid',
                                     'ip-only-bilibili.invalid'], '106.75.74.76')
            hosts.extend(ip_hosts)
            def local_direct(rule):
                parts = rule.split(',')
                action = -2 if parts[-1] == 'no-resolve' else -1
                if parts[action] == 'DIRECT':
                    parts[action] = 'fixture-direct'
                return ','.join(parts)
            mixed, controller = H['free_port'](), H['free_port']()
            config = {'mixed-port': mixed, 'external-controller': f'127.0.0.1:{controller}',
                      'bind-address': '127.0.0.1', 'allow-lan': False, 'mode': 'rule', 'log-level': 'info',
                      'dns': {'enable': False}, 'tun': {'enable': False},
                      'hosts': {**dict.fromkeys(hosts, '127.0.0.1'), **ip_hosts},
                      'proxies': copy.deepcopy(source['proxies']) + fixture_proxies,
                      'proxy-groups': groups, 'rule-providers': providers,
                      'rules': [local_direct(rule) for rule in source['rules']],
                      'sub-rules': {name: [local_direct(rule) for rule in rules]
                                    for name, rules in source['sub-rules'].items()}}
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config, ensure_ascii=False))
            validation = subprocess.run([H['MIHOMO'], '-t', '-d', directory, '-f', str(path)], capture_output=True, text=True, timeout=10)
            assert validation.returncode == 0, validation.stdout + validation.stderr
            core_log = Path(directory) / 'core.log'
            with core_log.open('w') as output:
                core = subprocess.Popen([H['MIHOMO'], '-d', directory, '-f', str(path)],
                                        stdout=output, stderr=subprocess.STDOUT)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path, body=None, method='GET'):
                data = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(f'http://127.0.0.1:{controller}{path}', data=data,
                                             method=method, headers={'Content-Type': 'application/json'})
                with opener.open(req, timeout=3) as response:
                    return response.status
            def choose(group, target):
                api('/proxies/' + urllib.parse.quote(group), {'name': target}, 'PUT')

            def expect(mode, cases):
                for host, expected in cases:
                    actual = request(mixed, host, udp_sockets)
                    assert actual == expected, (mode, host, expected, actual)
                    checks.append({'mode': mode, 'host': host, 'outlet': actual})

            def assert_rejected(host, port=12345):
                # 超时也可能来自 DNS/权限/网络故障，必须确认原生匹配到了 REJECT。
                lines = core_log.read_text().splitlines()
                assert any(f' --> {host}:{port} match ' in line and 'using REJECT' in line
                           for line in lines), ('UDP timed out without a REJECT match', host, lines[-10:])

            H['until'](lambda: api('/version'))
            # Catch both a probe-family escape and rematch's implicit DIRECT fallthrough.
            direct_echo = Relay(('127.0.0.1', 0), DirectEcho)
            threading.Thread(target=direct_echo.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
            servers.append(direct_echo)
            for group, host in [('Cloudflare-自动', 'cf.invalid'), ('GitHub-自动', 'gh.invalid'),
                                ('纯下载-自动', 'download.invalid'), ('机场名称3优先', 'unknown.invalid')]:
                previous = next(g for g in groups if g['name'] == group)['proxies'][0]
                choose(group, 'fixture-no-udp')
                try:
                    actual = request(mixed, host, udp_sockets, direct_echo.server_address[1])
                except socket.timeout:
                    assert_rejected(host, direct_echo.server_address[1])
                    checks.append({'mode': 'auto-unsupported-udp', 'host': host, 'outlet': 'REJECT'})
                else:
                    raise AssertionError(('UDP escaped selected probe family', group, host, actual))
                finally:
                    choose(group, previous)
            choose('哔哩哔哩', 'fixture-manual')
            expect('domain-before-ip-and-vendor', [
                ('cn-ip-overlap.invalid', 'direct'), ('ms-ip-overlap.invalid', 'cost-generic'),
                ('ip-only-bilibili.invalid', 'manual'), ('whatsapp.invalid', 'cost-generic'),
                ('viber.invalid', 'cost-generic'), ('social-ms.invalid', 'quality-generic')])
            expect('auto', [('cf.invalid', 'cost-cf'), ('gh.invalid', 'cost-github'),
                            ('dev.invalid', 'cost-generic'), ('dev.cf.invalid', 'cost-cf'),
                            ('download.invalid', 'download'), ('unknown.invalid', 'cost-generic'),
                            ('ordinary.invalid', 'quality-generic'), ('ordinary.cf.invalid', 'quality-cf'),
                            ('netflix.invalid', high['generic']), ('disney.cf.invalid', high['cf']),
                            ('paypal.invalid', high['generic']), ('reddit.invalid', high['generic']),
                            ('wise.gh.invalid', high['github']),
                            ('telegram.invalid', 'cost-generic'), ('youtube.invalid', 'cost-generic'),
                            ('ai.invalid', 'ai-jp-cf')])
            dev_hosts = ['dev.invalid', 'dev.cf.invalid', 'gh.invalid', 'registry-1.docker.io', docker_r2, 'huggingface.co']
            finance_hosts = ['paypal.invalid', 'paypal.cf.invalid', 'wise.invalid', 'wise.cf.invalid', 'wise.gh.invalid']
            choose('AI', 'fixture-no-udp')
            for host in ['ai.invalid', 'opencode.ai', 'origin-tracker.githubusercontent.com',
                         'copilotprodattachments.blob.core.windows.net']:
                try:
                    actual = request(mixed, host, udp_sockets)
                except socket.timeout:
                    assert_rejected(host)
                    checks.append({'mode': 'ai-unsupported-udp', 'host': host, 'outlet': 'REJECT'})
                else:
                    raise AssertionError(('AI UDP escaped selected route', host, actual))
            choose('AI', 'fixture-manual')
            choose('开发下载', 'fixture-manual-dev')
            expect('dev-github-docker-hf-unified', [(host, 'manual-dev') for host in dev_hosts]
                   + [('download.invalid', 'download'), ('cf.invalid', 'cost-cf')])
            choose('纯下载', 'fixture-manual-download')
            expect('download-independent-manual', [('download.invalid', 'manual-download'), ('gh.invalid', 'manual-dev')])
            choose('通用代理', 'fixture-manual-general')
            expect('independent-cost-businesses', [(docker_r2, 'manual-dev'), ('download.invalid', 'manual-download'),
                                                  ('cf.invalid', 'manual-general'), ('unknown.invalid', 'manual-general')])
            choose('金融', 'fixture-manual-finance')
            expect('finance-unified-manual', [(host, 'manual-finance') for host in finance_hosts]
                   + [('talk.invalid', high['generic'])])
            choose('开发下载', '日本·机场名称3优先')
            expect('cost-region-path', [('dev.invalid', 'jp-cost-generic'), ('dev.cf.invalid', 'jp-cost-cf'),
                                       ('gh.invalid', 'jp-cost-github'), ('registry-1.docker.io', 'jp-cost-generic'),
                                       (docker_r2, 'jp-cost-cf'), ('huggingface.co', 'jp-cost-generic'),
                                       ('download.invalid', 'manual-download'),
                                       ('cf.invalid', 'manual-general')])
            choose('金融', high_japan)
            expect('high-region-path', [('wise.invalid', high_jp['generic']), ('paypal.cf.invalid', high_jp['cf']),
                                       ('wise.gh.invalid', high_jp['github']), ('talk.invalid', high['generic'])])
            choose('Google', '日本·机场名称1优先')
            expect('normal-region-path', [('ordinary.invalid', 'jp-normal-generic'),
                                         ('ordinary.cf.invalid', 'jp-normal-cf'), ('fcm.invalid', 'jp-normal-generic'),
                                         ('googlevpn.invalid', 'jp-normal-generic'), ('microsoft.invalid', 'cost-generic')])
            choose('Microsoft', '日本·机场名称3优先')
            expect('microsoft-cost-region-unified', [('microsoft.invalid', 'jp-cost-generic'), ('microsoft.cf.invalid', 'jp-cost-cf'),
                                                     ('onedrive.invalid', 'jp-cost-generic'), ('ordinary.invalid', 'jp-normal-generic')])
            choose('Microsoft', 'fixture-manual-ms')
            expect('google-microsoft-independent', [('ordinary.invalid', 'jp-normal-generic'),
                                                    ('microsoft.cf.invalid', 'manual-ms'), ('onedrive.invalid', 'manual-ms')])
            choose('境外通信', '日本·机场名称3优先')
            expect('communication-cost-region-unified', [(host, 'jp-cost-generic') for host in
                                                          ('telegram.invalid', 'line.invalid', 'signal.invalid', 'communication.invalid')]
                   + [('discord.cf.invalid', 'jp-cost-cf'), ('ordinary.invalid', 'jp-normal-generic'),
                      ('microsoft.cf.invalid', 'manual-ms')])
            choose('境外通信', 'fixture-manual-comm')
            expect('communication-unified', [(host, 'manual-comm') for host in
                                             ('telegram.invalid', 'line.invalid', 'discord.cf.invalid',
                                              'signal.invalid', 'communication.invalid')]
                   + [('tiktok.invalid', 'quality-generic'), ('ordinary.invalid', 'jp-normal-generic')])
            choose('境外影音', '日本·机场名称3优先')
            expect('media-unified-independent', [('youtube.invalid', 'jp-cost-generic'), ('appletv.cf.invalid', 'jp-cost-cf'),
                                                 ('netflix.invalid', high['generic']), ('discord.cf.invalid', 'manual-comm')])
            choose('境外社媒', 'fixture-manual-social')
            expect('social-unified-reddit-independent', [('meta.invalid', 'manual-social'), ('x.invalid', 'manual-social'),
                                                        ('reddit.invalid', high['generic'])])
            choose('Reddit', high_japan)
            expect('reddit-high-region-independent', [('reddit.invalid', high_jp['generic']), ('reddit.cf.invalid', high_jp['cf']),
                                                      ('meta.invalid', 'manual-social')])
            choose('NETFLIX', high_japan)
            expect('netflix-region-independent', [('netflix.invalid', high_jp['generic']), ('netflix.cf.invalid', high_jp['cf']),
                                                 ('disney.invalid', high['generic']), ('disney.cf.invalid', high['cf'])])
            choose('DisneyPlus', 'fixture-manual-disney')
            expect('disney-manual-independent', [('netflix.invalid', high_jp['generic']), ('netflix.cf.invalid', high_jp['cf']),
                                                ('disney.invalid', 'manual-disney'), ('disney.cf.invalid', 'manual-disney')])
            choose('NETFLIX', 'fixture-manual-netflix')
            choose('DisneyPlus', high_japan)
            expect('media-choices-swapped', [('netflix.invalid', 'manual-netflix'), ('netflix.cf.invalid', 'manual-netflix'),
                                            ('disney.invalid', high_jp['generic']), ('disney.cf.invalid', high_jp['cf']),
                                            ('reddit.cf.invalid', high_jp['cf'])])
            choose('TVB', '日本·机场名称1优先')
            expect('tvb-region-independent', [('mytv.com.hk', 'jp-normal-generic'), ('mytv2.invalid', 'jp-normal-generic'),
                                             ('youtube.invalid', 'jp-cost-generic'), ('netflix.invalid', 'manual-netflix')])
            choose('游戏平台', 'fixture-manual-game')
            expect('steam-games-unified', [('steam.invalid', 'manual-game'), ('epic.invalid', 'manual-game'),
                                          ('gh.invalid', 'jp-cost-github')])
            try:
                request(mixed, 'blocked.cf.invalid', udp_sockets)
            except socket.timeout:
                checks.append({'mode': 'blocked-default', 'host': 'blocked.cf.invalid', 'outlet': 'REJECT'})
            else:
                raise AssertionError('拦截默认应拒绝 UDP 转发')
            choose('隐私拦截', '通用代理')
            expect('blocked-proxy-override', [('blocked.cf.invalid', 'manual-general')])
            choose('通用代理', '机场名称3优先-自动')
            expect('blocked-proxy-auto', [('blocked.cf.invalid', 'cost-cf'), ('unknown.invalid', 'cost-generic')])
            choose('GLOBAL', '日本-成本优先')
            api('/configs', {'mode': 'global'}, 'PATCH')
            expect('global-region-dialable', [(host, 'jp-cost-generic') for host in
                                            ('cf.invalid', 'gh.invalid', 'download.invalid', 'blocked.cf.invalid')])
            api('/configs', {'mode': 'rule'}, 'PATCH')
            expect('rule-mode-restored', [('cf.invalid', 'cost-cf'), ('gh.invalid', 'jp-cost-github'),
                                         ('download.invalid', 'manual-download'), ('blocked.cf.invalid', 'cost-cf')])
            print(json.dumps({'passed': True, 'config': str(Path(config_path).resolve()), 'with_home': with_home,
                              'checks': checks, 'scope': '回环 SOCKS5 UDP 转发；不证明公网 UDP/QUIC 或原健康池回退'}, ensure_ascii=False, indent=2))
        finally:
            if core is not None:
                core.terminate()
                core.wait(timeout=5)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=D['CONFIG'], help='直接读取实际配置文件')
    main(parser.parse_args().config)
