#!/usr/bin/env python3
"""保留真实组链、缓存和生产探测参数，验证重启/重载及 HTTP 更新。"""

import argparse
import copy
import ipaddress
import json
from pathlib import Path
import runpy
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


D = runpy.run_path(str(Path(__file__).with_name('test-config-design.py')))
H = D['H']
DNS = runpy.run_path(str(Path(__file__).with_name('test-dns-policy.py')))


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        state, label = self.server.state, self.server.label
        try:
            line = self.rfile.readline().decode().strip()
            if line.startswith('CONNECT '):
                while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                    pass
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                line = self.rfile.readline().decode().strip()
            method, target, _ = line.split(' ', 2)
            while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                pass
            path = urllib.parse.urlsplit(target).path
            if path in state['subscriptions']:
                status, body = 200, state['subscriptions'][path]
            elif path == '/rules.mrs':
                status, body = (503, b'') if state['offline'] else (200, state['rules'])
            elif method == 'HEAD':
                status = 503 if path == '/github' and label[:1] in state['bad_github'] else (
                    200 if path == '/github' else 204)
                time.sleep(.01)
                body = b''
            else:
                status, body = 200, label.encode()
            state['events'].append({'at': time.monotonic(), 'node': label, 'method': method,
                                    'path': path, 'status': status})
            self.wfile.write((f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n'
                             'Connection: close\r\n\r\n').encode() + body)
        except (OSError, ValueError):
            pass


def main(config_path):
    source = D['load_source'](config_path)
    servers, core, checks = [], None, []
    state = {'bad_github': set(), 'offline': False, 'subscriptions': {},
             'events': [], 'rules': (D['ROOT'] / 'rules/Domain/dev-download.mrs').read_bytes()}
    with tempfile.TemporaryDirectory(prefix='mihomo-runtime-lifecycle-') as directory:
        directory = Path(directory)
        try:
            nodes = {}
            for provider in source['proxy-providers']:
                airport = str(int(provider[-2:]))
                nodes[provider] = []
                for region, name in [('JP', '日本01'), ('HK', '香港01'), ('SG', '新加坡01')]:
                    server = D['Server'](('127.0.0.1', 0), Handler)
                    server.label, server.state = airport + '-' + region, state
                    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
                    servers.append(server)
                    nodes[provider].append({'name': name, 'type': 'http', 'server': '127.0.0.1',
                                            'port': server.server_address[1]})
                state['subscriptions']['/' + provider] = json.dumps({'proxies': nodes[provider]}).encode()
            origin = D['Server'](('127.0.0.1', 0), Handler)
            origin.label, origin.state = 'DIRECT', state
            upstream = socketserver.ThreadingUDPServer(('127.0.0.1', 0), DNS['DNSHandler'])
            upstream.answer, upstream.answers, upstream.queries = '127.0.0.1', {}, set()
            for server in (origin, upstream):
                threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
                servers.append(server)
            origin_url = f'http://127.0.0.1:{origin.server_address[1]}'
            local_dns = f'udp://127.0.0.1:{upstream.server_address[1]}#DIRECT'
            mixed, control, dns_port = [H['free_port']() for _ in range(3)]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            home = directory / 'current'
            runtime = home / 'config.json'

            def build(original):
                home.mkdir(exist_ok=True)
                groups = copy.deepcopy(original['proxy-groups'])
                urls = {original[key]['url']: origin_url + path for key, path in (
                    ('Fallback_Base', '/google'), ('GitHub_Urltest_Base', '/github'),
                    ('Cloudflare_Urltest_Base', '/cloudflare'))}
                for group in groups:
                    if 'url' in group:
                        group['url'] = urls[group['url']]
                providers = copy.deepcopy(original['proxy-providers'])
                for name, provider in providers.items():
                    provider.update(url=origin_url + '/' + name, path=str(home / (name + '.json')))
                    provider['health-check']['url'] = origin_url + '/google'
                # 保留全部自动组、筛选、override 和周期/超时/lazy/失败次数，只替换外部服务地址。
                rules = {name: {'type': 'inline', 'behavior': item['behavior'], 'payload': item.get('payload', [])}
                         for name, item in original['rule-providers'].items()}
                membership = {'google_domain': ['google.com'], 'telegram_domain': ['telegram.org'],
                              'communication_domain': ['line.me'], 'ai!cn_domain': ['chatgpt.com'],
                              'github_domain': ['github.com', 'codeload.github.com']}
                for name, payload in membership.items():
                    rules[name]['payload'] = payload
                rules['dev_download_domain'] = {**original['rule-providers']['dev_download_domain'],
                    'url': origin_url + '/rules.mrs', 'path': str(home / 'dev-download.mrs')}
                dns = copy.deepcopy(original['dns'])
                dns.update({'listen': f'127.0.0.1:{dns_port}', 'use-system-hosts': False,
                            'default-nameserver': [local_dns], 'nameserver': [local_dns],
                            'proxy-server-nameserver': [local_dns], 'direct-nameserver': [local_dns]})
                dns['nameserver-policy'] = {key: value if isinstance(value, str) and value.startswith('rcode://')
                                           else [local_dns] for key, value in dns['nameserver-policy'].items()}
                runtime.write_text(json.dumps({'mixed-port': mixed, 'external-controller': f'127.0.0.1:{control}',
                    'bind-address': '127.0.0.1', 'allow-lan': False, 'mode': 'rule', 'log-level': 'debug',
                    'tun': {'enable': False}, 'dns': dns, 'profile': original['profile'],
                    'unified-delay': original['unified-delay'], 'proxies': original['proxies'],
                    'proxy-groups': groups, 'proxy-providers': providers, 'rule-providers': rules,
                    'rules': original['rules'], 'sub-rules': original['sub-rules']}, ensure_ascii=False))

            def api(path, body=None, method='GET'):
                data = json.dumps(body).encode() if body is not None else None
                request = urllib.request.Request(f'http://127.0.0.1:{control}{path}', data=data, method=method,
                                                 headers={'Content-Type': 'application/json'})
                with opener.open(request, timeout=5) as response:
                    return json.load(response) if response.status != 204 else None

            def group(name):
                return api('/proxies/' + urllib.parse.quote(name, safe=''))

            def choose(name, target):
                api('/proxies/' + urllib.parse.quote(name, safe=''), {'name': target}, 'PUT')

            def start():
                nonlocal core
                with (home / 'core.log').open('a') as log:
                    core = subprocess.Popen([H['MIHOMO'], '-d', str(home), '-f', str(runtime)],
                                            stdout=log, stderr=subprocess.STDOUT)
                H['until'](lambda: api('/version'), seconds=10)
                def providers_ready():
                    items = api('/providers/proxies')['providers']
                    return all((items.get(name) or {}).get('proxies') for name in nodes)
                H['until'](providers_ready)

            def stop():
                nonlocal core
                H['stop_core'](core)
                core = None

            def request(host, port=80):
                result = subprocess.run(['curl', '-q', '--silent', '--show-error', '--fail', '--noproxy', '',
                    '--proxy', f'http://127.0.0.1:{mixed}', '--max-time', '3', f'http://{host}:{port}/file'],
                    capture_output=True, text=True, timeout=4)
                return result.returncode, result.stdout

            def expect(host, label, seconds=75, port=80):
                samples = []
                def observed():
                    actual = request(host, port)
                    samples.append({'at': time.monotonic(), 'exit': actual[0], 'outlet': actual[1]})
                    return actual == (0, label)
                try:
                    H['until'](observed, seconds=seconds)
                except AssertionError:
                    raise AssertionError({'host': host, 'expected': label, 'samples': samples}) from None

            def fake_ip(host):
                rcode, ips = DNS['query'](dns_port, host)
                assert rcode == 0 and len(ips) == 1 and ipaddress.ip_address(ips[0]) in ipaddress.ip_network('198.18.0.0/15'), (host, rcode, ips)
                return ips[0]

            def mappings():
                result = {host: fake_ip(host) for host in ('first.lifecycle-fixture.net', 'second.lifecycle-fixture.net')}
                assert len(set(result.values())) == 2, result
                return result

            home, runtime = directory / 'current', directory / 'current/config.json'
            print('验证重启/重载、订阅异常及共享家宽缓存', file=sys.stderr, flush=True)
            build(source)
            start()
            chosen = {'Telegram': '[机场名称3]新加坡01', '境外通信': '[机场名称4]香港01',
                      '纯下载': '日本·机场名称3优先', 'AI': '[机场名称1]日本01',
                      'Cloudflare Tunnel': '[机场名称4]新加坡01', 'GLOBAL': '[机场名称4]香港01'}
            for name, target in chosen.items():
                choose(name, target)
            cached = mappings()

            def preserved():
                for name, target in chosen.items():
                    H['until'](lambda: group(name)['now'] == target)
                for host, label in [('telegram.org', '3-SG'), ('line.me', '4-HK'),
                                    ('codeload.github.com', '3-JP'), ('chatgpt.com', '1-JP')]:
                    expect(host, label)
                expect('region1.v2.argotunnel.com', '4-SG', port=7844)
                assert {host: fake_ip(host) for host in reversed(cached)} == cached
                api('/configs', {'mode': 'global'}, 'PATCH')
                expect('google.com', '4-HK')
                api('/configs', {'mode': 'rule'}, 'PATCH')

            stop()
            start()
            preserved()
            api('/configs?force=true', {'path': str(runtime)}, 'PUT')
            preserved()
            checks.append('重启/重载保持独立手选、Tunnel/GLOBAL 和两个不同 Fake-IP 的逆序映射')

            provider_path = '/providers/proxies/Airport_03'
            subscription_cache = home / 'Airport_03.json'
            old_bytes = subscription_cache.read_bytes()
            old_names = [p['name'] for p in api('/providers/proxies')['providers']['Airport_03']['proxies']]
            for bad in (b'invalid subscription', b'{"proxies": []}'):
                state['subscriptions']['/Airport_03'] = bad
                before = len(state['events'])
                try:
                    api(provider_path, method='PUT')
                except urllib.error.HTTPError as error:
                    assert error.code >= 400
                else:
                    raise AssertionError('无效/空订阅不应替换旧池')
                assert any(e.get('path') == '/Airport_03' for e in state['events'][before:])
                assert subscription_cache.read_bytes() == old_bytes
                assert [p['name'] for p in api('/providers/proxies')['providers']['Airport_03']['proxies']] == old_names
                preserved()
            # 删除手选候选回到默认；同名候选恢复后重新使用原保存选择。
            for available, expected, label in [(nodes['Airport_03'][:2], '机场名称1优先-自动', '1-JP'),
                                               (nodes['Airport_03'], chosen['Telegram'], '3-SG')]:
                state['subscriptions']['/Airport_03'] = json.dumps({'proxies': available}).encode()
                api(provider_path, method='PUT')
                H['until'](lambda: group('Telegram')['now'] == expected)
                expect('telegram.org', label)
                expect('line.me', '4-HK')
            checks.append('HTTP 无效/空订阅保留候选与磁盘缓存；候选删除/恢复只影响相关手选')

            # 家宽候选通过真实 HTTP 订阅加入，验证共享子选择也持久化。
            homes = [{**nodes['Airport_04'][0], 'name': '日本自建'}, {**nodes['Airport_04'][1], 'name': '香港家宽'}]
            state['subscriptions']['/Airport_04'] = json.dumps({'proxies': nodes['Airport_04'] + homes}).encode()
            api('/providers/proxies/Airport_04', method='PUT')
            H['until'](lambda: '[机场名称4]香港家宽' in group('自建/家宽节点')['all'])
            for name in ('AI', '开发下载', 'GLOBAL'):
                choose(name, '自建/家宽节点')
            choose('自建/家宽节点', '[机场名称4]香港家宽')
            stop()
            start()
            for name in ('AI', '开发下载', 'GLOBAL'):
                H['until'](lambda: group(name)['now'] == '自建/家宽节点')
            assert group('自建/家宽节点')['now'] == '[机场名称4]香港家宽'
            expect('chatgpt.com', '4-HK')
            expect('github.com', '4-HK')
            expect('telegram.org', '3-SG')
            choose('自建/家宽节点', '[机场名称4]日本自建')
            expect('chatgpt.com', '4-JP')
            expect('github.com', '4-JP')
            checks.append('共享家宽子选择跨重启保持，换点影响选择它的业务，Telegram 手选独立')

            # 更新链保留完整组结构；本阶段主动触发健康检查，加速逐机场故障枚举。
            rule_path = '/providers/rules/dev_download_domain'
            print('验证 HTTP 规则更新链及离线缓存', file=sys.stderr, flush=True)
            chain = [('3', 'GitHub-机场名称3'), ('1', 'GitHub-机场名称1')]
            if 'Airport_02' in nodes:
                chain.append(('2', 'GitHub-机场名称2'))
            chain += [('4', 'GitHub-机场名称4'), ('DIRECT', 'DIRECT')]
            for airport, expected in chain:
                for name in nodes:
                    api('/providers/proxies/' + name + '/healthcheck')
                attempts = []
                def updated():
                    # 查询 now 不会 Touch；实际更新才能唤醒 lazy 的父组探测。
                    before = len(state['events'])
                    api(rule_path, method='PUT')
                    fetches = [e for e in state['events'][before:] if e.get('path') == '/rules.mrs' and e['method'] == 'GET']
                    selected = group('规则更新')['now']
                    attempts.append({'selected': selected, 'fetches': fetches})
                    reached = fetches and all(e['node'] == 'DIRECT' if airport == 'DIRECT'
                                              else e['node'].startswith(airport + '-') for e in fetches)
                    return fetches if selected == expected and reached else False
                try:
                    fetches = H['until'](updated, seconds=75)
                except AssertionError:
                    raise AssertionError({'rule_update': expected, 'recent_attempts': attempts[-3:]}) from None
                assert (home / 'dev-download.mrs').read_bytes() == state['rules']
                checks.append({'rule_update': expected, 'fetches': fetches, 'attempts': len(attempts)})
                state['bad_github'].add(airport)
            count = api('/providers/rules')['providers']['dev_download_domain']['ruleCount']
            assert count > 0
            state['offline'] = True

            def offline_update():
                before = len(state['events'])
                try:
                    api(rule_path, method='PUT')
                except urllib.error.HTTPError as error:
                    assert error.code == 503, error
                else:
                    raise AssertionError('离线规则源应返回错误')
                assert any(e.get('path') == '/rules.mrs' and e['status'] == 503 for e in state['events'][before:])
                assert (home / 'dev-download.mrs').read_bytes() == state['rules']
                assert api('/providers/rules')['providers']['dev_download_domain']['ruleCount'] == count
                expect('unpkg.com', '4-JP')

            offline_update()
            stop()
            start()
            H['until'](lambda: api('/providers/rules')['providers']['dev_download_domain']['ruleCount'] == count)
            offline_update()
            checks.append('HTTP 规则更新逐机场回退到 DIRECT；503 保留 MRS 缓存，离线重启后仍实际匹配开发下载')
            print(json.dumps({'passed': True, 'config': str(config_path), 'checks': checks,
                              'scope': '本地少节点回环、完整组链'}, ensure_ascii=False, indent=2))
        except BaseException:
            for log in directory.glob('*/core.log'):
                print(f'{log}:\n{log.read_text()[-6000:]}', file=sys.stderr)
            raise
        finally:
            if core is not None:
                H['stop_core'](core)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=D['CONFIG'])
    args = parser.parse_args()
    main(args.config)
