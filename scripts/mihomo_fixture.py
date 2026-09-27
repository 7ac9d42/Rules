"""配置回归的回环夹具；无订阅凭据，不接触设备运行目录。"""
import base64
import concurrent.futures
import copy
from dataclasses import dataclass, field
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import shutil
import socket
import socketserver
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def load(path):
    return json.loads(subprocess.check_output(['ruby', '-ryaml', '-rjson', '-e',
        'puts JSON.generate(YAML.load(STDIN.read, aliases: true))'], input=Path(path).read_bytes(), timeout=10))


def until(check, seconds=18):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except OSError as error:
            last = error
        time.sleep(.1)
    raise AssertionError(f'等待运行状态超时: {last}')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


@dataclass
class Node:
    label: str
    statuses: dict = field(default_factory=dict)
    delays: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


class HTTP(socketserver.StreamRequestHandler):
    def headers(self):
        result = {}
        while True:
            line = self.rfile.readline()
            if line in (b'\r\n', b'\n', b''):
                return result
            key, value = line.decode().split(':', 1)
            result[key.lower()] = value.strip()

    def handle(self):
        self.connection.settimeout(3)
        try:
            line = self.rfile.readline().decode().strip()
            headers = self.headers()
            auth = headers.get('proxy-authorization', '')
            username = base64.b64decode(auth[6:]).decode().split(':', 1)[0] if auth.startswith('Basic ') else ''
            node = self.server.nodes[username]
            if line.startswith('CONNECT '):
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                line = self.rfile.readline().decode().strip()
                self.headers()
            method, target, _ = line.split(' ', 2)
            status, body = 200, node.label.encode()
            if method == 'HEAD':
                path = urllib.parse.urlsplit(target).path
                with self.server.lock:
                    node.counts[path] = node.counts.get(path, 0) + 1
                    status = node.statuses.get(path, self.server.expected[path])
                    delay = node.delays.get(path, .01 if 'fast' in node.label else .12)
                time.sleep(delay)
                body = b''
            self.wfile.write(f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
            self.wfile.flush()
        except (OSError, ValueError, KeyError, UnicodeError):
            return


class DNSHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        offset, labels = 12, []
        while data[offset]:
            size = data[offset]
            labels.append(data[offset + 1:offset + size + 1].decode())
            offset += size + 1
        host = '.'.join(labels)
        qtype = struct.unpack_from('!H', data, offset + 1)[0]
        self.server.queries.add((host, qtype))
        ips = self.server.answers.get(host, [self.server.answer]) if qtype == 1 else []
        answers = b''.join(b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton(ip) for ip in ips)
        sock.sendto(data[:2] + struct.pack('!HHHHH', 0x8180, 1, len(ips), 0, 0)
                    + data[12:offset + 5] + answers, self.client_address)

def skip_name(data, offset):
    while data[offset]:
        if data[offset] & 0xc0 == 0xc0:
            return offset + 2
        offset += data[offset] + 1
    return offset + 1

def query(port, host, qtype=1):
    packet = struct.pack('!HHHHHH', 1234, 0x0100, 1, 0, 0, 0)
    packet += b''.join(bytes([len(label)]) + label.encode() for label in host.split('.'))
    packet += b'\0' + struct.pack('!HH', qtype, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.sendto(packet, ('127.0.0.1', port))
        response = sock.recv(4096)
    assert response[:2] == packet[:2]
    rcode = struct.unpack_from('!H', response, 2)[0] & 15
    count = struct.unpack_from('!H', response, 6)[0]
    offset, ips = skip_name(response, 12) + 4, []
    for _ in range(count):
        offset = skip_name(response, offset)
        kind, _, _, size = struct.unpack_from('!HHIH', response, offset)
        offset += 10
        if kind == 1:
            ips.append(socket.inet_ntoa(response[offset:offset + size]))
        offset += size
    return rcode, ips

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

def udp_request(mixed, host, udp_sockets, target_port=12345):
    # 新 SOCKS 关联不清除旧 UDP NAT；整轮持有源端口，避免复用后继承旧出口。
    udp = udp_sockets.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    udp.bind(('127.0.0.1', 0))
    with socket.create_connection(('127.0.0.1', mixed), timeout=3) as control:
        control.sendall(b'\x05\x01\x00')
        assert read(control, 2) == b'\x05\x00'
        control.sendall(b'\x05\x03\x00\x01' + b'\x00' * 6)
        assert read(control, 3) == b'\x05\x00\x00'
        target = address(control)
        try:
            ip = ipaddress.ip_address(host)
            destination = bytes([1 if ip.version == 4 else 4]) + ip.packed
        except ValueError:
            destination = b'\x03' + bytes([len(host)]) + host.encode()
        packet = b'\x00\x00\x00' + destination + struct.pack('!H', target_port) + b'fixture'
        udp.settimeout(3)
        udp.sendto(packet, target)
        response = udp.recv(4096)
        kind = response[3]
        size = 10 if kind == 1 else 7 + response[4] if kind == 3 else 22
        return response[size:].decode()

class Runtime:
    def __init__(self, directory, mihomo, expected=None):
        self.directory, self.mihomo = Path(directory), mihomo
        self.controller, self.mixed = free_port(), free_port()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.core, self.servers = None, []
        self.http = self.server(HTTP)
        self.http.nodes, self.http.expected, self.http.lock = {}, expected or {}, threading.Lock()
        self.file = self.directory / 'config.json'

    def server(self, handler, cls=Server):
        server = cls(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
        self.servers.append(server)
        return server

    def proxy(self, name, label=None):
        self.http.nodes[name] = Node(label or name)
        return dict(name=name, type='http', server='127.0.0.1', port=self.http.server_address[1],
                    username=name, password='fixture')

    def udp_proxy(self, name, label):
        relay = self.server(Echo, Relay)
        relay.label = label
        control = self.server(Control)
        control.relay = relay
        return dict(name=name, type='socks5', server='127.0.0.1', port=control.server_address[1], udp=True)

    def api(self, path, method='GET', body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.controller}' + path, method=method,
            data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=20) as response:
            data = response.read()
            return json.loads(data) if data else None

    def group(self, name):
        return self.api('/proxies/' + urllib.parse.quote(name, safe=''))

    def select(self, name, choice):
        self.api('/proxies/' + urllib.parse.quote(name, safe=''), 'PUT', {'name': choice})

    def probe(self, name, url, expected, timeout=5000):
        query = urllib.parse.urlencode(dict(url=url, expected=expected, timeout=timeout))
        path = '/proxies/' + urllib.parse.quote(name, safe='')
        endpoint = '/delay?'
        if name.startswith('[机场名称'):
            airport = name.split(']')[0][-1]
            path = '/providers/proxies/Airport_0' + airport + '/' + urllib.parse.quote(name, safe='')
            endpoint = '/healthcheck?'
        try:
            self.api(path + endpoint + query)
            # 状态码错误时 API 仍可能返回延迟，选路使用 URL 专属健康状态。
            return self.api(path)['extra'][url]['alive']
        except urllib.error.HTTPError as error:
            assert error.code in (503, 504), error
            return False

    def base(self, source):
        return {'mixed-port': self.mixed, 'external-controller': f'127.0.0.1:{self.controller}',
                'allow-lan': False, 'mode': 'rule', 'log-level': 'error', 'ipv6': False,
                'unified-delay': source['unified-delay'], 'tcp-concurrent': source['tcp-concurrent'],
                'profile': {'store-selected': True, 'store-fake-ip': True},
                'proxies': copy.deepcopy(source['proxies']), 'sub-rules': copy.deepcopy(source['sub-rules']),
                'rules': source['rules'], 'rule-providers': {
                    n: dict(type='inline', behavior=p['behavior'], payload=p.get('payload', []))
                    for n, p in source['rule-providers'].items()}}

    def reload(self, config):
        self.file.write_text(json.dumps(config, ensure_ascii=False))
        self.api('/configs?force=true', 'PUT', {'path': str(self.file)})

    def start(self, config):
        self.file.write_text(json.dumps(config, ensure_ascii=False))
        with (self.directory / 'core.log').open('a') as log:
            self.core = subprocess.Popen([self.mihomo, '-d', str(self.directory), '-f', str(self.file)], stdout=log, stderr=log)
        def ready():
            assert self.core.poll() is None, '内核提前退出'
            return self.api('/version')
        until(ready)

    def stop(self):
        if self.core:
            self.core.terminate()
            try:
                self.core.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.core.kill()
                self.core.wait(timeout=5)
            self.core = None

    def request(self, host, port=80):
        connection = http.client.HTTPConnection('127.0.0.1', self.mixed, timeout=5)
        try:
            authority = f'[{host}]' if ':' in host else host
            connection.request('GET', f'http://{authority}:{port}/resource')
            response = connection.getresponse()
            assert response.status == 200, (host, response.status)
            return response.read().decode()
        finally:
            connection.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind and (self.directory / 'core.log').exists():
            print((self.directory / 'core.log').read_text()[-4000:])
        self.stop()
        for server in self.servers:
            server.shutdown()
            server.server_close()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare_rules(source, rules_dir, runtime):
    manifest = json.loads((rules_dir / 'manifest.json').read_text())
    entries = {item['name']: item for item in manifest['providers']}
    prepared = {}
    for name, provider in source['rule-providers'].items():
        if provider['type'] == 'inline':
            prepared[name] = copy.deepcopy(provider)
            continue
        item = entries.get(name, {})
        assert item.get('url') == provider['url'], f'{name}: 快照 URL 与配置不一致'
        assert item.get('status') in {'downloaded', 'workspace'}, f'{name}: 缺少原始规则'
        filename = item['file']
        assert Path(filename).name == filename, f'{name}: 快照 file 必须是文件名'
        path = rules_dir / filename
        assert digest(path) == item['sha256'], f'{name}: 规则 SHA256 不符'
        prefix = 'https://raw.githubusercontent.com/7ac9d42/Rules/refs/heads/main/rules/'
        if provider['url'].startswith(prefix):
            current = ROOT / 'rules' / urllib.parse.unquote(provider['url'][len(prefix):])
            assert digest(current) == item['sha256'], f'{name}: 工作区规则已变化，请重建快照'
        target = runtime / f'{name}.{provider["format"]}'
        shutil.copyfile(path, target)
        prepared[name] = {'type': 'file', 'behavior': provider['behavior'],
                          'format': provider['format'], 'path': str(target)}
    return prepared

def snapshot(sources, directory):
    """一次下载四配置所需并集；已有快照只校验，不悄悄补齐或替换。"""
    providers = {}
    for source in sources:
        for name, provider in source['rule-providers'].items():
            if provider['type'] == 'http':
                assert name not in providers or providers[name]['url'] == provider['url'], name
                providers[name] = provider
    if directory.exists():
        assert (directory / 'manifest.json').is_file(), '快照不完整，请删除该临时目录后重试'
        return
    directory.mkdir(parents=True)
    prefix = 'https://raw.githubusercontent.com/7ac9d42/Rules/refs/heads/main/rules/'
    def collect(item):
        name, provider = item
        url = provider['url']
        target = directory / f'{name}.{provider["format"]}'
        if url.startswith(prefix):
            shutil.copyfile(ROOT / 'rules' / urllib.parse.unquote(url[len(prefix):]), target)
            status = 'workspace'
        else:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '1',
                            '--max-time', '30', '--output', str(target), url], check=True, timeout=70)
            status = 'downloaded'
        assert target.stat().st_size > 0, (name, '规则文件为空')
        return dict(name=name, url=url, file=target.name, sha256=digest(target), status=status)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    try:
        entries = list(executor.map(collect, providers.items()))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    (directory / 'manifest.json').write_text(json.dumps({'providers': entries}, indent=2) + '\n')
