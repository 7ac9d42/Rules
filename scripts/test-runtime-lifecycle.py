#!/usr/bin/env python3
"""全配置回环验收：手选/fake-ip 缓存、订阅失败保留及真实生产周期下的拨号恢复。"""

import argparse
import copy
import http.server
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
import time
import urllib.error
import urllib.parse
import urllib.request


D = runpy.run_path(str(Path(__file__).with_name("test-config-design.py")))
H = D["H"]


class ProxyHandler(D["Handler"]):
    def handle(self):
        if self.server.reject_connect:
            self.connection.settimeout(3)
            try:
                if not self.rfile.readline().startswith(b"CONNECT "):
                    return
                while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                    pass
                self.server.rejections.append(time.monotonic())
                # 代理握手直接失败，尚未进入目标站点 HTTP 响应阶段。
                self.wfile.write(b"HTTP/1.1 502 Proxy unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
        else:
            super().handle()


class SubscriptionHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = self.server.payloads.get(self.path)
        self.send_response(200 if payload is not None else 404)
        self.end_headers()
        self.wfile.write(payload or b"")

    def log_message(self, *_):
        pass


class DNSHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        offset = 12
        while data[offset]:
            offset += data[offset] + 1
        end = offset + 5
        qtype = struct.unpack_from("!H", data, offset + 1)[0]
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("127.0.0.1") if qtype == 1 else b""
        sock.sendto(data[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0)
                    + data[12:end] + answer, self.client_address)


def stop_core(core):
    core.terminate()
    try:
        core.wait(timeout=5)
    except subprocess.TimeoutExpired:
        core.kill()
        core.wait(timeout=5)


def main(config_path=D["CONFIG"]):
    SOURCE = D["load_source"](config_path)
    with_home = "Airport_02" in SOURCE["proxy-providers"]
    high_default = "机场名称2优先-自动" if with_home else "机场名称1优先-自动"
    high_japan = "日本·机场名称2优先" if with_home else "日本·机场名称1优先"
    high_default_label, high_jp_label = ("2-HK", "2-JP") if with_home else ("1-JP", "1-JP")
    core, servers, checks = None, [], []
    with tempfile.TemporaryDirectory(prefix="mihomo-runtime-lifecycle-") as directory:
        try:
            nodes, proxies = {name: [] for name in SOURCE["proxy-providers"]}, {}
            examples = [("1-HK", "1", "HongKong 01"), ("1-JP", "1", "日本01"),
                        ("3-JP", "3", "日本01|CTCUCM"), ("3-SG", "3", "新加坡01|BGP"),
                        ("3-US", "3", "美国01|0.1x"), ("4-JP", "4", "日本备用"),
                        ("4-DE", "4", "德国备用")]
            if with_home:
                examples.extend([("2-HK", "2", "HongKong 01"), ("2-JP", "2", "日本01")])
            for label, airport, raw_name in examples:
                server = D["Server"](("127.0.0.1", 0), ProxyHandler)
                server.label, server.airport, server.reject_connect, server.rejections = label, airport, False, []
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
                proxies[label] = server
                nodes[f"Airport_0{airport}"].append({"name": raw_name, "type": "http", "server": "127.0.0.1",
                                                     "port": server.server_address[1]})
            subscription = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SubscriptionHandler)
            subscription.payloads = {f"/{name}": json.dumps({"proxies": value}).encode() for name, value in nodes.items()}
            threading.Thread(target=subscription.serve_forever, daemon=True).start()
            servers.append(subscription)
            upstream = socketserver.ThreadingUDPServer(("127.0.0.1", 0), DNSHandler)
            threading.Thread(target=upstream.serve_forever, daemon=True).start()
            servers.append(upstream)
            providers = copy.deepcopy(SOURCE["proxy-providers"])
            for name, provider in providers.items():
                provider.update(url=f"http://127.0.0.1:{subscription.server_address[1]}/{name}",
                                path=str(Path(directory) / f"{name}.json"))
                provider["health-check"]["url"] = H["GENERIC"]
            groups = copy.deepcopy(SOURCE["proxy-groups"])
            urls = {SOURCE["Fallback_Base"]["url"]: H["GENERIC"],
                    SOURCE["GitHub_Urltest_Base"]["url"]: H["GITHUB"],
                    SOURCE["Cloudflare_Urltest_Base"]["url"]: H["CLOUDFLARE"]}
            for group in groups:
                if "url" in group:
                    group["url"] = urls[group["url"]]
            # 周期、超时、lazy、max-failed-times 一律保留原值；只替换外部依赖。
            for original, fixture in zip(SOURCE["proxy-groups"], groups):
                assert {k: v for k, v in original.items() if k != "url"} == {
                    k: v for k, v in fixture.items() if k != "url"}
            rule_providers = {name: {"type": "inline", "behavior": value["behavior"], "payload": value.get("payload", [])}
                              for name, value in SOURCE["rule-providers"].items()}
            fixtures = {"cloudflare_domain": ["+.cloudflare.com"],
                        "google_domain": ["google.com", "google.cloudflare.com"],
                        "fcm_domain": ["fcm.invalid"],
                        "googlevpn_domain": ["googlevpn.invalid"],
                        "microsoft_domain": ["microsoft.com", "microsoft.cloudflare.com"],
                        "onedrive_domain": ["onedrive.invalid"],
                        "netflix_domain": ["netflix.com", "netflix.cloudflare.com"],
                        "disney_domain": ["disneyplus.com", "disney.cloudflare.com"],
                        "ai!cn_domain": ["ai.cloudflare.com"],
                        "reddit_domain": ["reddit.invalid", "reddit.cloudflare.com"],
                        "telegram_domain": ["telegram.invalid"],
                        "line_domain": ["line.invalid"],
                        "discord_domain": ["discord.invalid", "discord.cloudflare.com"],
                        "signal_domain": ["signal.invalid"],
                        "github_domain": ["github.com", "codeload.github.com", "release-assets.githubusercontent.com"],
                        "paypal_domain": ["paypal.invalid", "paypal.cloudflare.com"],
                        "Wise_domain": ["wise.invalid", "wise.cloudflare.com"],
                        "talkatone_domain": ["talkatone.invalid"],
                        "youtube_domain": ["youtube.com"],
                        "appleTV_domain": ["appletv.invalid"]}
            for name, values in fixtures.items():
                rule_providers[name]["payload"] = values
            hosts = ["cloudflare.com", *[host for name, members in fixtures.items()
                                         if name != "cloudflare_domain" for host in members]]
            D["CF_HOSTS"].update(host for host in hosts if host.endswith("cloudflare.com"))
            mixed, control, dns_port = [H["free_port"]() for _ in range(3)]
            dns = copy.deepcopy(SOURCE["dns"])
            local_dns = f"udp://127.0.0.1:{upstream.server_address[1]}#DIRECT"
            dns.update(listen=f"127.0.0.1:{dns_port}", **{"use-system-hosts": False,
                "default-nameserver": [local_dns], "nameserver": [local_dns],
                "proxy-server-nameserver": [local_dns], "direct-nameserver": [local_dns]})
            dns["nameserver-policy"] = {key: value if isinstance(value, str) and value.startswith("rcode://") else [local_dns]
                                       for key, value in dns["nameserver-policy"].items()}
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"mixed-port": mixed, "external-controller": f"127.0.0.1:{control}",
                "bind-address": "127.0.0.1", "allow-lan": False, "log-level": "debug", "dns": dns,
                "tun": {"enable": False}, "profile": SOURCE["profile"], "unified-delay": SOURCE["unified-delay"],
                "hosts": dict.fromkeys(hosts, "127.0.0.1"),
                "proxies": SOURCE["proxies"], "proxy-providers": providers, "proxy-groups": groups, "rule-providers": rule_providers,
                "rules": SOURCE["rules"], "sub-rules": SOURCE["sub-rules"]}, ensure_ascii=False))
            validation = subprocess.run([H["MIHOMO"], "-t", "-d", directory, "-f", str(config)],
                                        capture_output=True, text=True, timeout=10)
            assert validation.returncode == 0, validation.stdout + validation.stderr
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, method="GET", body=None):
                payload = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(f"http://127.0.0.1:{control}{path}", data=payload, method=method,
                                             headers={"Content-Type": "application/json"})
                with opener.open(req, timeout=5) as response:
                    return json.load(response) if response.status != 204 else None

            def group(name):
                return api("/proxies/" + urllib.parse.quote(name, safe=""))

            def choose(name, candidate):
                api("/proxies/" + urllib.parse.quote(name, safe=""), "PUT", {"name": candidate})

            def request(host):
                result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--noproxy", "",
                    "--proxy", f"http://127.0.0.1:{mixed}", "--max-time", "3", f"http://{host}/file"],
                    capture_output=True, timeout=4)
                return result.returncode, result.stdout.decode()

            # HTTP订阅异步载入；初次父组检查可能遇到空池，允许完整60秒周期就绪。
            def expect(host, label, seconds=75):
                try:
                    H["until"](lambda: request(host) == (0, label), seconds=seconds)
                except AssertionError:
                    names = ["Google", "Microsoft", "NETFLIX", "DisneyPlus", "Reddit", "境外通信", "境外影音",
                             "机场名称1优先", "机场名称1地区优先", "机场名称1-香港", "日本-机场名称1优先", "机场名称1-日本",
                             "开发下载", "纯下载", "纯下载-自动"]
                    if with_home:
                        names.extend(["家宽优先", "机场名称2地区优先", "机场名称2-香港", "日本-高要求", "机场名称2-日本"])
                    raise AssertionError({"host": host, "expected": label, "actual": request(host),
                                          "groups": {name: group(name) for name in names},
                                          "core_log": (Path(directory) / "core.log").read_text()[-6000:]}) from None

            def start():
                with (Path(directory) / "core.log").open("a") as log:
                    return subprocess.Popen([H["MIHOMO"], "-d", directory, "-f", str(config)],
                                            stdout=log, stderr=subprocess.STDOUT)

            def fake_ip(host):
                question = b"".join(bytes([len(label)]) + label.encode() for label in host.split(".")) + b"\0\0\1\0\1"
                packet = struct.pack("!HHHHHH", 1987, 0x0100, 1, 0, 0, 0) + question
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(3)
                    sock.sendto(packet, ("127.0.0.1", dns_port))
                    response = sock.recv(4096)
                assert response[:2] == packet[:2] and struct.unpack_from("!H", response, 6)[0] == 1
                value = socket.inet_ntoa(response[-4:])
                assert value.startswith("198.18."), value
                return value

            core = start()
            H["until"](lambda: api("/version"), seconds=10)
            expect("google.com", "1-JP")
            expect("cloudflare.com", "3-JP")
            expect("ai.cloudflare.com", "1-JP")
            assert group("AI")["now"] == "AI-机场名称1-日本"
            assert group("AI-机场名称1-日本")["now"] == "[机场名称1]日本01"
            selected_at = time.monotonic()
            choose("Google", "日本·机场名称1优先")
            assert group("Google")["now"] == "日本·机场名称1优先"
            expect("google.com", "1-JP")
            startup_region_settlement_ms = round((time.monotonic() - selected_at) * 1000, 1)
            expect("fcm.invalid", "1-JP")
            expect("googlevpn.invalid", "1-JP")
            expect("microsoft.com", "3-JP")
            assert group("Microsoft")["now"] == "机场名称3优先-自动"
            choose("Microsoft", "日本·机场名称3优先")
            expect("microsoft.com", "3-JP")
            expect("onedrive.invalid", "3-JP")
            expect("google.com", "1-JP")
            choose("Microsoft", "[机场名称3]新加坡01|BGP")
            expect("microsoft.com", "3-SG")
            expect("onedrive.invalid", "3-SG")
            expect("google.com", "1-JP")
            expect("netflix.com", high_default_label)
            expect("disneyplus.com", high_default_label)
            choose("NETFLIX", high_japan)
            expect("netflix.com", high_jp_label)
            expect("disneyplus.com", high_default_label)
            assert group("DisneyPlus")["now"] == high_default
            choose("DisneyPlus", "[机场名称4]日本备用")
            expect("disneyplus.com", "4-JP")
            expect("netflix.com", high_jp_label)
            choose("NETFLIX", "[机场名称4]日本备用")
            assert group("DisneyPlus")["now"] == "[机场名称4]日本备用"
            choose("DisneyPlus", high_japan)
            expect("disneyplus.com", high_jp_label)
            expect("google.com", "1-JP")
            expect("netflix.com", "4-JP")
            expect("reddit.invalid", high_default_label)
            choose("Reddit", "[机场名称3]日本01|CTCUCM")
            expect("reddit.invalid", "3-JP")
            expect("netflix.com", "4-JP")
            expect("disneyplus.com", high_jp_label)
            assert group("境外通信")["now"] == "机场名称3优先-自动"
            expect("telegram.invalid", "3-JP")
            choose("境外通信", "日本·机场名称3优先")
            for host in ("telegram.invalid", "line.invalid", "discord.invalid", "discord.cloudflare.com", "signal.invalid"):
                expect(host, "3-JP")
            expect("google.com", "1-JP")
            expect("microsoft.com", "3-SG")
            expect("youtube.com", "3-JP")
            choose("境外影音", "[机场名称3]新加坡01|BGP")
            expect("youtube.com", "3-SG")
            expect("appletv.invalid", "3-SG")
            expect("discord.invalid", "3-JP")
            expect("netflix.com", "4-JP")
            choose("通用代理", "[机场名称4]德国备用")
            expect("cloudflare.com", "4-DE")
            expect("github.com", "3-JP")
            assert group("开发下载")["now"] == "机场名称3优先-自动"
            assert group("纯下载")["now"] == "机场名称3优先-自动"
            choose("开发下载", "[机场名称1]日本01")
            expect("github.com", "1-JP")
            expect("codeload.github.com", "3-US")
            choose("纯下载", "[机场名称4]日本备用")
            expect("codeload.github.com", "4-JP")
            expect("release-assets.githubusercontent.com", "4-JP")
            expect("github.com", "1-JP")
            choose("开发下载", "[机场名称3]新加坡01|BGP")
            expect("github.com", "3-SG")
            expect("codeload.github.com", "4-JP")
            choose("金融", "机场名称3优先-自动")
            for host in ("paypal.invalid", "wise.invalid", "paypal.cloudflare.com", "wise.cloudflare.com"):
                expect(host, "3-JP")
            expect("talkatone.invalid", high_default_label)
            assert group("Talkatone")["now"] == high_default
            selections = {"Google": "日本·机场名称1优先", "Microsoft": "[机场名称3]新加坡01|BGP",
                          "NETFLIX": "[机场名称4]日本备用", "DisneyPlus": high_japan,
                          "Reddit": "[机场名称3]日本01|CTCUCM", "境外通信": "日本·机场名称3优先",
                          "境外影音": "[机场名称3]新加坡01|BGP",
                          "通用代理": "[机场名称4]德国备用", "金融": "机场名称3优先-自动",
                          "开发下载": "[机场名称3]新加坡01|BGP", "纯下载": "[机场名称4]日本备用",
                          "Talkatone": high_default}
            mappings = {host: fake_ip(host) for host in ["one.fixture.invalid", "two.fixture.invalid"]}
            assert len(set(mappings.values())) == 2
            stop_core(core)
            core = None
            core = start()
            H["until"](lambda: api("/version"), seconds=10)
            for name, candidate in selections.items():
                assert group(name)["now"] == candidate, name
            for host, label in [("google.com", "1-JP"), ("google.cloudflare.com", "1-JP"),
                                ("fcm.invalid", "1-JP"), ("googlevpn.invalid", "1-JP"),
                                ("microsoft.com", "3-SG"), ("microsoft.cloudflare.com", "3-SG"),
                                ("onedrive.invalid", "3-SG"),
                                ("netflix.com", "4-JP"), ("netflix.cloudflare.com", "4-JP"),
                                ("disneyplus.com", high_jp_label), ("disney.cloudflare.com", high_jp_label),
                                ("ai.cloudflare.com", "1-JP"),
                                ("reddit.invalid", "3-JP"), ("reddit.cloudflare.com", "3-JP"),
                                ("telegram.invalid", "3-JP"), ("discord.cloudflare.com", "3-JP"),
                                ("youtube.com", "3-SG"), ("appletv.invalid", "3-SG"),
                                ("cloudflare.com", "4-DE"), ("github.com", "3-SG"),
                                ("codeload.github.com", "4-JP"), ("release-assets.githubusercontent.com", "4-JP"),
                                ("paypal.invalid", "3-JP"), ("wise.cloudflare.com", "3-JP"),
                                ("talkatone.invalid", high_default_label)]:
                expect(host, label)
            # 逆序查询使“重启后碰巧按相同顺序重新分配”无法冒充缓存命中。
            assert {host: fake_ip(host) for host in reversed(mappings)} == mappings
            checks.append("Google含FCM/VPN用普通政策、Microsoft含OneDrive用成本政策且独立；Netflix/Disney双向交换高要求地区与节点，Reddit独立；相关业务通用/CF路径跨同次重启恢复，fake-ip逆序查询不变")
            checks.append("通信聚合Telegram/LINE/Discord/Signal用成本政策，日本成本跨重启保留；独立于Google、Microsoft和YouTube/AppleTV影音聚合，不改变严格媒体")
            checks.append("开发下载与纯下载双向手选隔离；GitHub网页与两个纯下载域使用不同节点并跨重启分别恢复")

            path = "/providers/proxies/Airport_04"
            old_names = [node["name"] for node in api("/providers/proxies")["providers"]["Airport_04"]["proxies"]]
            cached = (Path(directory) / "Airport_04.json").read_bytes()
            for bad in (b"invalid subscription", b'{"proxies": []}'):
                subscription.payloads["/Airport_04"] = bad
                try:
                    api(path, "PUT")
                except urllib.error.HTTPError as error:
                    assert error.code >= 400
                else:
                    raise AssertionError("无效订阅不应替换旧池")
                assert [node["name"] for node in api("/providers/proxies")["providers"]["Airport_04"]["proxies"]] == old_names
                assert (Path(directory) / "Airport_04.json").read_bytes() == cached
                expect("google.com", "1-JP")
                expect("microsoft.com", "3-SG")
                expect("netflix.com", "4-JP")
                expect("disneyplus.com", high_jp_label)
                expect("reddit.invalid", "3-JP")
                expect("telegram.invalid", "3-JP")
                expect("youtube.com", "3-SG")
                expect("cloudflare.com", "4-DE")
                expect("github.com", "3-SG")
                expect("codeload.github.com", "4-JP")
                for name, candidate in selections.items():
                    assert group(name)["now"] == candidate, name
            updated = [nodes["Airport_04"][0], {**nodes["Airport_04"][1], "name": "香港新增"}]
            subscription.payloads["/Airport_04"] = json.dumps({"proxies": updated}).encode()
            api(path, "PUT")
            H["until"](lambda: "[机场名称4]香港新增" in group("通用代理")["all"])
            assert "[机场名称4]德国备用" not in group("通用代理")["all"]
            expect("google.com", "1-JP")
            expect("microsoft.com", "3-SG")
            expect("netflix.com", "4-JP")
            expect("disneyplus.com", high_jp_label)
            expect("reddit.invalid", "3-JP")
            expect("telegram.invalid", "3-JP")
            expect("youtube.com", "3-SG")
            expect("cloudflare.com", "3-JP")
            expect("github.com", "3-SG")
            expect("codeload.github.com", "4-JP")
            for name, candidate in selections.items():
                if name != "通用代理":
                    assert group(name)["now"] == candidate, name
            checks.append("无效/全空 HTTP 订阅保留旧池与磁盘缓存，正常更新恢复；已删除手选候选回到默认")

            choose("Google", "机场名称1优先-自动")
            expect("google.com", "1-JP")
            started = time.monotonic()
            proxies["1-JP"].reject_connect = True
            first_results = [request("google.com")[0] for _ in range(3)]
            expect("google.com", "1-HK", seconds=90)
            expect("netflix.com", "4-JP")
            failed_over = time.monotonic()
            assert proxies["1-JP"].rejections, "必须实际触发代理 CONNECT 拨号拒绝"
            proxies["1-JP"].reject_connect = False
            restored = time.monotonic()
            expect("google.com", "1-JP", seconds=100)
            failback = time.monotonic()
            timings = {"startup_region_settlement_ms": startup_region_settlement_ms,
                       "failure_to_same_airport_fallback_ms": round((failed_over - started) * 1000, 1),
                       "recovery_to_preferred_region_ms": round((failback - restored) * 1000, 1),
                       "initial_three_curl_codes": first_results, "rejected_proxy_handshakes": len(proxies["1-JP"].rejections)}
            checks.append("保留 60/30/18/45 秒周期与 3500ms/3 次参数，测量真实代理拨号失败及优先地区恢复")
            proxies["1-JP"].reject_connect = True
            assert request("ai.cloudflare.com")[0] != 0
            assert group("AI")["now"] == "AI-机场名称1-日本"
            choose("AI", "机场名称3优先-自动")
            expect("ai.cloudflare.com", "3-JP")
            assert group("Google")["now"] == "机场名称1优先-自动"
            expect("microsoft.com", "3-SG")
            proxies["1-JP"].reject_connect = False
            choose("AI", "美国·机场名称1优先")
            expect("ai.cloudflare.com", "3-US")
            if with_home:
                choose("AI", "机场名称2优先-自动")
                expect("ai.cloudflare.com", "2-HK")
            choose("AI", "[机场名称3]新加坡01|BGP")
            expect("ai.cloudflare.com", "3-SG")
            choose("AI", "AI-机场名称1-日本")
            expect("ai.cloudflare.com", "1-JP")
            checks.append("AI默认节点失败不自动换路；用户可在规则模式覆盖为其他机场自动、地区或实际节点，其他业务选择保持")
            shortcut = "自建/家宽节点"
            assert group(shortcut)["all"] == ["REJECT"]
            home_nodes = [{**nodes["Airport_04"][1], "name": "德国家宽"},
                          {**nodes["Airport_04"][0], "name": "日本自建"}]
            subscription.payloads["/Airport_04"] = json.dumps({"proxies": updated + home_nodes}).encode()
            api(path, "PUT")
            home_de, home_jp = "[机场名称4]德国家宽", "[机场名称4]日本自建"
            H["until"](lambda: group(shortcut)["all"] == [home_de, home_jp])
            shared_businesses = ("AI", "Google", "金融", "开发下载", "纯下载")
            shared_hosts = ("ai.cloudflare.com", "google.com", "google.cloudflare.com", "paypal.invalid", "wise.cloudflare.com",
                            "github.com", "codeload.github.com")
            for business in shared_businesses:
                choose(business, shortcut)
            choose(shortcut, home_jp)
            for host in shared_hosts:
                expect(host, "4-JP")
            choose(shortcut, home_de)
            for host in shared_hosts:
                expect(host, "4-DE")
            expect("netflix.com", "4-JP")
            expect("microsoft.com", "3-SG")
            choose("GLOBAL", shortcut)
            stop_core(core)
            core = start()
            H["until"](lambda: api("/version"), seconds=10)
            H["until"](lambda: group(shortcut)["all"] == [home_de, home_jp])
            assert group(shortcut)["now"] == home_de
            for business in (*shared_businesses, "GLOBAL"):
                assert group(business)["now"] == shortcut, business
            for host in shared_hosts:
                expect(host, "4-DE")
            api("/configs", "PATCH", {"mode": "global"})
            expect("google.com", "4-DE")
            expect("netflix.com", "4-DE")
            choose(shortcut, home_jp)
            expect("netflix.com", "4-JP")
            api("/configs", "PATCH", {"mode": "rule"})
            proxies["4-JP"].reject_connect = True
            assert request("google.com")[0] != 0
            assert group(shortcut)["now"] == home_jp
            expect("microsoft.com", "3-SG")
            proxies["4-JP"].reject_connect = False
            expect("google.com", "4-JP")
            subscription.payloads["/Airport_04"] = json.dumps({"proxies": updated}).encode()
            api(path, "PUT")
            H["until"](lambda: group(shortcut)["all"] == ["REJECT"])
            assert request("google.com")[0] != 0
            assert group("Google")["now"] == shortcut
            checks.append("自建/家宽快捷手选跨业务与GLOBAL共享、重启保留、未选择业务隔离；节点失败不换路，筛空后拒绝")
            print(json.dumps({"passed": True, "config": str(Path(config_path).resolve()), "with_home": with_home,
                "groups": len(groups), "checks": checks, "timings": timings,
                "limit": "仅少节点回环 CONNECT 立即失败；拒绝次数包括健康探测，不代表用户失败请求数或生产恢复上限"},
                ensure_ascii=False, indent=2))
        finally:
            if core is not None:
                stop_core(core)
            for server in servers:
                server.shutdown()
                server.server_close()


def interrupted(signum, frame):
    raise InterruptedError("运行生命周期验证被中止")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=D["CONFIG"], help="直接读取实际配置文件")
    main(parser.parse_args().config)
