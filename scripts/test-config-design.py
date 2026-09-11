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
import time
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
H = runpy.run_path(str(Path(__file__).with_name("test-download-policy.py")))
GENERIC, GITHUB, CF = H["GENERIC"], H["GITHUB"], H["CLOUDFLARE"]
CONFIG = Path(os.environ.get("MIHOMO_DESIGN_CONFIG", str(ROOT / "configfull_new.yaml")))
CF_HOSTS = set()
DOCKER_R2 = "docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com"
REGIONS = ("香港", "日本", "新加坡", "台湾", "美国")
BUSINESS_TEMPLATES = {
    "Highest_policy": ["AI"],
    "High_policy": ["金融", "Talkatone", "NETFLIX", "DisneyPlus", "HBO", "Primevideo", "Spotify", "Reddit"],
    "Normal_policy": ["Google", "TikTok", "哔哩东南亚", "TVB", "境外社媒", "境外电商"],
    "Cost_policy": ["Microsoft", "境外通信", "境外影音", "开发下载", "纯下载", "游戏平台", "通用代理", "Kryptex", "Speedtest"],
    "Direct_Select": ["Apple", "哔哩哔哩"],
}


def load_source(config=CONFIG):
    return json.loads(subprocess.check_output(["ruby", "-ryaml", "-rjson", "-e",
        "puts JSON.generate(YAML.load(STDIN.read, aliases: true))"], input=Path(config).read_bytes(), timeout=10))


def static_shared_checks():
    three = load_source(ROOT / "configfull_new.yaml")
    four = load_source(ROOT / "cinfigfull_new_4.yaml")
    assert set(three["proxy-providers"]) == {"Airport_01", "Airport_03", "Airport_04"}
    assert set(four["proxy-providers"]) == {"Airport_01", "Airport_02", "Airport_03", "Airport_04"}
    common = {"dns", "tun", "sniffer", "profile", "rules", "rule-providers", "unified-delay", "tcp-concurrent",
              "Fallback_Base", "Urltest_Base", "GitHub_Urltest_Base", "Cloudflare_Urltest_Base"}
    common.update(key for key in three if key.startswith(("region_", "exclude_")))
    for key in common:
        assert three[key] == four[key], key
    for provider in three["proxy-providers"]:
        assert three["proxy-providers"][provider] == four["proxy-providers"][provider], provider


class Server(H["Server"]):
    # 一个 provider 共用健康检查队列；足够 backlog 避免并行 HEAD 人为丢连接。
    request_queue_size = 128


class Handler(H["Handler"]):
    def handle(self):
        self.connection.settimeout(3)
        try:
            line = self.rfile.readline().decode().strip()
            if line.startswith("CONNECT "):
                while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                    pass
                self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                self.wfile.flush()
                line = self.rfile.readline().decode().strip()
            while line:
                method, target, _ = line.split(" ", 2)
                headers = {}
                while True:
                    header = self.rfile.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                    key, value = header.decode().split(":", 1)
                    headers[key.lower()] = value.strip()
                self.rfile.read(int(headers.get("content-length", "0")))
                path = urllib.parse.urlsplit(target).path
                host = headers.get("host", "").split(":", 1)[0]
                service = next((url for url in H["EXPECTED"] if path == urllib.parse.urlsplit(url).path), None)
                if service is None:
                    service = CF if host in CF_HOSTS else (GITHUB if host in {
                        "github.com", "release-assets.githubusercontent.com", "codeload.github.com"} else GENERIC)
                label = self.server.label
                with H["LOCK"]:
                    failed = ((service, self.server.airport) in H["FAILED"] or
                              (service, label) in H["NODE_FAILED"])
                if method == "HEAD":
                    preferred = {GENERIC: "3-JP", GITHUB: "3-US", CF: "3-JP"}[service]
                    delay = .01 if label == preferred else .15
                    if service == GITHUB and label == "3-JP2":
                        delay = .04
                    time.sleep(getattr(self.server, "probe_delays", {}).get(service, delay))
                    status, body = (503 if failed else H["EXPECTED"][service]), b""
                else:
                    status, body = (503 if failed else 200), label.encode()
                connection = "keep-alive" if method == "HEAD" else "close"
                self.wfile.write((f"HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n"
                                 f"Connection: {connection}\r\n\r\n").encode() + body)
                self.wfile.flush()
                if method != "HEAD":
                    return
                line = self.rfile.readline().decode().strip()
        except (OSError, ValueError):
            return


def static_checks(source, with_home):
    for rule in ("DOMAIN,region1.v2.argotunnel.com,real-ip", "DOMAIN,region2.v2.argotunnel.com,real-ip"):
        assert source["dns"]["fake-ip-filter"].count(rule) == 1, rule
    assert source["dns"]["nameserver-policy"]["+.argotunnel.com"] == source["dns"]["direct-nameserver"]
    assert source["profile"]["store-selected"] is True
    assert source["unified-delay"] is False
    for group in source["proxy-groups"]:
        if not group.get("hidden", False):
            assert group.get("icon", "").startswith("https://"), group["name"]
    groups = {g["name"]: {k: v for k, v in g.items() if k != "icon"}
              for g in source["proxy-groups"]}
    for name, prefix in (("机场名称1地区优先", ""), ("GitHub-机场名称1", "GitHub-"),
                         ("Cloudflare-机场名称1", "Cloudflare-")):
        assert groups[name]["proxies"] == [f"{prefix}机场名称1-{region}" for region in ("日本", "香港", "新加坡", "美国")], name
    assert len(groups) == len(source["proxy-groups"])
    assert len(groups) == (146 if with_home else 111), len(groups)
    assert all(group["type"] != "load-balance" for group in groups.values())
    outbounds = {p["name"]: p for p in source["proxies"]}
    airports = ("1", "2", "3") if with_home else ("1", "3")
    assert set(outbounds) == {
        *(f"机场名称{airport}优先-自动" for airport in airports),
        *(f"{region}·机场名称{airport}优先" for airport in airports for region in REGIONS),
    }, set(outbounds)
    assert len(outbounds) == (18 if with_home else 12)
    for name in (*groups, *outbounds, *source["sub-rules"]):
        assert "机场" not in re.sub(r"机场名称[1-4](?![0-9])", "", name), name
    known = set(groups) | set(outbounds) | {"DIRECT", "REJECT", "REJECT-DROP"}
    visible = {name for name, g in groups.items() if not g.get("hidden", False)}
    assert visible == {name for names in BUSINESS_TEMPLATES.values() for name in names} | {
        "台湾限定", "Emby", "隐私拦截", "GLOBAL", "Cloudflare Tunnel", "自建/家宽节点"}, visible
    assert len(visible) == 32
    for name, group in groups.items():
        if group["type"] == "select":
            assert len(group.get("proxies", [])) == len(set(group.get("proxies", []))), name
        assert set(group.get("proxies", [])) <= known, name
        assert set(group.get("use", [])) <= set(source["proxy-providers"]), name
        if re.fullmatch(r"(?:机场名称|GitHub-机场名称|Cloudflare-机场名称)[123]-(?:香港|日本|新加坡|美国|台湾)", name):
            assert (group["type"], group["tolerance"]) == ("url-test", 50), name
        if name.startswith("Cloudflare-"):
            assert group["url"] == source["Cloudflare_Urltest_Base"]["url"], name
            assert group["expected-status"] == 204, name
            assert all(p.startswith("Cloudflare-") for p in group.get("proxies", [])), name
    # Every rematch must terminate in an automatic pool; reject missing targets/cycles.
    assert len(outbounds) == len(source["proxies"])
    def dialable(name, ancestors=()):
        assert name not in ancestors, (name, ancestors)
        assert name not in outbounds, name
        for child in groups.get(name, {}).get("proxies", []):
            dialable(child, (*ancestors, name))
    dialable("GLOBAL")
    assert groups["GLOBAL"]["proxies"][:2] == ["机场名称3优先", "机场名称1优先"]
    assert set(groups["GLOBAL"]["proxies"]) == {
        "机场名称3优先", "机场名称1优先", "DIRECT", "自建/家宽节点",
        *(region + "-成本优先" for region in ("香港", "日本", "新加坡", "台湾", "美国")),
    }
    assert groups["自建/家宽节点"] == {"name": "自建/家宽节点", "type": "select",
        "use": source["use_ap_all"], "filter": source["home_only"], "empty-fallback": "REJECT"}
    assert groups["隐私拦截"]["proxies"] == ["REJECT", "REJECT-DROP", "DIRECT", "通用代理"]
    tunnel = groups["Cloudflare Tunnel"]
    assert tunnel == {"name": "Cloudflare Tunnel", **source["Direct_Select"]}
    referenced = set()
    for outbound in outbounds.values():
        assert outbound["type"] == "rematch"
        target = outbound["target-sub-rule"]
        assert target in source["sub-rules"], target
        referenced.add(target)
    assert referenced == set(source["sub-rules"])
    assert referenced == {
        *(f"机场名称{airport}自动" for airport in airports),
        *(f"机场名称{airport}-{region}" for airport in airports for region in REGIONS),
    }, referenced
    for airport, target in (("1", "纯下载-机场名称1优先"), ("3", "纯下载-自动")):
        rules = source["sub-rules"][f"机场名称{airport}自动"]
        assert outbounds[f"机场名称{airport}优先-自动"]["target-sub-rule"] == f"机场名称{airport}自动"
        assert rules[1] == "RULE-SET,pure_download_domain," + target
        assert rules[2] == "OR,((RULE-SET,github_domain),(RULE-SET,gitbook_domain))," + (
            "GitHub-机场名称1优先" if airport == "1" else "GitHub-自动")
    for rules in source["sub-rules"].values():
        assert rules[-1].startswith("MATCH,")
        for rule in rules:
            target = rule.rsplit(",", 1)[-1]
            assert target in groups and groups[target]["type"] != "select", rule
            dialable(target)
    assert groups["AI"]["type"] == "select" and groups["AI"]["use"] == source["use_ap_all"]
    ai_choices = ["AI-机场名称1-日本", *source["Normal_policy"]["proxies"]]
    if with_home:
        ai_choices.insert(2, "机场名称2优先-自动")
    assert groups["AI"]["proxies"] == ai_choices
    assert groups["AI-机场名称1-日本"]["type"] == "select"
    assert groups["AI-机场名称1-日本"]["use"] == ["Airport_01"]
    dialable("AI-机场名称1-日本")
    assert groups["AI-机场名称1-日本"]["filter"] == source["region_jp"]
    for policy, businesses in BUSINESS_TEMPLATES.items():
        for business in businesses:
            assert groups[business] == {"name": business, **source[policy]}, business
    for policy, preference, order in (
        ("High_policy", "2" if with_home else "1", ("2", "1", "3") if with_home else ("1", "3")),
        ("Normal_policy", "1", ("1", "3")),
        ("Cost_policy", "3", ("3", "1")),
    ):
        assert source[policy]["proxies"] == [
            *(f"机场名称{airport}优先-自动" for airport in order),
            "自建/家宽节点",
            *(f"{region}·机场名称{preference}优先" for region in REGIONS), "DIRECT",
        ], policy
    if not with_home:
        assert source["High_policy"] == source["Normal_policy"]
    assert groups["台湾限定"]["proxies"] == ["台湾·机场名称1优先"]
    assert source["Direct_Select"]["proxies"] == ["DIRECT", *source["Cost_policy"]["proxies"][:-1]]
    assert groups["Emby"]["proxies"] == ["低倍率/MITM节点", *source["Cost_policy"]["proxies"]]
    # 聚合改变业务入口，不能只检验菜单而遗漏实际规则去向。
    provider_businesses = {
        "Google": ["google_domain", "googlevpn_domain", "fcm_domain"],
        "Microsoft": ["microsoft_domain", "onedrive_domain"],
        "境外通信": ["telegram_domain", "telegram_ip", "line_domain", "discord_domain", "signal_domain", "communication_domain"],
        "境外影音": ["youtube_domain", "appleTV_domain", "twitch_domain", "porn_domain"],
        "开发下载": ["github_domain", "gitbook_domain", "dev_download_domain"],
        "纯下载": ["pure_download_domain"],
        "游戏平台": ["steam_domain", "Epic_domain", "EA_domain", "Blizzard_domain", "UBI_domain", "Sony_domain", "Nintendo_domain"],
        "境外社媒": ["meta_domain", "facebook_ip", "social_media_non_cn_domain", "twitter_ip"],
        "TVB": ["TVB_domain"], "Reddit": ["reddit_domain"],
        "NETFLIX": ["netflix_domain", "netflix_ip"], "DisneyPlus": ["disney_domain"],
        "HBO": ["hbo_domain"], "Primevideo": ["primevideo_domain"], "Spotify": ["spotify_domain"],
    }
    rule_targets = {parts[1]: parts[2] for rule in source["rules"]
                    if (parts := rule.split(","))[0] == "RULE-SET"}
    for business, providers in provider_businesses.items():
        for provider in providers:
            assert rule_targets[provider] == business, (provider, rule_targets[provider])
    for predicate, business in {
        "DOMAIN-SUFFIX,mytv.com.hk": "TVB",
        "DOMAIN-SUFFIX,huggingface.co": "开发下载",
        "DOMAIN-SUFFIX,hf.co": "开发下载",
        "DOMAIN-SUFFIX,docker.io": "开发下载",
        "DOMAIN," + DOCKER_R2: "开发下载",
    }.items():
        assert predicate + "," + business in source["rules"], predicate
    assert set(source["rule-providers"]["pure_download_domain"]["payload"]) == {
        "codeload.github.com", "release-assets.githubusercontent.com"}
    assert source["Direct_Select"]["proxies"][0] == "DIRECT"
    assert not {"高要求", "普通业务", "成本优先", "PayPal", "GitHub", "Cloudflare", "日本节点", "欧洲节点",
                "日常服务", "流媒体", "直连业务", "GoogleVPN", "FCM", "OneDrive", "YouTube", "AppleTV",
                "Telegram", "LINE", "Discord", "Signal", "Meta", "HuggingFace", "Docker", "STEAM"} & groups.keys()
    # 每个地区选项无共享 select 状态；只收窄地区，保持所属层机场顺序。
    for region in REGIONS:
        for airport in airports:
            assert outbounds[f"{region}·机场名称{airport}优先"]["target-sub-rule"] == f"机场名称{airport}-{region}"
        for family in ("", "Cloudflare-", "GitHub-"):
            cost = groups[family + region + "-成本优先"]
            if region == "台湾" and family:
                assert cost["use"] == [f"Airport_0{n}" for n in ([3, 1, 2, 4] if with_home else [3, 1, 4])]
            else:
                prefix = family + "机场名称"
                assert cost["proxies"] == [prefix + f"{n}-{region}" for n in ([3, 1, 2] if with_home else [3, 1])]
            if with_home:
                high = groups[family + region + "-高要求"]
                if region == "台湾" and family:
                    assert high["use"] == [f"Airport_0{n}" for n in [2, 1, 3, 4]]
                else:
                    prefix = family + "机场名称"
                    assert high["proxies"] == [prefix + f"{n}-{region}" for n in [2, 1, 3]]
    home = ["Airport_02"] if with_home else []
    assert set(source["proxy-providers"]) == {"Airport_01", "Airport_03", "Airport_04", *home}
    if not with_home:
        assert "Airport_02" not in json.dumps(source, ensure_ascii=False)
    assert source["sub-rules"]["机场名称1自动"][-1] == "MATCH,机场名称1优先"
    assert source["sub-rules"]["机场名称3自动"][-1] == "MATCH,机场名称3优先"
    assert groups["机场名称1优先"]["proxies"] == [f"机场名称{n}地区优先" for n in ([1, 2, 3, 4] if with_home else [1, 3, 4])]
    assert groups["机场名称3优先"]["proxies"] == [f"机场名称{n}地区优先" for n in ([3, 1, 2, 4] if with_home else [3, 1, 4])]
    if with_home:
        assert source["sub-rules"]["机场名称2自动"][-1] == "MATCH,家宽优先"
        assert outbounds["机场名称2优先-自动"]["target-sub-rule"] == "机场名称2自动"
        for prefix in ("Cloudflare-", "GitHub-"):
            assert groups[prefix + "家宽优先"]["proxies"] == [prefix + f"机场名称{n}" for n in [2, 1, 3, 4]]


def main(config=CONFIG):
    source = load_source(config)
    with_home = "Airport_02" in source["proxy-providers"]
    static_checks(source, with_home)
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
            # 同一目标端口的第二个回环地址，单独模拟 cn_ip 命中，不污染其他域名。
            direct_ip = Server(("127.0.0.2", by_label["DIRECT"].server_address[1]), Handler)
            direct_ip.label, direct_ip.airport = "DIRECT", "direct"
            threading.Thread(target=direct_ip.serve_forever, daemon=True).start()
            servers.append(direct_ip)
            providers = {}
            for name, proxies in nodes.items():
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps({"proxies": proxies}))
                providers[name] = {"type": "file", "path": str(path), "health-check": {
                    "enable": True, "url": GENERIC, "expected-status": 204, "timeout": 3500, "interval": 1, "lazy": False}}
            rules = {name: {"type": "inline", "behavior": value["behavior"], "payload": value.get("payload", [])}
                     for name, value in source["rule-providers"].items()}
            membership = {
                "github_domain": ["+.github.com", "+.githubusercontent.com", "wise.gh.invalid", "tv.gh.invalid"], "google_domain": ["+.google.com", "google.cf.invalid", "youtube.cf.invalid"],
                "youtube_domain": ["+.youtube.com", "youtube.cf.invalid"], "bahamut_domain": ["+.gamer.com.tw", "bahamut.cf.invalid"],
                "fcm_domain": ["fcm.cf.invalid"], "googlevpn_domain": ["googlevpn.cf.invalid"],
                "dev_download_domain": ["+.ghcr.io", "+.unpkg.com", "nodejs.org", "+.jsdelivr.net", "+.blob.core.windows.net"],
                "Wise_domain": ["wise.cf.invalid", "wise.invalid", "wise.gh.invalid"], "paypal_domain": ["paypal.cf.invalid", "paypal.invalid"],
                "finance_domain": ["finance.cf.invalid", "youtube.cf.invalid"], "talkatone_domain": ["talk.cf.invalid"],
                "talkatone_ip": ["127.0.0.3/32"],
                "meta_domain": ["meta.cf.invalid"], "microsoft_domain": ["microsoft.com", "ms.cf.invalid", "onedrive.cf.invalid"],
                "onedrive_domain": ["onedrive.cf.invalid"], "appleTV_domain": ["tv.cf.invalid", "tv.gh.invalid"],
                "netflix_domain": ["netflix.com", "netflix.cf.invalid"],
                "disney_domain": ["disneyplus.com", "disney.cf.invalid"],
                "reddit_domain": ["reddit.com", "reddit.cf.invalid"],
                "social_media_non_cn_domain": ["social.cf.invalid", "reddit.cf.invalid"], "TVB_domain": ["tvb.cf.invalid"],
                "telegram_domain": ["telegram.cf.invalid"], "line_domain": ["line.cf.invalid"],
                "signal_domain": ["signal.cf.invalid"], "communication_domain": ["communication.cf.invalid"],
                "steam_domain": ["steam.cf.invalid"], "Epic_domain": ["epic.cf.invalid"],
                "biliintl_domain": ["bili.cf.invalid"],
                "discord_domain": ["+.discord.com"], "xiaomi_domain": ["+.mi.com"],
                "ai!cn_domain": ["ai.cf.invalid", "cdn.huggingface.co"],
                "banAd_core_domain": ["blocked.cf.invalid", "wise.cf.invalid"],
                "direct_domain": ["direct.cf.invalid"],
                "cn_domain": ["cn.cf.invalid", "tv.cf.invalid", "proxy.cf.invalid"],
                "proxy_domain": ["proxy.cf.invalid"], "cn_ip": ["127.0.0.2/32"],
            }
            cf_synthetic = {value for entries in membership.values() for value in entries if value.endswith(".cf.invalid")}
            membership["cloudflare_domain"] = ["+.cloudflare.com", "+.pages.dev", "+.workers.dev",
                "+.r2.cloudflarestorage.com", "+.trycloudflare.com", "cdn.huggingface.co", "test.kuapt.top",
                "cn-ip.cf.invalid", "foreign-ip.cf.invalid", *sorted(cf_synthetic)]
            for name, payload in membership.items():
                rules[name]["payload"] = payload
            cf_known = ["cloudflare.com", "example.pages.dev", "example.workers.dev",
                DOCKER_R2,
                "dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com", "unpkg.com", "esm.unpkg.com",
                "cdnjs.com", "api.cdnjs.com", "nodejs.org", "linux.do", "cdn.linux.do", "connect.linux.do", "cdn.huggingface.co"]
            CF_HOSTS.update(cf_known + list(cf_synthetic) + ["test.kuapt.top", "discord.com", "demo.trycloudflare.com",
                                                          "cn-ip.cf.invalid", "foreign-ip.cf.invalid"])
            normal_hosts = ["github.com", "release-assets.githubusercontent.com", "codeload.github.com", "google.com",
                            "youtube.com", "ghcr.io", "gamer.com.tw", "cdn.jsdelivr.net", "unknown.linux.do",
                            "unknown.nodejs.org", "wise.invalid", "paypal.invalid", "api.discord.com",
                            "hk.tv.global.mi.com", "www.mi.com", "origin-tracker.githubusercontent.com",
                            "copilotprodattachments.blob.core.windows.net", "openaiassets.blob.core.windows.net", "wise.gh.invalid", "tv.gh.invalid",
                            "registry-1.docker.io", "netflix.com", "disneyplus.com", "microsoft.com", "reddit.com", "mytv.com.hk"]
            mixed, control = H["free_port"](), H["free_port"]()
            runtime_config = Path(directory) / "config.json"
            runtime_config.write_text(json.dumps({"mixed-port": mixed, "external-controller": f"127.0.0.1:{control}",
                "bind-address": "127.0.0.1", "allow-lan": False, "log-level": "silent", "dns": {"enable": False},
                "tun": {"enable": False}, "unified-delay": source["unified-delay"],
                "profile": {"store-selected": False, "store-fake-ip": False}, "proxy-providers": providers,
                "proxies": source["proxies"], "proxy-groups": groups, "rule-providers": rules, "rules": source["rules"], "sub-rules": source["sub-rules"],
                "hosts": {**dict.fromkeys(CF_HOSTS | set(normal_hosts), "127.0.0.1"),
                          "cn-ip.cf.invalid": "127.0.0.2"}}, ensure_ascii=False))
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
            for business in ("Microsoft", "境外通信"):
                assert group(business)["now"] == "机场名称3优先-自动", business
            for host in ("microsoft.com", "ms.cf.invalid", "onedrive.cf.invalid", "telegram.cf.invalid",
                         "line.cf.invalid", "discord.com", "api.discord.com", "signal.cf.invalid", "communication.cf.invalid"):
                expect(host, "3-JP")
            primary_nodes = api("/providers/proxies")["providers"]["Airport_01"]["proxies"]
            assert all(CF in node.get("extra", {}) for node in primary_nodes)
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
            recover()
            expect("github.com", "3-JP2")
            checks.append("机场名称4按顺序耗尽同区备用再换地区")

            choose("开发下载", "[机场名称4]德国备用")
            for host in ["github.com", "unpkg.com", "openaiassets.blob.core.windows.net"]:
                expect(host, "4-DE")
            for host in ["codeload.github.com", "release-assets.githubusercontent.com"]:
                expect(host, "3-US")
            expect("cloudflare.com", "3-JP")
            expect("youtube.com", "3-JP")
            expect(DOCKER_R2, "4-DE")
            expect("registry-1.docker.io", "4-DE")
            choose("开发下载", "[机场名称1]HongKong 01")
            for host in ["github.com", "unpkg.com", "cdn.huggingface.co", DOCKER_R2, "registry-1.docker.io"]:
                expect(host, "1-steady")
            expect("codeload.github.com", "3-US")
            choose("开发下载", "[机场名称4]德国备用")
            choose("纯下载", "[机场名称1]日本01")
            for host in ["codeload.github.com", "release-assets.githubusercontent.com"]:
                expect(host, "1-jp")
            expect("github.com", "4-DE")
            expect(DOCKER_R2, "4-DE")
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
            checks.append("开发下载统一控制GitHub/HF/Docker及CF请求；纯下载双向独立，其机场名称1跨区择优不扩大到普通GitHub")
            choose("通用代理", "[机场名称4]德国备用")
            for business in ("开发下载", "境外影音", "游戏平台"):
                choose(business, "[机场名称4]德国备用")
            for business in ("Google", "境外社媒", "Microsoft", "境外通信"):
                choose(business, "[机场名称1]日本01")
            choose("哔哩东南亚", "[机场名称4]日本备用02")
            choose("TVB", "[机场名称1]HongKong 01")
            choose("金融", "[机场名称3]美国01|0.1x")
            choose("Talkatone", "[机场名称1]HongKong 01")
            for host in cf_known + ["youtube.cf.invalid", "tv.cf.invalid", "tv.gh.invalid", "steam.cf.invalid", "epic.cf.invalid", "proxy.cf.invalid", "foreign-ip.cf.invalid"]:
                expect(host, "4-DE")
            for host in ["google.cf.invalid", "fcm.cf.invalid", "googlevpn.cf.invalid", "meta.cf.invalid", "social.cf.invalid",
                         "ms.cf.invalid", "onedrive.cf.invalid", "discord.com", "api.discord.com", "telegram.cf.invalid",
                         "line.cf.invalid", "signal.cf.invalid", "google.com"]:
                expect(host, "1-jp")
            expect("bili.cf.invalid", "4-JP-B")
            for host in ["mytv.com.hk", "tvb.cf.invalid"]:
                expect(host, "1-steady")
            for host in ["wise.cf.invalid", "finance.cf.invalid", "wise.invalid", "wise.gh.invalid", "paypal.cf.invalid", "paypal.invalid"]:
                expect(host, "3-US")
            for host in ["talk.cf.invalid", "127.0.0.3"]:
                expect(host, "1-steady")
            for host in ["ai.cf.invalid", "origin-tracker.githubusercontent.com", "copilotprodattachments.blob.core.windows.net"]:
                expect(host, "1-jp")
            assert request("bahamut.cf.invalid")[0] != 0
            checks.append("聚合入口统一手选：厂商/通信/影音/游戏各自控制成员，CF/GH身份不改变业务；TVB和哔哩东南亚独立")

            for host in ["direct.cf.invalid", "test.kuapt.top", "cn.cf.invalid", "cn-ip.cf.invalid", "demo.trycloudflare.com", "www.mi.com"]:
                expect(host, "DIRECT")
            expect("hk.tv.global.mi.com", "4-DE")
            assert request("blocked.cf.invalid")[0] != 0
            checks.append("明确直连、CN域名/IP优先；具体跨区和人工代理例外保留")
            choose("隐私拦截", "通用代理")
            expect("blocked.cf.invalid", "4-DE")
            choose("通用代理", "机场名称3优先-自动")
            expect("blocked.cf.invalid", "3-JP")
            expect("direct.cf.invalid", "DIRECT")
            choose("通用代理", "[机场名称4]德国备用")
            choose("隐私拦截", "REJECT")
            assert request("blocked.cf.invalid")[0] != 0
            checks.append("误杀代理放行遵守通用代理手选与CF自动链，可切回拦截且不覆盖明确直连")
            choose("开发下载", "DIRECT")
            for host in ["unpkg.com", "github.com", DOCKER_R2, "registry-1.docker.io"]:
                expect(host, "DIRECT")
            expect("codeload.github.com", "3-US")
            expect("youtube.com", "4-DE")
            defaults = {business: source[template]["proxies"][0]
                        for template, businesses in BUSINESS_TEMPLATES.items() if template != "Highest_policy"
                        for business in businesses}
            for business, default in defaults.items():
                choose(business, default)
            for host in ["wise.cf.invalid", "paypal.cf.invalid", "wise.invalid", "paypal.invalid", "wise.gh.invalid"]:
                expect(host, "2-HK" if with_home else "1-jp")
            expect("google.cf.invalid", "1-jp")
            if with_home:
                fail(CF, airports=["2"])
                expect("wise.cf.invalid", "1-jp")
                fail(GENERIC, airports=["2"])
                expect("wise.invalid", "1-jp")
                recover()
                expect("wise.cf.invalid", "2-HK")
            checks.append("默认政策可复用：金融和Talkatone用高要求，PayPal不再保留品牌专用日本默认")

            # 相同高要求政策下，地区和具体节点选择仍属于各个产品。
            choose("NETFLIX", "日本·" + high_preference)
            choose("DisneyPlus", "美国·" + high_preference)
            for host in ("netflix.com", "netflix.cf.invalid"):
                expect(host, "2-JP" if with_home else "1-jp")
            for host in ("disneyplus.com", "disney.cf.invalid"):
                expect(host, "3-US")
            choose("DisneyPlus", "香港·" + high_preference)
            for host in ("disneyplus.com", "disney.cf.invalid"):
                expect(host, "2-HK" if with_home else "1-fast")
            for host in ("netflix.com", "netflix.cf.invalid"):
                expect(host, "2-JP" if with_home else "1-jp")
            choose("NETFLIX", "[机场名称4]德国备用")
            for host in ("netflix.com", "netflix.cf.invalid"):
                expect(host, "4-DE")
            for host in ("disneyplus.com", "disney.cf.invalid"):
                expect(host, "2-HK" if with_home else "1-fast")
            choose("DisneyPlus", "[机场名称1]HongKong 01")
            for host in ("disneyplus.com", "disney.cf.invalid"):
                expect(host, "1-steady")
            for host in ("netflix.com", "netflix.cf.invalid"):
                expect(host, "4-DE")
            choose("NETFLIX", high_preference + "-自动")
            choose("DisneyPlus", high_preference + "-自动")
            checks.append("Netflix/Disney共用高要求政策与池，普通和CF请求均服从各自地区/节点选择，双向切换不联动")

            choose("Reddit", "日本·" + high_preference)
            choose("境外社媒", "香港·机场名称1优先")
            for host in ("reddit.com", "reddit.cf.invalid"):
                expect(host, "2-JP" if with_home else "1-jp")
            for host in ("meta.cf.invalid", "social.cf.invalid"):
                expect(host, "1-fast")
            choose("Reddit", "[机场名称4]德国备用")
            for host in ("reddit.com", "reddit.cf.invalid"):
                expect(host, "4-DE")
            for host in ("meta.cf.invalid", "social.cf.invalid"):
                expect(host, "1-fast")
            choose("境外社媒", "[机场名称1]日本01")
            for host in ("meta.cf.invalid", "social.cf.invalid"):
                expect(host, "1-jp")
            for host in ("reddit.com", "reddit.cf.invalid"):
                expect(host, "4-DE")
            choose("Reddit", high_preference + "-自动")
            choose("境外社媒", "机场名称1优先-自动")
            checks.append("Reddit高要求与普通社媒双向独立；重叠社媒集合中的CF请求仍先归Reddit")

            choose("Google", "日本·机场名称1优先")
            choose("Microsoft", "日本·机场名称3优先")
            for host in ("google.com", "google.cf.invalid"):
                expect(host, "1-jp")
            for host in ("microsoft.com", "ms.cf.invalid", "onedrive.cf.invalid"):
                expect(host, "3-JP")
            choose("Google", "[机场名称4]德国备用")
            for host in ("google.com", "google.cf.invalid"):
                expect(host, "4-DE")
            for host in ("microsoft.com", "ms.cf.invalid", "onedrive.cf.invalid"):
                expect(host, "3-JP")
            choose("Microsoft", "[机场名称3]美国01|0.1x")
            for host in ("microsoft.com", "ms.cf.invalid", "onedrive.cf.invalid"):
                expect(host, "3-US")
            for host in ("google.com", "google.cf.invalid"):
                expect(host, "4-DE")
            choose("境外通信", "日本·机场名称3优先")
            for host in ("telegram.cf.invalid", "line.cf.invalid", "discord.com", "api.discord.com",
                         "signal.cf.invalid", "communication.cf.invalid"):
                expect(host, "3-JP")
            expect("microsoft.com", "3-US")
            expect("google.com", "4-DE")
            choose("Google", "机场名称1优先-自动")
            choose("Microsoft", "机场名称3优先-自动")
            choose("境外通信", "机场名称3优先-自动")
            checks.append("Microsoft含OneDrive、通信聚合均默认成本；日本成本地区与手选独立于Google普通政策，通用与CF请求共同受控")

            choose("开发下载", "机场名称1优先-自动")
            fail(CF, labels=["1-jp"])
            expect("unpkg.com", "1-fast")
            expect("github.com", "1-jp")
            expect("youtube.com", "3-JP")
            recover()
            choose("开发下载", "机场名称3优先-自动")
            expect("unpkg.com", "3-JP")
            expect(DOCKER_R2, "3-JP")
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

            fail(CF, airports=["1", "2"])
            expect("google.cf.invalid", "3-JP")
            expect("wise.cf.invalid", "3-JP")
            assert request("ai.cf.invalid")[0] != 0
            assert group("AI")["now"] == "AI-机场名称1-日本"
            assert group("AI-机场名称1-日本")["now"] == "[机场名称1]日本01"
            recover()
            expect("ai.cf.invalid", "1-jp")
            checks.append("最高要求通过AI业务独立执行；已选机场名称1节点失败不自动换路")

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
            expect("tv.cf.invalid", "3-JP")
            expect("talk.cf.invalid", "2-HK" if with_home else "1-jp")
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
            choose("金融", "[机场名称4]日本备用02")
            for host in ["wise.invalid", "wise.gh.invalid", "paypal.cf.invalid"]:
                expect(host, "4-JP-B")
            expect("google.com", "1-jp")
            expect("github.com", "3-JP2")
            for business, default in defaults.items():
                choose(business, default)
            checks.append("金融从地区自动改具体节点不影响同级Talkatone或其他业务；无共享地区手选状态")

            api("/configs", {"mode": "global"}, "PATCH")
            expect("google.com", "3-JP")
            for region, label in [("香港", "1-fast"), ("新加坡", "3-SG"), ("美国", "3-US")]:
                choose("GLOBAL", region + "-成本优先")
                expect("google.com", label)
            choose("GLOBAL", "台湾-成本优先")
            assert request("google.com")[0] != 0
            choose("GLOBAL", "日本-成本优先")
            expect("google.com", "3-JP")
            expect("unpkg.com", "3-JP")
            fail(GENERIC, labels=["3-JP", "3-JP2"])
            expect("google.com", "1-jp")
            fail(GENERIC, labels=["1-jp"])
            expect("google.com", "2-JP" if with_home else "4-JP-A")
            if with_home:
                fail(GENERIC, labels=["2-JP"])
            expect("google.com", "4-JP-A")
            fail(GENERIC, labels=["4-JP-A", "4-JP-B"])
            assert request("google.com")[0] != 0
            recover()
            expect("google.com", "3-JP")
            checks.append("GLOBAL五个地区链可直接拨号；日本按成本顺序回退，空地区和同区耗尽均不越区")
            choose("GLOBAL", "[机场名称4]德国备用")
            expect("google.com", "4-DE")
            expect("unpkg.com", "4-DE")
            api("/configs", {"mode": "rule"}, "PATCH")
            expect("google.com", "1-jp")
            checks.append("GLOBAL直接拨号；切回规则模式恢复业务与探针分流")

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
        static_checks(source, "Airport_02" in source["proxy-providers"])
        print(f"PASS: {args.config.name} static design")
    else:
        main(args.config)
