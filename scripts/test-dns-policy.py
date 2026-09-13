#!/usr/bin/env python3
"""用回环 DNS 验证 Fake-IP 例外与解析器选择；规则匹配使用实际配置。"""

import copy
import ipaddress
import json
from pathlib import Path
import runpy
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading

D = runpy.run_path(str(Path(__file__).with_name('test-config-design.py')))
H = D['H']


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


def main():
    source = D['load_source']()
    dns = copy.deepcopy(source['dns'])
    assert source['ipv6'] is False and dns['ipv6'] is False
    assert dns['direct-nameserver-follow-policy'] is True and dns['respect-rules'] is True
    servers, core = [], None
    with tempfile.TemporaryDirectory(prefix='mihomo-dns-policy-') as directory:
        try:
            for address in ('203.0.113.10', '203.0.113.20'):
                server = socketserver.UDPServer(('127.0.0.1', 0), DNSHandler)
                server.answer, server.answers, server.queries = address, {}, set()
                threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
                servers.append(server)
            domestic, foreign = servers
            tunnel = {'region1.v2.argotunnel.com': ['198.41.192.167', '198.41.192.67'],
                      'region2.v2.argotunnel.com': ['198.41.200.13', '198.41.200.193']}
            domestic.answers.update(tunnel)
            local = [f'udp://127.0.0.1:{s.server_address[1]}#DIRECT' for s in servers]
            # 保留策略键和顺序，核对用途后替换解析器地址。
            for key, value in dns['nameserver-policy'].items():
                if isinstance(value, str) and value.startswith('rcode://'):
                    continue
                assert value == dns['direct-nameserver'], (key, value)
                dns['nameserver-policy'][key] = [local[0]]
            port = H['free_port']()
            dns.update({'listen': f'127.0.0.1:{port}', 'default-nameserver': [local[0]],
                        'proxy-server-nameserver': [local[0]], 'direct-nameserver': [local[0]], 'nameserver': [local[1]]})
            providers = {name: {'type': 'inline', 'behavior': p['behavior'], 'payload': []}
                         for name, p in source['rule-providers'].items()}
            for name, values in {'cn_domain': ['+.cn.fixture.test'],
                                 'private_domain': ['+.lan', '+.plex.direct'],
                                 'stun_domain': ['stun.external.fixture.test'],
                                 'fakeip_filter_domain': ['legacy.external.fixture.test']}.items():
                providers[name]['payload'] = values
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'log-level': 'error', 'dns': dns, 'ipv6': source['ipv6'],
                'tun': {'enable': False}, 'profile': {'store-fake-ip': False},
                'rule-providers': providers, 'rules': ['MATCH,DIRECT']}))
            with (Path(directory) / 'core.log').open('w') as log:
                core = subprocess.Popen([H['MIHOMO'], '-d', directory, '-f', str(config)], stdout=log, stderr=subprocess.STDOUT)
            H['until'](lambda: query(port, 'ready.external.fixture.test'))
            for host, expected in [
                ('ordinary.cn.fixture.test', [domestic.answer]),
                ('ordinary.external.fixture.test', 'fake'),
                ('stun.external.fixture.test', [foreign.answer]),
                ('legacy.external.fixture.test', [foreign.answer]),
                ('router.lan', 'nxdomain'), ('public.plex.direct', [domestic.answer]),
                ('other.argotunnel.com', 'fake'), *tunnel.items(),
            ]:
                rcode, ips = query(port, host)
                if expected == 'nxdomain':
                    assert (rcode, ips) == (3, []), (host, rcode, ips)
                elif expected == 'fake':
                    assert rcode == 0 and len(ips) == 1 and ipaddress.ip_address(ips[0]) in ipaddress.ip_network(dns['fake-ip-range']), (host, ips)
                else:
                    assert rcode == 0 and sorted(ips) == sorted(expected), (host, ips)
            for host, qtype in [('_v2-origintunneld._tcp.argotunnel.com', 33), ('cfd-features.argotunnel.com', 16)]:
                assert query(port, host, qtype) == (0, [])
                assert (host, qtype) in domestic.queries and (host, qtype) not in foreign.queries
            print(f'PASS: {D["CONFIG"].name} DNS 国内/海外、STUN、私有域与 Tunnel 发现策略')
        finally:
            if core is not None:
                core.terminate()
                core.wait(timeout=5)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, D['interrupted'])
    main()
