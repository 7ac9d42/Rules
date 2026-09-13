#!/usr/bin/env python3
"""通过官方核心验证原始订阅名、provider 前缀和节点准入；仅使用回环地址。"""

import copy
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
H = runpy.run_path(str(Path(__file__).with_name("proxy-fixture.py")))
SOURCE = json.loads(subprocess.check_output(["ruby", "-ryaml", "-rjson", "-e",
    "puts JSON.generate(YAML.load_file(ARGV[0], aliases: true))",
    os.environ.get("MIHOMO_DESIGN_CONFIG", str(ROOT / "configfull_new.yaml"))], timeout=10))


def main():
    # 每行显式声明业务上允许进入的池，不能用配置自己的正则计算预期。
    examples = {
        "Airport_01": [
            ("HongKong 01", {"hk1", "download1"}),
            ("HongKong 02", set()), ("HongKong 03", set()),
            ("HongKong 04", set()), ("HongKong 05", set()),
            ("Hong Kong 06", {"hk1", "download1"}),
            ("香港 0.3x", set()), ("香港 0.5x", {"hk1", "download1"}),
            ("香港 5x", set()), ("香港 BETA", set()),
            ("日本 MITM 1x", {"jp1"}), ("美国 0.1x", set()),
            ("HK01", {"hk1", "download1"}), ("JP01", {"jp1", "download1"}),
            ("HK-06", {"hk1", "download1"}), ("JP-01", {"jp1", "download1"}),
            ("XHK01", set()), ("JP01test", set()),
        ],
        "Airport_03": [
            ("CTCU|日本01", set()), ("日本02|CTCU|0.5x", set()),
            ("日本03|BGP|CTCU", set()),
            ("日本06 CTCU 1x", set()), ("日本07-CTCU-1x", set()),
            ("新加坡05【CTCU】1x", set()), ("新加坡06_CTCU_1x", set()),
            ("CTCUCM|日本04", {"jp3", "download3"}),
            ("日本05|CTCUCM", {"jp3", "download3"}),
            ("JP01 CTCUCM 1x", {"jp3", "download3"}),
            ("SG01 CTCUCM 1x", {"sg3", "download3"}),
            ("US01 CTCU 0.1x", {"us3", "download3"}),
            ("USA01 0.1x", {"us3", "download3"}),
            ("RUS01", set()), ("US01test", set()),
            ("CTCU|新加坡01", set()), ("新加坡02|CTCU|1x", set()),
            ("新加坡03|BGP|CTCU", set()),
            ("新加坡04|CTCUCM", {"sg3", "download3"}),
            ("CTCU|美国01|0.1x", {"us3", "download3"}),
            ("美国02|CTCU|0.1x", {"us3", "download3"}),
            ("美国 0.1x", {"us3", "download3"}),
            ("美国 BETA", set()), ("美国 wcloud", set()), ("美国 traffic", set()),
            ("美国 5x", set()), ("美国 5.5倍", set()), ("美国 10x", set()),
            ("美国 4.9x", {"us3", "download3"}),
            ("日本 0.3x", set()), ("日本 0.5x", {"jp3", "download3"}),
            ("日本 5x", set()), ("日本 BETA", set()),
            ("香港 0.1x", set()), ("德国普通", set()),
        ],
        "Airport_04": [
            ("德国备用", set()), ("德国家宽", {"home"}), ("日本自建", {"home"}),
            ("日本 CF 优化", set()), ("日本 CFILT", set()), ("香港 HKT", set()),
            ("美国 ATT", set()), ("日本 homework", set()), ("日本 privatecloud", set()),
            ("日本 home", {"home"}), ("日本 [private]", {"home"}),
            ("The_house 日本", {"home"}), ("日本 Self_Back", {"home"}),
            ("TW01", {"tw4"}), ("TWN01", {"tw4"}), ("TPE01", {"tw4"}),
            ("XTW01", set()), ("TW01test", set()),
        ],
    }
    if "Airport_02" in SOURCE["proxy-providers"]:
        examples["Airport_02"] = [("香港家宽 1x", {"hk2", "home"}), ("日本家宽 1x", {"jp2", "home"}),
                                  ("香港家宽 BETA", {"home"}), ("日本家宽 0.3x", {"home"}),
                                  ("HK01", {"hk2", "home"}), ("JP01", {"jp2", "home"}),
                                  ("德国01", {"home"})]
    notices = ["剩余流量: 100 GB", "套餐到期: 2027-01-01", "Email: support@example.invalid", "Expired"]
    core = None
    with tempfile.TemporaryDirectory(prefix="mihomo-node-filters-") as directory:
        try:
            providers, expected, manual, udp_capabilities = {}, {}, set(), {}
            for name, cases in examples.items():
                provider = copy.deepcopy(SOURCE["proxy-providers"][name])
                prefix = provider["override"]["additional-prefix"]
                suffix = provider["override"].get("additional-suffix", "")
                for raw_name, memberships in cases:
                    manual.add(prefix + raw_name + suffix)
                    for membership in memberships:
                        expected.setdefault(membership, set()).add(prefix + raw_name + suffix)
                path = Path(directory) / f"{name}.json"
                udp_capabilities.update({prefix + raw_name + suffix: bool(i % 2)
                                         for i, (raw_name, _) in enumerate(cases)})
                path.write_text(json.dumps({"proxies": [
                    {"name": raw_name, "type": "socks5", "server": "127.0.0.1", "port": 9,
                     "udp": bool(i % 2)}
                    for i, raw_name in enumerate([entry[0] for entry in cases] + notices)]}))
                provider.pop("url", None)
                provider.update(type="file", path=str(path), **{"health-check": {"enable": False}})
                providers[name] = provider
            subjects = {"纯下载-机场名称1": "download1", "纯下载-机场名称3": "download3",
                        "开发下载": "manual", "自建/家宽节点": "home", "台湾限定": "tw4"}
            for family in ("机场名称", "GitHub-机场名称", "Cloudflare-机场名称"):
                subjects.update({f"{family}1-香港": "hk1", f"{family}1-日本": "jp1", f"{family}3-日本": "jp3",
                                 f"{family}3-新加坡": "sg3", f"{family}3-美国": "us3"})
            if "Airport_02" in examples:
                for family in ("机场名称", "GitHub-机场名称", "Cloudflare-机场名称"):
                    subjects.update({f"{family}2-香港": "hk2", f"{family}2-日本": "jp2"})
            groups = [copy.deepcopy(group) for group in SOURCE["proxy-groups"] if group["name"] in subjects]
            assert len(groups) == len(subjects)
            for group in groups:
                if group["name"] in ("开发下载", "台湾限定"):
                    group.pop("proxies")  # 本测试仅核对入口的原始订阅候选。
                group.update(url="http://probe.invalid/204", interval=3600, lazy=True)
            control = H["free_port"]()
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"external-controller": f"127.0.0.1:{control}", "log-level": "silent",
                "dns": {"enable": False}, "tun": {"enable": False}, "profile": {"store-selected": False},
                "proxy-providers": providers, "proxy-groups": groups, "rules": ["MATCH,REJECT"]}, ensure_ascii=False))
            validation = subprocess.run([H["MIHOMO"], "-t", "-d", directory, "-f", str(config)],
                                        capture_output=True, text=True, timeout=10)
            assert validation.returncode == 0, validation.stdout + validation.stderr
            core = subprocess.Popen([H["MIHOMO"], "-d", directory, "-f", str(config)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def snapshot():
                with opener.open(f"http://127.0.0.1:{control}/proxies", timeout=2) as response:
                    value = json.load(response)["proxies"]
                    return value if all(name in value for name in subjects) else None

            actual = H["until"](snapshot)
            failures = []
            with opener.open(f"http://127.0.0.1:{control}/providers/proxies", timeout=2) as response:
                actual_nodes = {node["name"]: node for provider in json.load(response)["providers"].values()
                                for node in provider["proxies"]}
            for name, supported in udp_capabilities.items():
                if actual_nodes[name]["udp"] != supported:
                    failures.append({"node": name, "expected_udp": supported,
                                     "actual_udp": actual_nodes[name]["udp"]})
            for name, membership in subjects.items():
                want = manual if membership == "manual" else expected[membership]
                members = set(actual[name]["all"])
                if members != want:
                    failures.append({"group": name, "unexpected": sorted(members - want), "missing": sorted(want - members)})
            print(json.dumps({"passed": not failures, "groups": len(subjects), "raw_nodes": len(manual),
                "checks": ["provider 原始公告先过滤、显示前后缀后添加", "英文地区码支持数字编号并拒绝字母子串",
                           "CTCU 支持竖线、空格、连字符和括号分隔，保留 CTCUCM",
                           "美国保留低倍率/CTCU，排除 BETA/wcloud/traffic/高倍率", "香港质量及倍率/BETA/MITM 下载边界",
                           "机场2统一家宽标签，其余机场仅认明确标签；排除 CF/运营商和英文子串", "全量手选保留问题节点",
                           "订阅 UDP 能力声明保留，TCP-only 节点仍可入池和手选"],
                "failures": failures}, ensure_ascii=False, indent=2))
            assert not failures, "官方核心候选与准入政策不一致"
        finally:
            if core is not None:
                core.terminate()
                try:
                    core.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    core.kill()
                    core.wait(timeout=5)


def interrupted(signum, frame):
    raise InterruptedError("节点过滤验证被中止")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    main()
