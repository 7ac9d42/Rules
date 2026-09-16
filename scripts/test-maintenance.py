#!/usr/bin/env python3
"""启动就绪、控制器错误分类、Smart 规避检查及 UDP 测试子进程回收。"""

import concurrent.futures
import contextlib
import copy
import http.server
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parent.parent


class Controller(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        status, body, delay = self.server.responses[self.path]
        if hasattr(self.server, 'release'):
            self.server.requested.set()
            self.server.release.wait(timeout=10)
        time.sleep(delay)
        try:
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())
        except OSError:
            pass  # 超时用例的客户端已退出。

    def log_message(self, *_):
        pass


class MaintenanceTests(unittest.TestCase):
    def test_readiness_waits_for_registration(self):
        fixture = runpy.run_path(str(ROOT / 'scripts/proxy-fixture.py'))
        # 控制器已监听，但尚未注册 provider/组时，核心会返回 null 或空映射。
        stages = iter([
            (None, None, None),
            ({}, {}, {}),
            ({'nodes': {'proxies': []}}, {'rules': {'ruleCount': 0}}, {'pool': {'all': ['REJECT']}}),
            ({'nodes': {'proxies': [{'name': 'node'}]}}, {'rules': {'ruleCount': 0}}, {'pool': {'all': ['node']}}),
        ])
        current = None

        def api(path):
            nonlocal current
            if path == '/providers/proxies':
                current = next(stages)
                return {'providers': current[0]}
            if path == '/providers/rules':
                return {'providers': current[1]}
            self.assertEqual(path, '/proxies')
            return {'proxies': current[2]}

        actual = fixture['wait_ready'](api, ['pool'], ['nodes'], ['rules'])
        self.assertEqual(actual['pool']['all'], ['node'])

    def test_readiness_waits_for_subscription(self):
        # 确定性重现：/version 和策略组已开放，HTTP 订阅仍在下载。
        fixture = runpy.run_path(str(ROOT / 'scripts/proxy-fixture.py'))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Controller)
        server.release, server.requested = threading.Event(), threading.Event()
        server.responses = {'/subscription': (200, {'proxies': [
            {'name': 'loaded-node', 'type': 'socks5', 'server': '127.0.0.1', 'port': 9}]}, 0)}
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix='mihomo-readiness-') as directory, contextlib.ExitStack() as cleanup:
                control = fixture['free_port']()
                config = Path(directory) / 'config.json'
                config.write_text(json.dumps({
                    'external-controller': f'127.0.0.1:{control}', 'log-level': 'silent',
                    'dns': {'enable': False}, 'tun': {'enable': False},
                    'proxy-providers': {'delayed': {'type': 'http', 'path': './nodes.json', 'proxy': 'DIRECT',
                        'url': f'http://127.0.0.1:{server.server_address[1]}/subscription',
                        'health-check': {'enable': False}}},
                    'proxy-groups': [
                        {'name': 'pool', 'type': 'select', 'use': ['delayed'], 'empty-fallback': 'REJECT'},
                        {'name': 'empty-pool', 'type': 'select', 'use': ['delayed'],
                         'filter': '^absent$', 'empty-fallback': 'REJECT'}],
                    'rules': ['MATCH,REJECT']}))
                core = subprocess.Popen([fixture['MIHOMO'], '-d', directory, '-f', str(config)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                cleanup.callback(fixture['stop_core'], core)
                cleanup.callback(server.release.set)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def api(path):
                    with opener.open(f'http://127.0.0.1:{control}{path}', timeout=1) as response:
                        return json.load(response)

                fixture['until'](lambda: api('/version'))
                self.assertTrue(server.requested.wait(timeout=5))
                self.assertEqual(api('/proxies')['proxies']['pool']['all'], ['REJECT'])
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
                    ready = worker.submit(fixture['wait_ready'], api, ['pool', 'empty-pool'], ['delayed'], seconds=5)
                    try:
                        with self.assertRaises(concurrent.futures.TimeoutError):
                            ready.result(timeout=.3)
                    finally:
                        server.release.set()
                    actual = ready.result(timeout=6)
                self.assertEqual(actual['pool']['all'], ['loaded-node'])
                # 等待初始化不能变成“等到过滤断言正确”；真正的空池仍需交给调用者检查。
                self.assertEqual(actual['empty-pool']['all'], ['REJECT'])
                with self.assertRaisesRegex(AssertionError, '策略组:missing'):
                    fixture['wait_ready'](api, ['missing'], seconds=.2)
        finally:
            server.release.set()
            server.shutdown()
            server.server_close()

    def test_unresponsive_core_is_killed_and_reaped(self):
        fixture = runpy.run_path(str(ROOT / 'scripts/proxy-fixture.py'))
        child = subprocess.Popen([sys.executable, '-c',
            'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
            'print("ready", flush=True); time.sleep(60)'], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            fixture['stop_core'](child)
            self.assertEqual(child.returncode, -signal.SIGKILL)
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()

    def test_controller_contract(self):
        responses = {'/version': (200, {'version': 'alpha-smart-g4bc3d49'}, 0),
                     '/configs': (200, {'mode': 'rule'}, 0),
                     '/proxies': (200, {'proxies': {'日本': {'type': 'URLTest'}}}, 0)}
        cases = [('Smart 内核保留原组类型', {}, 0),
                 ('非规则模式', {'/configs': (200, {'mode': 'global'}, 0)}, 1),
                 ('Smart 算法开关关闭仍拒绝', {'/proxies': (200, {'proxies': {'日本': {
                     'type': 'Smart', 'use-asn': False, 'uselightgbm': False, 'collectdata': False}}}, 0)}, 1),
                 ('鉴权失败', {'/version': (401, {}, 0)}, 2),
                 ('无效 JSON', {'/proxies': (200, b'not-json', 0)}, 2),
                 ('空代理列表', {'/proxies': (200, {'proxies': {}}, 0)}, 2),
                 ('控制器超时', {'/version': (200, {}, .5)}, 2)]
        for value in (None, 1, [], {}, '', '   '):
            for path, body in (
                ('/version', {'version': value}),
                ('/configs', {'mode': value}),
                ('/proxies', {'proxies': {'日本': {'type': value}}}),
            ):
                cases.append((f'{path} 异常字段 {value!r}', {path: (200, body, 0)}, 2))
        for body in ({'proxies': {'日本': None}}, {'proxies': {'日本': {}}}, []):
            cases.append(('代理响应结构异常', {'/proxies': (200, body, 0)}, 2))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Controller)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
        try:
            for label, changed, expected in cases:
                with self.subTest(case=label):
                    server.responses = {**copy.deepcopy(responses), **changed}
                    result = subprocess.run([
                        sys.executable, str(ROOT / 'scripts/check-proxy-route.py'), 'check-smart',
                        '--controller', f'http://127.0.0.1:{server.server_address[1]}',
                        '--timeout', '.2', '--json',
                    ], capture_output=True, text=True, timeout=5,
                        env={**os.environ, 'MIHOMO_SECRET': '', 'NO_PROXY': '*'})
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    if expected == 2:
                        self.assertIn('ERROR', result.stderr)
                        self.assertEqual(result.stdout, '')
                    else:
                        record = json.loads(result.stdout)
                        self.assertEqual(record['ok'], expected == 0)
                        self.assertEqual(record['smart_groups'], ['日本'] if 'Smart 算法' in label else [])
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipUnless(Path('/proc/self/task').is_dir(), '进程回收检查需要 Linux /proc')
    def test_udp_sigterm_reaps_core(self):
        # 只向测试父进程发 SIGTERM；依靠它的 finally 回收内核，不能用进程组杀死冒充通过。
        with tempfile.TemporaryFile(mode='w+') as log:
            parent = subprocess.Popen([sys.executable, str(ROOT / 'scripts/test-rematch-udp.py'),
                                       '--config', str(ROOT / 'configfull_new.yaml')],
                                      cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            child, runtime = None, None
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and parent.poll() is None:
                    children = Path(f'/proc/{parent.pid}/task/{parent.pid}/children').read_text().split()
                    for pid in children:
                        try:
                            args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
                            if '-d' not in args or '-f' not in args or '-t' in args:
                                continue
                            config = Path(args[args.index('-f') + 1])
                            endpoint = json.loads(config.read_text())['external-controller']
                            host, port = endpoint.rsplit(':', 1)
                            with socket.create_connection((host, int(port)), timeout=.1):
                                child, runtime = int(pid), config.parent
                        except (OSError, ValueError):
                            continue
                    if child is not None:
                        break
                    time.sleep(.05)
                log.seek(0)
                self.assertIsNotNone(child, log.read())
                parent.terminate()
                parent.wait(timeout=10)
                self.assertFalse(Path(f'/proc/{child}').exists(), f'遗留测试内核 PID {child}')
                self.assertFalse(runtime.exists(), f'临时目录未清理：{runtime}')
                self.assertNotEqual(parent.returncode, -signal.SIGTERM)
                self.assertNotEqual(parent.returncode, 0)
            finally:
                # 失败时也只清理本用例创建的独立进程组。
                try:
                    os.killpg(parent.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                parent.wait(timeout=5)
                if runtime is not None and runtime.exists():
                    shutil.rmtree(runtime)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    unittest.main()
