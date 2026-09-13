#!/usr/bin/env python3
"""直接读取独立三/四机场配置，以本机假代理验证政策及探针隔离；不使用真实订阅。"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
H = runpy.run_path(str(Path(__file__).with_name("proxy-fixture.py")))
GENERIC, GITHUB, CF = H["GENERIC"], H["GITHUB"], H["CLOUDFLARE"]
CONFIG = Path(os.environ.get("MIHOMO_DESIGN_CONFIG", str(ROOT / "configfull_new.yaml")))
Server, Handler, CF_HOSTS = H["Server"], H["Handler"], H["CF_HOSTS"]


def load_source(config=CONFIG):
    return json.loads(subprocess.check_output(["ruby", "-ryaml", "-rjson", "-e",
        "puts JSON.generate(YAML.load(STDIN.read, aliases: true))"], input=Path(config).read_bytes(), timeout=10))


def static_shared_checks():
    three = load_source(ROOT / "configfull_new.yaml")
    four = load_source(ROOT / "cinfigfull_new_4.yaml")
    assert set(three["proxy-providers"]) == {"Airport_01", "Airport_03", "Airport_04"}
    assert set(four["proxy-providers"]) == {"Airport_01", "Airport_02", "Airport_03", "Airport_04"}
    common = {"dns", "tun", "sniffer", "profile", "rules", "rule-providers", "unified-delay", "tcp-concurrent",
              "Fallback_Base", "Urltest_Base", "GitHub_Urltest_Base", "Cloudflare_Urltest_Base",
              "PProviders", "home_only", "reserve_region_order", "lowrate_mitm"}
    common.update(key for key in three if key.startswith(("region_", "exclude_")))
    for key in common:
        assert three[key] == four[key], key
    for provider in three["proxy-providers"]:
        assert three["proxy-providers"][provider] == four["proxy-providers"][provider], provider
    assert three["sub-rules"]["业务分流"] == four["sub-rules"]["业务分流"]


def static_checks(source):
    groups = {g["name"]: g for g in source["proxy-groups"]}
    outbounds = {p["name"]: p for p in source["proxies"]}
    known = set(groups) | set(outbounds) | {"DIRECT", "REJECT", "REJECT-DROP"}
    assert len(groups) == len(source["proxy-groups"]), "重复组名"
    assert len(outbounds) == len(source["proxies"]), "重复出口名"
    assert source["profile"]["store-selected"] is True
    assert source["profile"]["store-fake-ip"] is True
    for name in (*groups, *outbounds, *source["sub-rules"]):
        assert "机场" not in re.sub(r"机场名称[1-4](?![0-9])", "", name), name
    for name, group in groups.items():
        visible = not group.get("hidden", False)
        assert (group["type"] == "select") == visible, name
        assert group["type"] != "load-balance", name
        if visible:
            assert group.get("icon", "").startswith("https://"), name
        children = group.get("proxies", [])
        assert len(children) == len(set(children)), name
        assert set(children) <= known, name
        assert set(group.get("use", [])) <= set(source["proxy-providers"]), name

    # GLOBAL 和 rematch 的终点必须可直接拨号，不能再次进入 rematch。
    def dialable(name, ancestors=()):
        assert name not in ancestors, (name, ancestors)
        assert name not in outbounds, name
        for child in groups.get(name, {}).get("proxies", []):
            dialable(child, (*ancestors, name))
    dialable("GLOBAL")
    referenced = set()
    for outbound in outbounds.values():
        assert outbound["type"] == "rematch"
        target = outbound["target-sub-rule"]
        assert target in source["sub-rules"], target
        referenced.add(target)
    # SUB-RULE 只返回首个业务；外层拒绝不支持 UDP 的选择，禁止跨业务下落。
    assert source["rules"] == ["SUB-RULE,(NETWORK,tcp),业务分流",
                               "SUB-RULE,(NETWORK,udp),业务分流", "NETWORK,udp,REJECT"]
    assert referenced | {"业务分流"} == set(source["sub-rules"])
    assert source["sub-rules"]["业务分流"][-1] == "MATCH,通用代理"
    for rule in source["sub-rules"]["业务分流"]:
        parts = rule.split(",")
        assert (parts[-2] if parts[-1] == "no-resolve" else parts[-1]) in known, rule
    for name in referenced:
        rules = source["sub-rules"][name]
        assert rules[-1] == "NETWORK,udp,REJECT"
        for rule in rules:
            if rule.endswith(",REJECT"):
                assert "NETWORK,udp" in rule, rule
                continue
            target = rule.rsplit(",", 1)[-1]
            assert target in groups and groups[target]["type"] != "select", rule
            dialable(target)

    ai = groups["AI-机场名称1-日本"]
    assert groups["AI"]["proxies"][0] == ai["name"]
    assert ai["type"] == "url-test" and ai["use"] == ["Airport_01"]
    assert ai["filter"] == source["region_jp"]
    assert ai["exclude-filter"] == source["exclude_lowrate"]
    assert ai["url"] == source["Cloudflare_Urltest_Base"]["url"]
    assert groups["自建/家宽节点"]["empty-fallback"] == "REJECT"
    assert groups["Cloudflare Tunnel"]["proxies"][0] == "DIRECT"
    assert set(groups["Cloudflare Tunnel"]["use"]) == set(source["proxy-providers"])
    assert set(source["rule-providers"]["cloudflare_tunnel_ip"]["payload"]) == {
        f'{ip}/{128 if ":" in ip else 32}' for ip in H["TUNNEL_IPS"]}
    update = groups["规则更新"]
    assert update["type"] == "fallback" and update["proxies"][-1] == "DIRECT"
    assert update["url"] == source["GitHub_Urltest_Base"]["url"] and update["expected-status"] == 200
    assert all(name.startswith("GitHub-") for name in update["proxies"][:-1])
    assert all(p["proxy"] == "规则更新" for p in source["rule-providers"].values() if p["type"] == "http")


def main(config=CONFIG):
    source = load_source(config)
    with_home = "Airport_02" in source["proxy-providers"]
    static_checks(source)
    static_shared_checks()
    high_preference = "机场名称2优先" if with_home else "机场名称1优先"
    core, servers, checks = None, [], []
    with tempfile.TemporaryDirectory(prefix="mihomo-config-design-") as directory:
        try:
            groups = copy.deepcopy(source["proxy-groups"])
            urls = {source["Fallback_Base"]["url"]: GENERIC, source["GitHub_Urltest_Base"]["url"]: GITHUB,
                    source["Cloudflare_Urltest_Base"]["url"]: CF}
            for item in groups:
                if "url" in item or item["type"] in ("url-test", "load-balance"):
                    item["url"] = urls.get(item.get("url"), GENERIC)
                if item["type"] in ("fallback", "url-test"):
                    item.update(interval=1, lazy=False)
            nodes = {name: [] for name in source["proxy-providers"]}
            examples = [("1-jp", "1", "日本01"), ("1-steady", "1", "HongKong 01"),
                        ("1-fast", "1", "HongKong 06"), ("1-excluded", "1", "HongKong 05"),
                        ("3-JP", "3", "日本01|CTCUCM"), ("3-JP2", "3", "日本02|BGP"),
                        ("3-US", "3", "美国01|0.1x"), ("3-SG", "3", "新加坡01|BGP"),
                        ("3-excluded", "3", "日本01|CTCU"), ("3-outside", "3", "德国01"),
                        ("4-DE", "4", "德国备用"), ("4-JP-A", "4", "日本备用01"), ("4-JP-B", "4", "日本备用02")]
            if with_home:
                examples.extend([("2-HK", "2", "HongKong 01"), ("2-JP", "2", "日本01")])
            by_label = {}
            for label, airport, name in examples + [("DIRECT", "direct", "")]:
                server = Server(("127.0.0.1", 0), Handler)
                server.label, server.airport = label, airport
                if label in ("1-fast", "4-DE", "4-JP-B"):
                    server.probe_delays = dict.fromkeys(H["EXPECTED"], .005)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
                by_label[label] = server
                if airport != "direct":
                    nodes[f"Airport_0{airport}"].append({"name": f"[机场名称{airport}]{name}", "type": "http",
                                                        "server": "127.0.0.1", "port": server.server_address[1]})
            # 同一探针既能经代理访问，也能直连，覆盖规则更新的 DIRECT 兜底。
            probe_origin = f'http://127.0.0.1:{by_label["DIRECT"].server_address[1]}'
            for item in groups:
                if "url" in item:
                    item["url"] = probe_origin + urllib.parse.urlsplit(item["url"]).path
            providers = {}
            for name, proxies in nodes.items():
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps({"proxies": proxies}))
                providers[name] = {"type": "file", "path": str(path), "health-check": {
                    "enable": True, "url": probe_origin + "/google", "expected-status": 204, "timeout": 3500, "interval": 1, "lazy": False}}
                suffix = source["proxy-providers"][name].get("override", {}).get("additional-suffix")
                if suffix:
                    providers[name]["override"] = {"additional-suffix": suffix}
            rules = {name: {"type": "inline", "behavior": value["behavior"], "payload": value.get("payload", [])}
                     for name, value in source["rule-providers"].items()}
            membership = {
                "github_domain": ["+.github.com", "+.githubusercontent.com", "wise.gh.invalid"],
                "google_domain": ["google.com", "google.cf.invalid"],
                "youtube_domain": ["youtube.com"],
                "bahamut_domain": ["gamer.com.tw", "bahamut.cf.invalid"],
                "dev_download_domain": ["unpkg.com"],
                "Wise_domain": ["wise.invalid", "wise.cf.invalid", "wise.gh.invalid"],
                "paypal_domain": ["paypal.cf.invalid"],
                "ai!cn_domain": ["ai.cf.invalid"],
            }
            CF_HOSTS.update(["cloudflare.com", "unpkg.com", *(host for values in membership.values()
                            for host in values if host.endswith(".cf.invalid"))])
            membership["cloudflare_domain"] = sorted(CF_HOSTS)
            for name, payload in membership.items():
                rules[name]["payload"] = payload
            hosts = CF_HOSTS | {"github.com", "codeload.github.com", "release-assets.githubusercontent.com"}
            hosts.update(host for values in membership.values() for host in values if not host.startswith("+."))
            mixed, control = H["free_port"](), H["free_port"]()
            runtime_config = Path(directory) / "config.json"
            runtime_config.write_text(json.dumps({"mixed-port": mixed, "external-controller": f"127.0.0.1:{control}",
                "bind-address": "127.0.0.1", "allow-lan": False, "log-level": "silent", "dns": {"enable": False},
                "tun": {"enable": False}, "unified-delay": source["unified-delay"],
                "profile": {"store-selected": False, "store-fake-ip": False}, "proxy-providers": providers,
                "proxies": source["proxies"], "proxy-groups": groups, "rule-providers": rules, "rules": source["rules"], "sub-rules": source["sub-rules"],
                "hosts": dict.fromkeys(hosts, "127.0.0.1")}, ensure_ascii=False))
            validation = subprocess.run([H["MIHOMO"], "-t", "-d", directory, "-f", str(runtime_config)],
                                        capture_output=True, text=True, timeout=10)
            assert validation.returncode == 0, validation.stdout + validation.stderr
            core = subprocess.Popen([H["MIHOMO"], "-d", directory, "-f", str(runtime_config)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, body=None, method="GET"):
                data = json.dumps(body).encode() if body is not None else None
                request = urllib.request.Request(f"http://127.0.0.1:{control}{path}", data=data, method=method,
                                                 headers={"Content-Type": "application/json"})
                with opener.open(request, timeout=2) as response:
                    return json.load(response) if response.status != 204 else None

            def group(name):
                return api("/proxies/" + urllib.parse.quote(name, safe=""))

            def choose(name, target):
                api("/proxies/" + urllib.parse.quote(name, safe=""), {"name": target}, "PUT")

            def request(host):
                port = by_label["DIRECT"].server_address[1]
                result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--noproxy", "",
                    "--proxy", f"http://127.0.0.1:{mixed}", "--max-time", "2", f"http://{host}:{port}/file"],
                    capture_output=True, timeout=3)
                return result.returncode, result.stdout.decode()

            def expect(host, label):
                try:
                    H["until"](lambda: request(host) == (0, label))
                except AssertionError:
                    raise AssertionError((host, label, request(host))) from None

            def fail(service, airports=(), labels=()):
                with H["LOCK"]:
                    H["FAILED"].update((service, airport) for airport in airports)
                    H["NODE_FAILED"].update((service, label) for label in labels)

            def recover():
                with H["LOCK"]:
                    H["FAILED"].clear()
                    H["NODE_FAILED"].clear()

            H["until"](lambda: api("/version"))
            for host, label in [("github.com", "3-JP2"), ("codeload.github.com", "3-US"),
                                ("cloudflare.com", "3-JP"), ("google.com", "1-jp")]:
                expect(host, label)
            primary_nodes = api("/providers/proxies")["providers"]["Airport_01"]["proxies"]
            cf_url = probe_origin + "/cloudflare"
            tested = {node["name"] for node in primary_nodes
                      if node.get("extra", {}).get(cf_url, {}).get("history")}
            assert "[机场名称1]日本01" in tested
            assert "[机场名称1]HongKong 05" not in tested
            checks.append("手选不注册全量 CF 探测；专用池仍探测日本，排除的香港节点不额外探测")
            checks.append("开发默认成本政策；GitHub地区稳定，纯下载允许同机场跨区择优")

            choose("开发下载", "机场名称1优先-自动")
            expect("github.com", "1-jp")
            expect("codeload.github.com", "3-US")
            expect("youtube.com", "3-JP")
            assert "[机场名称1]HongKong 05" not in group("GitHub-机场名称1-香港")["all"]
            fail(GITHUB, labels=["1-jp"])
            expect("github.com", "1-fast")
            fail(GITHUB, labels=["1-fast"])
            expect("github.com", "1-steady")
            fail(GITHUB, labels=["1-steady"])
            expect("github.com", "2-HK" if with_home else "3-JP2")
            recover()
            expect("github.com", "1-jp")
            checks.append("显式机场名称1优先只改开发业务；同区失败后先同机场换区")
            choose("开发下载", "机场名称3优先-自动")
            fail(GITHUB, airports=["1", "2", "3"])
            expect("github.com", "4-JP-A")
            assert group("GitHub-机场名称4")["all"] == ["[机场名称4]日本备用01", "[机场名称4]日本备用02", "[机场名称4]德国备用"]
            fail(GITHUB, labels=["4-JP-A"])
            expect("github.com", "4-JP-B")
            fail(GITHUB, labels=["4-JP-B"])
            expect("github.com", "4-DE")
            fail(GITHUB, labels=["4-DE"])
            H["until"](lambda: group("规则更新")["now"] == "DIRECT")
            recover()
            expect("github.com", "3-JP2")
            fail(GITHUB, airports=["3"])
            H["until"](lambda: group("规则更新")["now"] == "GitHub-机场名称1")
            recover()
            checks.append("机场名称4按顺序耗尽同区备用再换地区")

            # 香港明显更快时，仅纯下载跨区择优；普通 GitHub 仍优先日本。
            by_label["1-jp"].probe_delays = {GITHUB: .4}
            choose("开发下载", "机场名称1优先-自动")
            choose("纯下载", "机场名称1优先-自动")
            for host in ["codeload.github.com", "release-assets.githubusercontent.com"]:
                expect(host, "1-fast")
            expect("github.com", "1-jp")
            del by_label["1-jp"].probe_delays
            expect("github.com", "1-jp")
            choose("纯下载", "机场名称3优先-自动")
            choose("开发下载", "机场名称3优先-自动")
            checks.append("纯下载同机场跨区择优，普通 GitHub 仍优先日本")
            if with_home:
                expect("wise.cf.invalid", "2-HK")
                fail(CF, airports=["2"])
                expect("wise.cf.invalid", "1-jp")
                recover()
                expect("wise.cf.invalid", "2-HK")

            choose("开发下载", "机场名称1优先-自动")
            fail(CF, labels=["1-jp"])
            expect("unpkg.com", "1-fast")
            expect("github.com", "1-jp")
            expect("youtube.com", "3-JP")
            recover()
            choose("开发下载", "机场名称3优先-自动")
            expect("unpkg.com", "3-JP")
            expect("github.com", "3-JP2")
            choose("开发下载", "机场名称3优先-自动")
            fail(CF, labels=["3-JP", "3-JP2"])
            expect("unpkg.com", "3-SG")
            expect("youtube.com", "3-JP")
            fail(CF, airports=["3"])
            expect("unpkg.com", "1-jp")
            fail(CF, airports=["1"])
            expect("unpkg.com", "2-HK" if with_home else "4-JP-A")
            if with_home:
                fail(CF, airports=["2"])
                expect("unpkg.com", "4-JP-A")
            recover()
            expect("unpkg.com", "3-JP")
            fail(GENERIC, airports=["3"])
            expect("youtube.com", "1-jp")
            expect("unpkg.com", "3-JP")
            recover()
            checks.append("探针只影响对应自动池：CF/Google故障独立，机场偏好保留各自探针")

            # 同机场同地区的第二个节点：先验证择优，再验证故障切换和边界。
            ai_provider = Path(directory) / "Airport_01.json"
            ai_extra = {"name": "[机场名称1]日本02", "type": "http", "server": "127.0.0.1",
                        "port": by_label["1-fast"].server_address[1]}
            ai_provider.write_text(json.dumps({"proxies": [*nodes["Airport_01"], ai_extra]}))
            api("/providers/proxies/Airport_01", method="PUT")
            expect("ai.cf.invalid", "1-fast")
            assert group("AI-机场名称1-日本")["now"] == "[机场名称1]日本02"
            fail(CF, labels=["1-fast"])
            expect("ai.cf.invalid", "1-jp")
            fail(CF, airports=["1", "2"])
            expect("google.cf.invalid", "3-JP")
            expect("wise.cf.invalid", "3-JP")
            assert request("ai.cf.invalid")[0] != 0
            assert group("AI")["now"] == "AI-机场名称1-日本"
            recover()
            ai_provider.write_text(json.dumps({"proxies": [node for node in nodes["Airport_01"]
                                                         if "日本" not in node["name"]]}))
            api("/providers/proxies/Airport_01", method="PUT")
            H["until"](lambda: group("AI-机场名称1-日本")["all"] == ["REJECT"])
            H["until"](lambda: request("ai.cf.invalid")[0] != 0)
            ai_provider.write_text(json.dumps({"proxies": nodes["Airport_01"]}))
            api("/providers/proxies/Airport_01", method="PUT")
            expect("ai.cf.invalid", "1-jp")
            checks.append("AI按CF探针在机场名称1日本内择优及故障切换；全部故障或空池不跨机场/地区")

            # 指定日本同时验证地区边界和三层不同机场顺序。
            choose("金融", "日本·" + high_preference)
            choose("Google", "日本·机场名称1优先")
            choose("开发下载", "日本·机场名称3优先")
            expect("wise.invalid", "2-JP" if with_home else "1-jp")
            expect("paypal.cf.invalid", "2-JP" if with_home else "1-jp")
            expect("wise.gh.invalid", "2-JP" if with_home else "1-jp")
            expect("google.com", "1-jp")
            expect("google.cf.invalid", "1-jp")
            expect("github.com", "3-JP2")
            expect("codeload.github.com", "3-US")
            choose("纯下载", "日本·机场名称3优先")
            expect("codeload.github.com", "3-JP2")
            expect("unpkg.com", "3-JP")
            # 成本日本先3→1；高要求/普通日本先各自首机场；全链不借用其他地区。
            fail(GITHUB, labels=["3-JP", "3-JP2"])
            expect("github.com", "1-jp")
            fail(GITHUB, labels=["1-jp"])
            expect("github.com", "2-JP" if with_home else "4-JP-A")
            if with_home:
                fail(GITHUB, labels=["2-JP"])
            expect("github.com", "4-JP-A")
            fail(GITHUB, labels=["4-JP-A"])
            expect("github.com", "4-JP-B")
            fail(GITHUB, labels=["4-JP-B"])
            assert request("github.com")[0] != 0
            assert request("codeload.github.com")[0] != 0
            recover()
            fail(GENERIC, labels=["1-jp"])
            expect("google.com", "2-JP" if with_home else "3-JP")
            if with_home:
                fail(GENERIC, labels=["2-JP"])
            expect("google.com", "3-JP")
            fail(GENERIC, labels=["3-JP", "3-JP2"])
            expect("google.com", "4-JP-A")
            fail(GENERIC, labels=["4-JP-A", "4-JP-B"])
            assert request("google.com")[0] != 0
            assert request("gamer.com.tw")[0] != 0
            recover()
            if with_home:
                fail(CF, labels=["2-JP"])
                expect("paypal.cf.invalid", "1-jp")
            fail(CF, labels=["1-jp"])
            expect("paypal.cf.invalid", "3-JP")
            expect("github.com", "3-JP2")
            recover()
            checks.append("地区与层级协同：日本高要求2→1→3→4、普通1→2→3→4、成本3→1→2→4；无家宽跳过2，同区耗尽拒绝越区")
            for name in ("金融", "Google", "开发下载", "纯下载"):
                default = next(g for g in source["proxy-groups"] if g["name"] == name)["proxies"][0]
                choose(name, default)

            remaining = [node for node in nodes["Airport_03"] if "日本" not in node["name"]]
            (Path(directory) / "Airport_03.json").write_text(json.dumps({"proxies": remaining}))
            api("/providers/proxies/Airport_03", method="PUT")
            H["until"](lambda: group("GitHub-机场名称3-日本")["all"] == ["REJECT"])
            expect("github.com", "3-SG")
            expect("codeload.github.com", "3-US")
            checks.append("订阅更新使地区筛空后先留同机场换地区；纯下载例外不变")

            # 末尾才加入台湾候选，避免改变前面机场名称4地区顺序的测试条件。
            for label, name in [("4-TW-beta", "台湾 BETA"), ("4-TW-low", "台湾 0.3x"),
                                ("4-TW-high", "台湾 5x"), ("4-TW", "台湾普通")]:
                server = Server(("127.0.0.1", 0), Handler)
                server.label, server.airport = label, "4"
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
                nodes["Airport_04"].append({"name": f"[机场名称4]{name}", "type": "http",
                    "server": "127.0.0.1", "port": server.server_address[1]})
            (Path(directory) / "Airport_04.json").write_text(json.dumps({"proxies": nodes["Airport_04"]}))
            api("/providers/proxies/Airport_04", method="PUT")
            H["until"](lambda: group("Cloudflare-台湾")["all"] == ["[机场名称4]台湾普通"])
            expect("bahamut.cf.invalid", "4-TW")
            fail(CF, labels=["4-TW"])
            assert request("bahamut.cf.invalid")[0] != 0
            expect("unpkg.com", "3-SG")
            checks.append("CF 台湾只接纳合格台湾节点，排除 BETA/低倍率/高倍率，失败不借用其他地区")
            print(json.dumps({"passed": True, "config": str(Path(config).resolve()), "with_home": with_home, "groups": len(groups), "checks": checks},
                             ensure_ascii=False, indent=2))
        finally:
            if core is not None:
                core.terminate()
                core.wait(timeout=5)
            for server in servers:
                server.shutdown()
                server.server_close()


def interrupted(signum, frame):
    raise InterruptedError("架构验证被中止")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG, help="独立三/四机场配置文件路径")
    parser.add_argument("--static", action="store_true", help="仅检查配置结构与三/四机场公共字段")
    args = parser.parse_args()
    if args.static:
        static_shared_checks()
        source = load_source(args.config)
        static_checks(source)
        print(f"PASS: {args.config.name} static design")
    else:
        main(args.config)
