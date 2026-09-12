#!/usr/bin/env python3
"""用文件订阅和本机 HTTP 规则源验证更新链的厂商探针、直连兜底和缓存重启。"""

import argparse
import copy
import json
from pathlib import Path
import runpy
import signal
import socketserver
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
H = runpy.run_path(str(ROOT / 'scripts/proxy-fixture.py'))
SOURCE = json.loads(subprocess.check_output(['ruby', '-ryaml', '-rjson', '-e',
    'puts JSON.generate(YAML.load_file(ARGV[0], aliases: true))', str(ROOT / 'configfull_new.yaml')], timeout=10))
LOCK = threading.Lock()
BAD_GITHUB = {'3'}
OFFLINE = False
FETCHES = []
PAYLOAD = b'payload:\n  - +.update-fixture.test\n'


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            line = self.rfile.readline().decode().strip()
            if line.startswith('CONNECT '):
                while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                    pass
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                line = self.rfile.readline().decode().strip()
            if not line:
                return
            method, target, _ = line.split(' ', 2)
            while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                pass
            path = urllib.parse.urlsplit(target).path
            with LOCK:
                unavailable = OFFLINE or (self.server.label in BAD_GITHUB and path != '/google')
                if method == 'GET' and path == '/rules.yaml':
                    FETCHES.append((self.server.label, not unavailable))
            status = 503 if unavailable else (200 if path in ('/github', '/rules.yaml') else 204)
            body = PAYLOAD if method == 'GET' and status == 200 else b''
            self.wfile.write((f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n'
                             'Connection: close\r\n\r\n').encode() + body)
        except (OSError, ValueError):
            pass


def stop_core(core):
    core.terminate()
    try:
        core.wait(timeout=5)
    except subprocess.TimeoutExpired:
        core.kill()
        core.wait(timeout=5)


def run(legacy=False):
    global OFFLINE
    servers, core = [], None
    with tempfile.TemporaryDirectory(prefix='mihomo-rule-updates-') as directory:
        try:
            nodes = {}
            for label, region in [('DIRECT', ''), ('1', '香港'), ('3', '日本'), ('4', '日本')]:
                server = Server(('127.0.0.1', 0), Handler)
                server.label = label
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
                if label != 'DIRECT':
                    nodes[f'Airport_0{label}'] = [{'name': f'[机场名称{label}]{region}01', 'type': 'http',
                        'server': '127.0.0.1', 'port': server.server_address[1]}]
            origin = f'http://127.0.0.1:{servers[0].server_address[1]}'
            urls = {SOURCE['Fallback_Base']['url']: origin + '/google',
                    SOURCE['GitHub_Urltest_Base']['url']: origin + '/github',
                    SOURCE['Cloudflare_Urltest_Base']['url']: origin + '/cloudflare'}
            groups = copy.deepcopy(SOURCE['proxy-groups'])
            update = next(group for group in groups if group['name'] == '规则更新')
            if legacy:
                update.update(proxies=['机场名称3地区优先', '机场名称1地区优先', '机场名称4地区优先', 'DIRECT'],
                              url=SOURCE['Fallback_Base']['url'], **{'expected-status': 204})
            for group in groups:
                if 'url' in group or group['type'] in ('url-test', 'load-balance'):
                    group['url'] = urls.get(group.get('url'), origin + '/google')
                if group['type'] in ('fallback', 'url-test'):
                    group.update(interval=1, lazy=False)
            providers = {}
            for name, proxies in nodes.items():
                path = Path(directory) / f'{name}.json'
                path.write_text(json.dumps({'proxies': proxies}))
                providers[name] = {'type': 'file', 'path': str(path), 'health-check': {'enable': True,
                    'url': origin + '/google', 'expected-status': 204, 'interval': 1, 'timeout': 1000, 'lazy': False}}
            rules = {name: {'type': 'inline', 'behavior': value['behavior'], 'payload': value.get('payload', [])}
                     for name, value in SOURCE['rule-providers'].items()}
            rules['dev_download_domain'] = {'type': 'http', 'behavior': 'domain', 'format': 'yaml',
                'url': origin + '/rules.yaml', 'path': str(Path(directory) / 'remote-rule.yaml'),
                'proxy': '规则更新', 'interval': 3600}
            control = H['free_port']()
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'external-controller': f'127.0.0.1:{control}', 'log-level': 'silent',
                'dns': {'enable': False}, 'tun': {'enable': False}, 'profile': SOURCE['profile'],
                'unified-delay': SOURCE['unified-delay'], 'proxies': SOURCE['proxies'], 'proxy-groups': groups, 'proxy-providers': providers,
                'rule-providers': rules, 'rules': SOURCE['rules'], 'sub-rules': SOURCE['sub-rules']}, ensure_ascii=False))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, method='GET'):
                request = urllib.request.Request(f'http://127.0.0.1:{control}' + path, method=method)
                try:
                    with opener.open(request, timeout=3) as response:
                        return response.status, json.load(response) if response.status != 204 else None
                except urllib.error.HTTPError as error:
                    return error.code, error.read().decode()

            def group(name):
                return api('/proxies/' + urllib.parse.quote(name, safe=''))[1]

            def start():
                return subprocess.Popen([H['MIHOMO'], '-d', directory, '-f', str(config)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            core = start()
            H['until'](lambda: api('/version')[0] == 200)
            H['until'](lambda: group('GitHub-自动')['now'] == 'GitHub-机场名称1')
            H['until'](lambda: group('机场名称3优先')['now'] == '机场名称3地区优先')
            chosen = group('规则更新')['now']
            with LOCK:
                fetch_count = len(FETCHES)
            status, payload = api('/providers/rules/dev_download_domain', 'PUT')
            with LOCK:
                update_fetches = FETCHES[fetch_count:]
            if legacy:
                assert status >= 400 and chosen == '机场名称3地区优先', (status, chosen, payload)
                assert ('3', False) in update_fetches, update_fetches
                return {'legacy_google_probe': True, 'update_status': status, 'selected': chosen,
                        'confirmed': 'Google健康/GitHub故障时，通用更新链不能自动使用健康GitHub机场'}
            assert status == 204, (status, chosen, payload)
            assert chosen == 'GitHub-机场名称1', chosen
            H['until'](lambda: api('/providers/rules')[1]['providers']['dev_download_domain']['ruleCount'] == 1)
            with LOCK:
                assert ('1', True) in update_fetches, update_fetches
                BAD_GITHUB.update(('1', '4'))
            H['until'](lambda: group('规则更新')['now'] == 'DIRECT')
            with LOCK:
                fetch_count = len(FETCHES)
            assert api('/providers/rules/dev_download_domain', 'PUT')[0] == 204
            with LOCK:
                assert ('DIRECT', True) in FETCHES[fetch_count:], FETCHES[fetch_count:]
                OFFLINE = True
            stop_core(core)
            core = start()
            H['until'](lambda: api('/version')[0] == 200)
            H['until'](lambda: api('/providers/rules')[1]['providers']['dev_download_domain']['ruleCount'] == 1)
            # 规则缓存恢复与叶组就绪是不同阶段；只把实际新增 GET 的站点503作为成功证据。
            offline_attempts = []

            def observed_offline_update():
                with LOCK:
                    fetch_count = len(FETCHES)
                status, payload = api('/providers/rules/dev_download_domain', 'PUT')
                with LOCK:
                    update_fetches = FETCHES[fetch_count:]
                attempt = {'status': status, 'error': payload, 'fetches': update_fetches}
                offline_attempts.append(attempt)
                assert api('/providers/rules')[1]['providers']['dev_download_domain']['ruleCount'] == 1, attempt
                message = json.loads(payload).get('message') if isinstance(payload, str) else None
                if (status == 503 and message == '503 Fixture' and update_fetches
                        and all(label in {'1', '3', '4', 'DIRECT'} and not success
                                for label, success in update_fetches)):
                    return attempt
                return False

            try:
                offline_update = H['until'](observed_offline_update)
            except AssertionError as error:
                raise AssertionError({'stage': 'offline restart', 'attempts': offline_attempts}) from error
            return {'passed': True, 'checks': ['规则更新使用健康的GitHub机场而非Google可达但GitHub失败的机场',
                '所有代理GitHub路径失败时仍可使用既有DIRECT规则更新兜底',
                '更新缓存跨重启保留；上游失败不会清空已载入规则'],
                'offline_update': offline_update, 'offline_update_attempts': len(offline_attempts)}
        finally:
            if core is not None:
                stop_core(core)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('规则更新测试中止')))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-google', action='store_true', help='对照旧Google更新链，预期复现更新失败')
    args = parser.parse_args()
    print(json.dumps(run(args.legacy_google), ensure_ascii=False, indent=2))
