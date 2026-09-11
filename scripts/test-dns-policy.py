#!/usr/bin/env python3
"""运行真实 DNS 策略与规则顺序；仅使用回环 DNS/HTTP，不启用 TUN 或真实订阅。"""

import copy
import http.server
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
CONFIG = os.environ.get("MIHOMO_DESIGN_CONFIG", str(ROOT / "configfull_new.yaml"))
MIHOMO = os.environ.get("MIHOMO_BIN", "mihomo")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def until(check, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except OSError:
            pass
        time.sleep(.1)
    raise AssertionError("等待本机 DNS 状态超时")


def skip_name(data, offset):
    while data[offset]:
        if data[offset] & 0xC0 == 0xC0:
            return offset + 2
        offset += data[offset] + 1
    return offset + 1


def read_exact(sock, size):
    result = b""
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise OSError("本机 TCP DNS 响应提前结束")
        result += chunk
    return result


class DNSServer(socketserver.ThreadingUDPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), DNSHandler)
        self.lock = threading.Lock()
        self.queries = {}
        self.answers = {}

    def count(self, host, qtype=1):
        with self.lock:
            return self.queries.get((host, qtype), 0)


class DNSHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        offset, labels = 12, []
        while data[offset]:
            size = data[offset]
            labels.append(data[offset + 1:offset + size + 1].decode())
            offset += size + 1
        host = ".".join(labels).lower()
        end = offset + 1
        qtype = struct.unpack_from("!H", data, end)[0]
        with self.server.lock:
            key = (host, qtype)
            self.server.queries[key] = self.server.queries.get(key, 0) + 1
            addresses, ttl = self.server.answers.get(host, ("127.0.0.1", 60))
        if isinstance(addresses, str):
            addresses = [addresses]
        answer = b""
        answer_count = 0
        if qtype in (1, 28):
            for address in addresses if qtype == 1 else ["2001:db8::1"]:
                value = socket.inet_aton(address) if qtype == 1 else socket.inet_pton(socket.AF_INET6, address)
                answer += b"\xc0\x0c" + struct.pack("!HHIH", qtype, 1, ttl, len(value)) + value
                answer_count += 1
        response = data[:2] + struct.pack("!HHHHH", 0x8180, 1, answer_count, 0, 0)
        sock.sendto(response + data[12:end + 4] + answer, self.client_address)


class Origin(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with self.server.lock:
            self.server.requests += 1
        body = b"DNS fixture"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def stop_core(core):
    core.terminate()
    try:
        core.wait(timeout=5)
    except subprocess.TimeoutExpired:
        core.kill()
        core.wait(timeout=5)


def main():
    source = json.loads(subprocess.check_output(["ruby", "-ryaml", "-rjson", "-e",
        "puts JSON.generate(YAML.load_file(ARGV[0], aliases: true))", CONFIG], timeout=10))
    assert source["ipv6"] is False and source["dns"]["ipv6"] is False
    assert source["profile"]["store-fake-ip"] is True
    core, servers, running_servers, checks = None, [], [], []
    with tempfile.TemporaryDirectory(prefix="mihomo-dns-policy-") as directory:
        runtime = Path(directory)
        try:
            for _ in range(3):
                servers.append(DNSServer())
            domestic, foreign, direct = servers
            origin = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Origin)
            origin.lock, origin.requests = threading.Lock(), 0
            servers.append(origin)
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                running_servers.append(server)

            addresses = [f"udp://127.0.0.1:{server.server_address[1]}#DIRECT" for server in servers[:3]]
            dns_port, mixed, control = [free_port() for _ in range(3)]
            dns = copy.deepcopy(source["dns"])
            dns.update({"listen": f"127.0.0.1:{dns_port}", "default-nameserver": [addresses[0]],
                "proxy-server-nameserver": [addresses[0]], "nameserver": [addresses[1]],
                "direct-nameserver": [addresses[2]]})
            # 保留策略键及顺序；只把公网 DoH 换为可计数的回环 UDP 上游。
            dns["nameserver-policy"] = {key: value if isinstance(value, str) and value.startswith("rcode://")
                                        else [addresses[0]] for key, value in dns["nameserver-policy"].items()}
            providers = {name: {"type": "inline", "behavior": value["behavior"], "payload": []}
                         for name, value in source["rule-providers"].items()}
            payloads = {
                "cn_domain": ["+.cn.fixture.test"],
                "private_domain": ["+.lan", "+.plex.direct", "localhost"],
                "stun_domain": ["stun.external.fixture.test"],
                "fakeip_filter_domain": ["legacy.external.fixture.test", "direct.external.fixture.test"],
                "banAd_core_domain": ["ads.cn.fixture.test"],
                "banAd_pcdn_domain": ["pcdn.cn.fixture.test"],
                "banAd_low_domain": ["allowed.cn.fixture.test"],
                "direct_domain": ["allowed.cn.fixture.test", "direct.external.fixture.test"],
            }
            for name, payload in payloads.items():
                providers[name]["payload"] = payload
            # 所有业务入口保留名称但用 DIRECT 占位；隐私拦截保留原候选和手动开关。
            groups = [{"name": group["name"], "type": "select", "proxies": ["DIRECT"]}
                      for group in source["proxy-groups"] if group["name"] != "隐私拦截"]
            groups.append(copy.deepcopy(next(group for group in source["proxy-groups"]
                                             if group["name"] == "隐私拦截")))
            config = runtime / "config.json"
            config.write_text(json.dumps({"external-controller": f"127.0.0.1:{control}", "mixed-port": mixed,
                "bind-address": "127.0.0.1", "allow-lan": False, "log-level": "error", "ipv6": source["ipv6"],
                "profile": {"store-selected": False, "store-fake-ip": source["profile"]["store-fake-ip"]},
                "tun": {"enable": False}, "sniffer": {"enable": False}, "dns": dns,
                "hosts": {"hosts.lan": "127.0.0.1", "hosts.external.fixture.test": "127.0.0.1"},
                "rules": source["rules"], "sub-rules": source.get("sub-rules", {}),
                "rule-providers": providers, "proxy-groups": groups}))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, body=None):
                request = urllib.request.Request(f"http://127.0.0.1:{control}{path}",
                    data=json.dumps(body).encode() if body is not None else None,
                    method="PUT" if body is not None else "GET", headers={"Content-Type": "application/json"})
                with opener.open(request, timeout=1) as response:
                    return json.load(response) if response.status != 204 else None

            def start():
                process = subprocess.Popen([MIHOMO, "-d", directory, "-f", str(config)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return process

            def query(host, qtype=1, tcp=False):
                packet = struct.pack("!HHHHHH", 1234, 0x0100, 1, 0, 0, 0)
                packet += b"".join(bytes([len(label)]) + label.encode() for label in host.split("."))
                packet += b"\0" + struct.pack("!HH", qtype, 1)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
                    sock.settimeout(2)
                    if tcp:
                        sock.connect(("127.0.0.1", dns_port))
                        sock.sendall(struct.pack("!H", len(packet)) + packet)
                        response = read_exact(sock, struct.unpack("!H", read_exact(sock, 2))[0])
                    else:
                        sock.sendto(packet, ("127.0.0.1", dns_port))
                        response = sock.recv(4096)
                rcode = struct.unpack_from("!H", response, 2)[0] & 15
                count = struct.unpack_from("!H", response, 6)[0]
                offset, ips = skip_name(response, 12) + 4, []
                for _ in range(count):
                    offset = skip_name(response, offset)
                    kind, _, _, size = struct.unpack_from("!HHIH", response, offset)
                    offset += 10
                    if kind in (1, 28):
                        family = socket.AF_INET if kind == 1 else socket.AF_INET6
                        ips.append(socket.inet_ntop(family, response[offset:offset + size]))
                    offset += size
                return rcode, ips

            def counts(host, qtype=1):
                return [server.count(host, qtype) for server in servers[:3]]

            def fake(address):
                return ipaddress.ip_address(address) in ipaddress.ip_network(source["dns"]["fake-ip-range"])

            def request(host):
                result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--noproxy", "",
                    "--proxy", f"socks5h://127.0.0.1:{mixed}", "--max-time", "2",
                    f"http://{host}:{origin.server_address[1]}/"], capture_output=True, timeout=3)
                return result.returncode == 0 and result.stdout == b"DNS fixture"

            core = start()
            until(lambda: api("/version"))
            for host, want_fake, want_counts, tcp in [
                    ("ordinary.cn.fixture.test", False, [1, 0, 0], False),
                    ("tcp.cn.fixture.test", False, [1, 0, 0], True),
                    ("ordinary.external.fixture.test", True, [0, 0, 0], False),
                    ("stun.external.fixture.test", False, [0, 1, 0], False),
                    ("legacy.external.fixture.test", False, [0, 1, 0], False)]:
                rcode, ips = query(host, tcp=tcp)
                assert rcode == 0 and len(ips) == 1 and fake(ips[0]) == want_fake, host
                assert counts(host) == want_counts, (host, counts(host))
            checks.append("国内Real-IP、海外Fake-IP、STUN/专属过滤与TCP/UDP监听")

            for host, expected in (
                    ("region1.v2.argotunnel.com", ["198.41.192.167", "198.41.192.67"]),
                    ("region2.v2.argotunnel.com", ["198.41.200.13", "198.41.200.193"])):
                with domestic.lock:
                    domestic.answers[host] = (expected, 60)
                rcode, ips = query(host)
                assert rcode == 0 and sorted(ips) == sorted(expected), (host, ips)
                assert counts(host) == [1, 0, 0], (host, counts(host))
            for host, qtype in (("_v2-origintunneld._tcp.argotunnel.com", 33),
                                ("cfd-features.argotunnel.com", 16)):
                assert query(host, qtype=qtype) == (0, []), host
                assert counts(host, qtype) == [1, 0, 0], (host, counts(host, qtype))
            host = "other.argotunnel.com"
            rcode, ips = query(host)
            assert rcode == 0 and len(ips) == 1 and fake(ips[0]), (host, ips)
            assert counts(host) == [0, 0, 0], (host, counts(host))
            checks.append("Tunnel两区域保留多地址，发现SRV/TXT走国内解析器，Real-IP例外限于两区域")

            for host in ("v6.cn.fixture.test", "v6.external.fixture.test",
                         "region1.v2.argotunnel.com", "region2.v2.argotunnel.com"):
                assert query(host, qtype=28) == (0, []), host
                assert counts(host, 28) == [0, 0, 0], host
            checks.append("关闭IPv6时AAAA返回空答案，不查询上游")

            assert query("router.lan") == (3, [])
            assert counts("router.lan") == [0, 0, 0]
            assert query("public.plex.direct") == (0, ["127.0.0.1"])
            assert counts("public.plex.direct") == [1, 0, 0]
            checks.append("私有域NXDOMAIN、plex.direct优先于私有域策略")

            for host in ("hosts.lan", "hosts.external.fixture.test", "localhost"):
                rcode, ips = query(host)
                assert rcode == 0 and "127.0.0.1" in ips and not any(fake(ip) for ip in ips), host
                assert counts(host) == [0, 0, 0], host
            checks.append("配置hosts与系统localhost优先，不误发Fake-IP或NXDOMAIN")

            assert request("direct-policy.cn.fixture.test")
            assert counts("direct-policy.cn.fixture.test") == [1, 0, 0]
            assert request("direct.external.fixture.test")
            assert counts("direct.external.fixture.test") == [0, 0, 1]
            # 未命中域名规则时，原cn_ip先用默认解析器判断IP；DIRECT占位再用直连解析器拨号。
            host = "unmatched.external.fixture.test"
            assert request(host)
            assert counts(host) == [0, 1, 1], ("before-restart/IP-fallback", host, counts(host))
            checks.append("DIRECT遵守nameserver-policy，IP兜底预解析与直连拨号分别使用对应解析器")

            for host in ("ads.cn.fixture.test", "pcdn.cn.fixture.test"):
                assert query(host) == (0, ["127.0.0.1"]), host
                before = origin.requests
                assert not request(host) and origin.requests == before, host
            assert query("allowed.cn.fixture.test") == (0, ["127.0.0.1"])
            assert request("allowed.cn.fixture.test")
            api("/proxies/" + urllib.parse.quote("隐私拦截"), {"name": "DIRECT"})
            assert all(request(host) for host in ("ads.cn.fixture.test", "pcdn.cn.fixture.test"))
            checks.append("广告沿用Real-IP但请求被拦截，国内白名单及手动放行生效")

            host = "cache.cn.fixture.test"
            assert query(host) == query(host) == (0, ["127.0.0.1"])
            assert counts(host) == [1, 0, 0]
            checks.append("重复Real-IP查询使用运行期DNS缓存")

            host = "refresh.cn.fixture.test"
            with domestic.lock:
                domestic.answers[host] = ("127.0.0.1", 1)
            assert query(host) == (0, ["127.0.0.1"])
            with domestic.lock:
                domestic.answers[host] = ("127.0.0.2", 60)
            time.sleep(1.1)
            first = query(host)
            assert first in ((0, ["127.0.0.1"]), (0, ["127.0.0.2"]))
            until(lambda: query(host) == (0, ["127.0.0.2"]))
            checks.append("LRU过期项可返回旧值，但后台刷新最终取得新地址")

            host = "persist.external.fixture.test"
            rcode, ips = query(host)
            assert rcode == 0 and len(ips) == 1 and fake(ips[0])
            saved = ips[0]
            stop_core(core)
            core = start()
            until(lambda: api("/version"))
            # 先分配另一个域名，再直接使用旧Fake-IP，避免重新查询掩盖映射未持久化。
            assert query("new-after-restart.external.fixture.test")[1] != [saved]
            assert request(saved)
            actual_counts = counts(host)
            # 与重启前的未匹配域相同：cn_ip默认预解析一次，DIRECT出站再解析一次。
            assert actual_counts == [0, 1, 1], ("restart/old-Fake-IP", host, saved, actual_counts)
            assert query(host) == (0, [saved])
            # 普通DNS答案不属于store-fake-ip的持久化承诺，应重新查询上游。
            assert query("cache.cn.fixture.test") == (0, ["127.0.0.1"])
            assert counts("cache.cn.fixture.test") == [2, 0, 0]
            checks.append("重启保存Fake-IP正反向映射，普通DNS缓存按新进程重建")
            print(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False, indent=2))
        finally:
            if core is not None and core.poll() is None:
                stop_core(core)
            for server in servers:
                if server in running_servers:
                    server.shutdown()
                server.server_close()


def interrupted(signum, frame):
    raise InterruptedError("DNS本机测试被中止")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    main()
