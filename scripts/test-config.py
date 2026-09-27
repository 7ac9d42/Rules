#!/usr/bin/env python3
"""配置回归：static=四配置基础；smoke=再查关键分流；full=再查三机场候选必要运行行为。"""
import argparse
import concurrent.futures
import copy
from contextlib import ExitStack
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import socketserver
import subprocess
import tempfile
import urllib.error
import urllib.parse

import mihomo_fixture as F

ROOT = F.ROOT
CONFIGS = ('configfull_new.yaml.bak', 'configfull_new_4.yaml.bak', 'configfull_new.yaml', 'configfull_new_4.yaml')
CANDIDATE = 'configfull_new.yaml'
FAMILIES = ('通用', 'Cloudflare', 'GitHub网页', 'GitHubRaw', 'GitHub归档')
URLS = dict(zip(FAMILIES, (
    'https://www.gstatic.com/generate_204', 'https://cp.cloudflare.com/generate_204',
    'https://github.com/robots.txt',
    'https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.30/README.md',
    'https://codeload.github.com/_ping')))
STATUS = dict(zip(FAMILIES, (204, 204, 200, 200, 200)))
LOCAL = {f: f'http://probe.invalid/{i}' for i, f in enumerate(FAMILIES)}
PATHS = {f: urllib.parse.urlsplit(url).path for f, url in LOCAL.items()}
REGIONS = ('香港', '日本', '新加坡', '台湾', '美国')
SAMPLES = ('日本 fast 1x', '日本 slow 1x', '日本 CTCU 1x', '日本 CTCUCM 1x',
           '日本 0.3x', '日本 MITM 1x', '日本 BETA 1x', '日本 6x',
           '新加坡 1x', '香港 1x', 'HongKong 05 1x', '美国 0.1x', '美国 1x',
           '台湾 1x', '台湾 BETA 1x', '德国 1x')


def static(source, name):
    groups = {g['name']: g for g in source['proxy-groups']}
    outbounds = {p['name']: p for p in source['proxies']}
    assert len(groups) + len(outbounds) == len(set(groups) | set(outbounds)), '重复出口名称'
    assert len(groups) == len(source['proxy-groups']) and len(outbounds) == len(source['proxies']), '重复定义'
    known = set(groups) | set(outbounds) | {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'}
    for g in groups.values():
        assert set(g.get('proxies', [])) <= known, g['name']
        assert set(g.get('use', [])) <= set(source['proxy-providers']), g['name']
        assert len(set(g.get('proxies', []))) == len(g.get('proxies', [])), g['name']
    for n in known:
        assert '机场' not in re.sub(r'机场名称[1-4](?![0-9])', '', n), n
    for outbound in outbounds.values():
        if outbound['type'] == 'rematch':
            assert outbound['target-sub-rule'] in source['sub-rules'], outbound['name']
    def visit(node, path=(), global_mode=False):
        assert node not in path, ('循环引用', path, node)
        assert not global_mode or node not in outbounds or outbounds[node]['type'] != 'rematch', node
        for child in groups.get(node, {}).get('proxies', []):
            visit(child, (*path, node), global_mode)
    for n in groups:
        visit(n)
    visit('GLOBAL', global_mode=True)
    if name != CANDIDATE:
        return
    assert source['tun']['device'] == 'tun0'
    assert source['profile']['store-selected'] and source['profile']['store-fake-ip']
    for g in groups.values():
        if g['type'] != 'select':
            assert g['timeout'] == 5000 and g['empty-fallback'] == 'REJECT', g['name']
            assert g.get('url', URLS['通用']) in URLS.values(), g['name']
            family = next(f for f in FAMILIES if URLS[f] == g.get('url', URLS['通用']))
            assert g['expected-status'] == STATUS[family], g['name']
            if g['type'] == 'url-test':
                assert g['tolerance'] == 50, g['name']
            if g.get('use') and family != '通用':
                assert 'exclude-filter' not in g, g['name']
    for family in FAMILIES:
        for policy, airports in [('质量优先', (1, 3)), ('成本优先', (3, 1))]:
            order = [f'节点池-机场名称{a}-{r}-{family}探针' for a in airports
                     for r in (('日本', '香港', '新加坡', '美国') if a == 1 else ('日本', '新加坡', '香港', '美国'))]
            assert groups[f'回退-{policy}-{family}探针']['proxies'] == order + [f'备用池-机场名称4-{family}探针']
            for region in REGIONS:
                g = groups[f'地区回退-{region}-{policy}-{family}探针']
                assert g['proxies'] == [f'节点池-机场名称{a}-{region}-{family}探针' for a in airports]
                assert g['use'] == ['Airport_04']
            if family in ('通用', 'Cloudflare', 'GitHub归档'):
                order = [f'下载池-机场名称{a}-{r}-{family}探针' for a in (*airports, 4)
                         for r in (('日本', '新加坡', '美国', '香港', '其他') if a == 4 else ('日本', '新加坡', '美国', '香港'))]
                assert groups[f'下载回退-{policy}-{family}探针']['proxies'] == order
    for n in ('AI', '金融', 'Talkatone'):
        assert groups[n]['proxies'] == ['节点池-机场名称1-日本-Cloudflare探针', 'DIRECT']
        assert groups[n]['use'] == ['Airport_01', 'Airport_03', 'Airport_04']
    assert groups['规则更新']['proxies'] == groups['回退-成本优先-GitHubRaw探针']['proxies'] + ['DIRECT']
    assert groups['规则更新']['url'] == URLS['GitHubRaw']


NODE_CASES = {
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

def node_filters(source, mihomo):
    with tempfile.TemporaryDirectory(prefix='mihomo-filters-') as directory, F.Runtime(directory, mihomo) as rt:
        providers, expected, manual, capabilities = {}, {}, set(), {}
        for provider, cases in NODE_CASES.items():
            p = copy.deepcopy(source['proxy-providers'][provider])
            prefix = p['override']['additional-prefix']
            proxies = []
            for index, (raw, memberships) in enumerate(cases):
                name = prefix + raw
                manual.add(name)
                capabilities[name] = index % 2 == 0
                for membership in memberships:
                    expected.setdefault(membership, set()).add(name)
                if provider == 'Airport_04':
                    expected.setdefault('download4', set()).add(name)
                proxies.append(dict(name=raw, type='socks5', server='127.0.0.1', port=9, udp=capabilities[name]))
            for notice in ('剩余流量: 100 GB', '套餐到期: 2027-01-01', 'Email: support@example.invalid', 'Expired'):
                proxies.append(dict(name=notice, type='socks5', server='127.0.0.1', port=9))
            file = Path(directory) / (provider + '.json')
            file.write_text(json.dumps({'proxies': proxies}))
            p.update(type='file', path=str(file))
            p.pop('url')
            p['health-check'] = {'enable': False}
            providers[provider] = p
        subjects = {'开发下载': 'manual', '手选-自建家宽': 'home', '台湾限定': 'tw4',
                    'Google FCM': 'manual', 'OneDrive': 'manual'}
        for family in FAMILIES:
            for airport, region, membership in ((1, '香港', 'hk1'), (1, '日本', 'jp1'),
                    (3, '日本', 'jp3'), (3, '新加坡', 'sg3'), (3, '美国', 'us3')):
                subjects[f'节点池-机场名称{airport}-{region}-{family}探针'] = membership
        groups = []
        for g in source['proxy-groups']:
            if g['name'] in subjects or g['name'].startswith('下载池-'):
                g = copy.deepcopy(g)
                g.pop('proxies', None)
                g.update(url='http://127.0.0.1:9/probe', interval=86400, lazy=True)
                groups.append(g)
        config = rt.base(source)
        config.update(proxies=[], **{'sub-rules': {}, 'rules': ['MATCH,REJECT'],
                      'proxy-providers': providers, 'proxy-groups': groups})
        rt.start(config)
        F.until(lambda: set(rt.group('开发下载')['all']) == manual)
        actual = rt.api('/proxies')['proxies']
        for name, membership in subjects.items():
            want = manual if membership == 'manual' else expected[membership]
            assert set(actual[name]['all']) == want, (name, set(actual[name]['all']) ^ want)
        for family in ('通用', 'Cloudflare', 'GitHub归档'):
            for airport in (1, 3, 4):
                members = {node for g in groups if g['name'].startswith(f'下载池-机场名称{airport}-')
                           and g['name'].endswith(f'-{family}探针') for node in actual[g['name']]['all'] if node != 'REJECT'}
                assert members == expected[f'download{airport}'], (airport, family, members)
        actual_nodes = {n['name']: n for p in rt.api('/providers/proxies')['providers'].values() for n in p['proxies']}
        for name, udp in capabilities.items():
            assert actual_nodes[name]['udp'] == udp, name
    print('PASS: 节点准入、下载筛选、公告过滤及 UDP 声明', flush=True)


def health(source, mihomo):
    with tempfile.TemporaryDirectory(prefix='mihomo-health-') as directory, F.Runtime(
            directory, mihomo, {PATHS[f]: STATUS[f] for f in FAMILIES}) as rt:
        config = rt.base(source)
        config['proxy-providers'], nodes = {}, {}
        for provider in source['proxy-providers']:
            nodes[provider] = [rt.proxy(f'[机场名称{int(provider[-2:])}]{sample}') for sample in SAMPLES]
            path = Path(directory) / (provider + '.json')
            path.write_text(json.dumps({'proxies': nodes[provider]}))
            config['proxy-providers'][provider] = dict(type='file', path=str(path), **{'health-check': dict(
                enable=True, url=LOCAL['通用'], interval=86400, timeout=5000, lazy=False, **{'expected-status': 204})})
        config['proxy-groups'] = copy.deepcopy(source['proxy-groups'])
        for g in config['proxy-groups']:
            if 'url' in g:
                g['url'] = LOCAL[next(f for f in FAMILIES if URLS[f] == g['url'])]
            if g['type'] != 'select':
                g['interval'] = 86400
        config['rules'] = ['MATCH,通用代理']
        rt.start(config)
        fast = '[机场名称3]日本 fast 1x'
        F.until(lambda: all(rt.group(f'节点池-机场名称3-日本-{f}探针')['now'] == fast for f in FAMILIES))
        expected = {(p, f): {n['name'] for n in nodes[p]} if f == '通用' else set()
                    for p in nodes for f in FAMILIES}
        # 准入已由独立案例验证；此处只验证额外探针遵守各组候选并集且不重复测。
        for g in source['proxy-groups']:
            family = next((f for f in FAMILIES if g.get('url') == URLS[f]), None)
            if not family:
                continue
            for provider in g.get('use', []):
                for node in nodes[provider]:
                    name = node['name']
                    def match(pattern):
                        return any(re.search(p.removeprefix('(?i)'), name, re.I) for p in pattern.split('`'))
                    if match(g.get('filter', '.*')) and not (g.get('exclude-filter') and match(g['exclude-filter'])):
                        expected[provider, family].add(name)
        before = {n: dict(s.counts) for n, s in rt.http.nodes.items()}
        for provider in nodes:
            rt.api('/providers/proxies/' + provider + '/healthcheck')
        for provider, values in nodes.items():
            for node in values:
                name = node['name']
                for f in FAMILIES:
                    delta = rt.http.nodes[name].counts.get(PATHS[f], 0) - before[name].get(PATHS[f], 0)
                    assert delta == int(name in expected[provider, f]), (name, f, delta)
        def probe(name, family):
            return rt.probe(name, LOCAL[family], STATUS[family])
        pairs = [(f'节点池-机场名称{a}-{r}-{f}探针', f) for f in FAMILIES for a in (3, 1)
                 for r in ('日本', '新加坡', '香港', '美国')]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda pair: probe(*pair), pairs))
        for family in FAMILIES:
            for name, node in rt.http.nodes.items():
                if name.startswith('[机场名称3]'):
                    node.statuses[PATHS[family]] = 503
            rt.api('/providers/proxies/Airport_03/healthcheck')
            children = [name for name, f in pairs if f == family and name.startswith('节点池-机场名称3-')]
            for child in children:
                probe(child, family)
            root = f'回退-成本优先-{family}探针'
            assert rt.group(root)['now'] == f'节点池-机场名称1-日本-{family}探针', family
            for other in FAMILIES:
                if other != family:
                    assert rt.group(f'回退-成本优先-{other}探针')['now'].startswith('节点池-机场名称3-'), other
            for node in rt.http.nodes.values():
                node.statuses.clear()
            rt.api('/providers/proxies/Airport_03/healthcheck')
            for child in children:
                assert probe(child, family)
            assert rt.group(root)['now'] == children[0]
        for status in (403, 429, 503):
            rt.http.nodes[fast].statuses[PATHS['GitHubRaw']] = status
            assert not probe(fast, 'GitHubRaw'), status
            assert probe(fast, '通用')
        rt.http.nodes[fast].statuses.clear()
        rt.http.nodes[fast].delays[PATHS['GitHubRaw']] = 5.3
        assert not probe(fast, 'GitHubRaw'), '超时'
        rt.http.nodes[fast].delays.clear()
        assert not rt.probe(fast, 'https://tls.invalid/3', 200), 'TLS 握手失败'
        assert probe(fast, 'GitHubRaw')
        rt.select('金融', fast)
        scoped = '节点池-机场名称1-日本-Cloudflare探针'
        for restart in (False, True):
            if restart:
                rt.stop()
                rt.start(config)
            else:
                rt.reload(config)
            F.until(lambda: rt.group('金融')['now'] == fast)
            assert rt.group('AI')['now'] == scoped and rt.group('Talkatone')['now'] == scoped
        path = Path(directory) / 'Airport_01.json'
        path.write_text(json.dumps({'proxies': [n for n in nodes['Airport_01'] if '日本' not in n['name']]}))
        rt.api('/providers/proxies/Airport_01', 'PUT')
        F.until(lambda: rt.group(scoped)['all'] == ['REJECT'])
        def converged():
            current = rt.group(scoped)['now']
            assert current == 'REJECT' or current.startswith('[机场名称1]日本'), current
            return current == 'REJECT'
        F.until(converged)
        path = Path(directory) / 'Airport_03.json'
        path.write_text(json.dumps({'proxies': [n for n in nodes['Airport_03'] if n['name'] != fast]}))
        rt.api('/providers/proxies/Airport_03', 'PUT')
        F.until(lambda: rt.group('金融')['now'] == scoped)
    print('PASS: 探针范围/去重、故障隔离/恢复、同区测速、缓存与空池', flush=True)


# 独立业务见证：同一机制的重复域名省略，保留实际重叠和易误分流边界。
BUSINESSES = {
    'www.408os.cn': 'DIRECT', 'weixin.qq.com': 'DIRECT', 'music.163.com': 'DIRECT',
    'www.mi.com': 'DIRECT', 'hk.tv.global.mi.com': '通用代理',
    'whatsapp.com': '境外通信', 'telegram.org': 'Telegram', '149.154.167.51': 'Telegram',
    'www.pixiv.net': '境外社媒', 's.pximg.net': '境外社媒',
    'chatgpt.com': 'AI', 'origin-tracker.githubusercontent.com': 'AI',
    'copilotprodattachments.blob.core.windows.net': 'AI',
    'wise.com': '金融', 'talkatone.com': 'Talkatone',
    'github.com': '开发下载', 'raw.githubusercontent.com': '开发下载', 'gitbook.com': '开发下载',
    'codeload.github.com': '纯下载', 'release-assets.githubusercontent.com': '纯下载', 'aur.archlinux.org': '纯下载',
    'cloudflare.com': '通用代理', 'example.pages.dev': '通用代理', 'cf-china.info': 'DIRECT',
    'unpkg.com': '开发下载', 'registry-1.docker.io': '开发下载', 'huggingface.co': '开发下载',
    'google.com': 'Google', 'services.googleapis.cn': 'Google', 'fcm.googleapis.com': 'Google',
    'microsoft.com': 'Microsoft', 'bilibili.tv': '哔哩东南亚', 'gamer.com.tw': '台湾限定',
    'bilibili.com': '哔哩哔哩', 'ad.doubleclick.net': '隐私拦截',
}
# 顺序对应 CONFIGS，明确列出差异，不通过旧名投影或配置当前值推导预期。
VARIANT_CASES = {
    'mtalk.google.com': ('Google', 'Google', 'Google FCM', 'FCM'),
    'onedrive.live.com': ('Microsoft', 'Microsoft', 'OneDrive', 'OneDrive'),
    'netflix.com': ('NETFLIX', 'NETFLIX', 'Netflix', 'NETFLIX'),
}
DEFAULTS = {
    'google.com': ('机场名称3优先', '机场名称3优先', '回退-成本优先-通用探针', '机场名称3优先'),
    'wise.com': ('机场名称1优先', '家宽优先', '节点池-机场名称1-日本-Cloudflare探针', '金融-机场名称2-香港'),
    'talkatone.com': ('机场名称1优先', '家宽优先', '节点池-机场名称1-日本-Cloudflare探针', 'Talkatone-机场名称2-香港'),
    'github.com': ('GitHub-自动', 'GitHub-自动', '回退-成本优先-GitHub网页探针', 'GitHub-自动'),
    'raw.githubusercontent.com': ('GitHub-自动', 'GitHub-自动', '回退-成本优先-GitHubRaw探针', 'GitHub-自动'),
    'codeload.github.com': ('纯下载-自动', '纯下载-自动', '下载回退-成本优先-GitHub归档探针', '纯下载-自动'),
    'cloudflare.com': ('Cloudflare-机场名称1优先', 'Cloudflare-机场名称1优先', '回退-质量优先-Cloudflare探针', 'Cloudflare-机场名称1优先'),
    'bilibili.tv': ('新加坡-机场名称1优先', '新加坡-机场名称1优先', '地区回退-新加坡-质量优先-通用探针', '新加坡-机场名称1优先'),
    'gamer.com.tw': ('台湾-机场名称1优先', '台湾-机场名称1优先', '地区回退-台湾-质量优先-通用探针', '台湾-机场名称1优先'),
}
TUNNEL = [('region1.v2.argotunnel.com', 7844, 'Cloudflare Tunnel'),
          ('region1.v2.argotunnel.com', 443, 'DIRECT'), ('unknown.argotunnel.com', 7844, 'DIRECT'),
          ('198.41.192.167', 7844, 'Cloudflare Tunnel'), ('198.41.192.1', 7844, '通用代理')]


def local_direct(rules):
    result = []
    for rule in rules:
        parts = rule.split(',')
        index = -2 if parts[-1] == 'no-resolve' else -1
        if parts[index] == 'DIRECT':
            parts[index] = 'fixture-DIRECT'
        result.append(','.join(parts))
    return result


def business(source, config_name, mihomo, rules_dir):
    index = CONFIGS.index(config_name)
    cases = {**BUSINESSES, **{h: v[index] for h, v in VARIANT_CASES.items()}}
    with tempfile.TemporaryDirectory(prefix='mihomo-business-') as directory, F.Runtime(directory, mihomo) as rt:
        config = rt.base(source)
        config['rule-providers'] = F.prepare_rules(source, rules_dir, Path(directory))
        config['rules'] = local_direct(source['rules'])
        config['sub-rules'] = {n: local_direct(rules) for n, rules in source['sub-rules'].items()}
        config['hosts'] = {h: '1.1.1.1' for h in cases if not re.match(r'^\d+\.', h)}
        config['hosts'].update({'www.408os.cn': '106.75.74.76', 'google.com': '45.121.184.1'})
        config['proxy-groups'], selections = [], {}
        for original in source['proxy-groups']:
            name = original['name']
            label = 'fixture-' + name
            config['proxies'].append(rt.proxy(label, name))
            if original['type'] == 'select':
                g = copy.deepcopy(original)
                g.pop('use', None)
                for field in ('filter', 'exclude-filter', 'url'):
                    g.pop(field, None)
                g['proxies'] = [label] + ['fixture-DIRECT' if p == 'DIRECT' else p for p in g.get('proxies', [])]
                selections[name] = original.get('proxies', ['REJECT'])[0]
                config['proxy-groups'].append(g)
            else:
                config['proxy-groups'].append(dict(name=name, type='select', proxies=[label]))
        config['proxies'].append(rt.proxy('fixture-DIRECT', 'DIRECT'))
        dns = rt.server(F.DNSHandler, socketserver.UDPServer)
        dns.answer, dns.answers, dns.queries = '1.1.1.1', {}, set()
        config['dns'] = dict(enable=True, nameserver=[f'udp://127.0.0.1:{dns.server_address[1]}'])
        rt.start(config)
        F.until(lambda: all(p['ruleCount'] > 0 for p in rt.api('/providers/rules')['providers'].values()))
        for host, expected in cases.items():
            actual = rt.request(host)
            assert actual == expected, (config_name, host, expected, actual)
        for host, port, expected in TUNNEL:
            actual = rt.request(host, port)
            assert actual == expected, (config_name, host, port, expected, actual)
        if not config_name.endswith('.bak'):
            fcm = 'Google FCM' if config_name == CANDIDATE else 'FCM'
            for host, port, expected in [('8.8.8.8', 5228, fcm), ('203.208.40.1', 5230, fcm),
                    ('8.8.8.8', 443, 'Google'), ('1.1.1.1', 5228, '通用代理'),
                    ('45.121.184.1', 5230, 'DIRECT')]:
                assert rt.request(host, port) == expected, (config_name, host, port, expected)
        # 只恢复被业务见证覆盖的 select，其他辅助选择保持可追踪标签。
        for name in set(cases.values()) - {'DIRECT', '隐私拦截', 'AI'}:
            choice = selections[name]
            rt.select(name, 'fixture-DIRECT' if choice == 'DIRECT' else choice)
        for host, choices in DEFAULTS.items():
            actual = rt.request(host)
            assert actual == choices[index], (config_name, host, choices[index], actual)
    print(f'PASS: {config_name} 关键业务、默认出口与 Tunnel/FCM 边界', flush=True)


def routing(source, mihomo, rules_dir):
    with tempfile.TemporaryDirectory(prefix='mihomo-routing-') as directory, ExitStack() as sockets, F.Runtime(directory, mihomo) as rt:
        config = rt.base(source)
        config['rule-providers'] = F.prepare_rules(source, rules_dir, Path(directory))
        config['proxy-groups'] = []
        for original in source['proxy-groups']:
            g = copy.deepcopy(original)
            g.pop('use', None)
            for field in ('filter', 'exclude-filter', 'url'):
                g.pop(field, None)
            if g['type'] == 'select':
                if not g.get('proxies'):
                    g['proxies'] = ['REJECT']
                config['proxy-groups'].append(g)
            else:
                name = g['name']
                label = 'fixture-' + name
                config['proxies'].append(rt.proxy(label, name))
                choices = [label]
                if name.startswith('回退-成本优先-'):
                    config['proxies'].append(rt.udp_proxy(label + '-udp', name))
                    choices.append(label + '-udp')
                config['proxy-groups'].append(dict(name=name, type='select', proxies=choices))
        dns = rt.server(F.DNSHandler, socketserver.UDPServer)
        dns.answer, dns.answers, dns.queries = '203.0.113.9', {
            'unknown-cf.fixture.test': ['104.16.1.1'], 'dns-failed.fixture.test': []}, set()
        dns_port = F.free_port()
        config['dns'] = dict(enable=True, listen=f'127.0.0.1:{dns_port}', **{
            'enhanced-mode': 'fake-ip', 'fake-ip-range': '198.18.0.1/16',
            'nameserver': [f'udp://127.0.0.1:{dns.server_address[1]}']})
        config['rules'] = ['NETWORK,tcp,通用代理', 'NETWORK,udp,通用代理', 'MATCH,DIRECT']
        rt.start(config)
        cases = dict(zip(('www.google.com', 'dash.cloudflare.com', 'github.com',
                          'raw.githubusercontent.com', 'codeload.github.com'), FAMILIES))
        entries = [('通用代理', '自动-质量优先', '回退-质量优先'),
                   ('通用代理', '自动-成本优先', '回退-成本优先'),
                   ('通用代理', '地区-日本-质量优先', '地区回退-日本-质量优先'),
                   ('Google', '地区-台湾-成本优先', '地区回退-台湾-成本优先'),
                   ('纯下载', '自动-下载-质量优先', '下载回退-质量优先'),
                   ('纯下载', '自动-下载-成本优先', '下载回退-成本优先')]
        for business_name, entry, target in entries:
            config['rules'] = [f'NETWORK,tcp,{business_name}', f'NETWORK,udp,{business_name}', 'MATCH,DIRECT']
            rt.reload(config)
            rt.select(business_name, entry)
            for host, family in cases.items():
                if business_name == '纯下载' and family in ('GitHub网页', 'GitHubRaw'):
                    try:
                        rt.request(host)
                    except (OSError, http.client.HTTPException, AssertionError):
                        continue
                    raise AssertionError(('下载入口不应接受此分支', entry, family))
                expected = f'{target}-{family}探针'
                actual = rt.request(host)
                assert actual == expected, (entry, host, expected, actual)
        config['rules'] = ['NETWORK,tcp,通用代理', 'NETWORK,udp,通用代理', 'MATCH,DIRECT']
        rt.reload(config)
        rt.select('通用代理', '自动-成本优先')
        for host, family in [('api.github.com', 'GitHub网页'), ('release-assets.githubusercontent.com', 'GitHub归档'),
                ('foo.github.io', 'GitHub网页'), ('gitbook.com', '通用'), ('foo.pages.dev', 'Cloudflare'),
                ('unknown-cf.fixture.test', 'Cloudflare'), ('dns-failed.fixture.test', '通用')]:
            assert rt.request(host) == f'回退-成本优先-{family}探针', (host, family)
        # 每类一组 UDP 正反例，不再对同类所有域名重复等待超时。
        for host, family in cases.items():
            name = f'回退-成本优先-{family}探针'
            rt.select(name, 'fixture-' + name + '-udp')
            assert F.udp_request(rt.mixed, host, sockets) == name, host
            rt.select(name, 'fixture-' + name)
            try:
                result = F.udp_request(rt.mixed, host, sockets)
            except socket.timeout:
                pass
            else:
                raise AssertionError(('UDP 不应泄漏', host, result))
        code, ips = F.query(dns_port, 'unknown-cf.fixture.test')
        assert code == 0 and ips[0].startswith('198.18.'), ips
        name = '回退-成本优先-Cloudflare探针'
        rt.select(name, 'fixture-' + name + '-udp')
        assert F.udp_request(rt.mixed, ips[0], sockets) == name
        rt.api('/configs', 'PATCH', {'mode': 'global'})
        rt.select('GLOBAL', '地区回退-日本-成本优先-通用探针')
        assert rt.request('github.com') == '地区回退-日本-成本优先-通用探针'
    print('PASS: 五类分类、固定地区/下载边界、UDP、Fake-IP/CF 与 GLOBAL', flush=True)


def dns_policy(source, mihomo):
    dns = copy.deepcopy(source['dns'])
    assert source['ipv6'] is False and dns['ipv6'] is False
    assert dns['direct-nameserver-follow-policy'] is True and dns['respect-rules'] is True
    with tempfile.TemporaryDirectory(prefix='mihomo-dns-') as directory, F.Runtime(directory, mihomo) as rt:
        servers = []
        for address in ('203.0.113.10', '203.0.113.20'):
            server = rt.server(F.DNSHandler, socketserver.UDPServer)
            server.answer, server.answers, server.queries = address, {}, set()
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
            assert value in (dns['direct-nameserver'], dns['nameserver']), (key, value)
            dns['nameserver-policy'][key] = [local[1] if value == dns['nameserver'] else local[0]]
        port = F.free_port()
        dns.update({'listen': f'127.0.0.1:{port}', 'default-nameserver': [local[0]],
                    'proxy-server-nameserver': [local[0]], 'direct-nameserver': [local[0]], 'nameserver': [local[1]]})
        providers = {name: {'type': 'inline', 'behavior': p['behavior'], 'payload': []}
                     for name, p in source['rule-providers'].items()}
        for name, values in {'cn_domain': ['+.cn.fixture.test', '+.cn', '+.bilibili.tv', 'hk.tv.global.mi.com'],
                             'google_domain': ['+.googleapis.cn', '+.gstatic.cn', '+.xn--ngstr-lra8j.com'],
                             'biliintl_domain': ['+.bilibili.tv'],
                             'TVB_domain': ['tvbc.com.cn'],
                             'proxy_domain': ['+.services.googleapis.cn', 'proxy.cn.fixture.test'],
                             'xiaomi_domain': ['+.mi.com'],
                             'media_cn_domain': ['+.bilibili.tv'],
                             'private_domain': ['+.lan', '+.plex.direct'],
                             'stun_domain': ['stun.external.fixture.test', 'stun.cn.fixture.test',
                                             'stun.wechat.fixture.test'],
                             'wechat_domain': ['+.wechat.fixture.test'],
                             'fakeip_filter_domain': ['legacy.external.fixture.test']}.items():
            providers[name]['payload'] = values
        config = rt.base(source)
        config.update(dns=dns, ipv6=source['ipv6'], proxies=[], **{'sub-rules': {},
                      'rule-providers': providers, 'rules': ['MATCH,DIRECT']})
        rt.start(config)
        F.until(lambda: F.query(port, 'ready.external.fixture.test'))
        for host, expected in [
            ('ordinary.cn.fixture.test', [domestic.answer]),
            ('ordinary.external.fixture.test', 'fake'),
            ('services.googleapis.cn', 'fake'),
            ('fonts.gstatic.cn', 'fake'),
            ('redirector.xn--ngstr-lra8j.com', 'fake'),
            ('www.bilibili.tv', 'fake'),
            ('tvbc.com.cn', 'fake'),
            ('proxy.cn.fixture.test', 'fake'),
            ('hk.tv.global.mi.com', 'fake'),
            ('www.mi.com', [domestic.answer]),
            ('stun.external.fixture.test', [foreign.answer]),
            ('stun.cn.fixture.test', [domestic.answer]),
            ('stun.wechat.fixture.test', [domestic.answer]),
            ('connectivitycheck.gstatic.com', [foreign.answer]),
            ('legacy.external.fixture.test', [foreign.answer]),
            ('router.lan', 'nxdomain'), ('public.plex.direct', [domestic.answer]),
            ('other.argotunnel.com', 'fake'), *tunnel.items(),
        ]:
            rcode, ips = F.query(port, host)
            if expected == 'nxdomain':
                assert (rcode, ips) == (3, []), (host, rcode, ips)
            elif expected == 'fake':
                assert rcode == 0 and len(ips) == 1 and ipaddress.ip_address(ips[0]) in ipaddress.ip_network(dns['fake-ip-range']), (host, ips)
            else:
                assert rcode == 0 and sorted(ips) == sorted(expected), (host, ips)
        for host, qtype in [('_v2-origintunneld._tcp.argotunnel.com', 33), ('cfd-features.argotunnel.com', 16)]:
            assert F.query(port, host, qtype) == (0, [])
            assert (host, qtype) in domestic.queries and (host, qtype) not in foreign.queries
        # TXT 不经过 Fake-IP 合成，验证相同交集的真实解析策略。
        for host in ['services.googleapis.cn', 'fonts.gstatic.cn', 'redirector.xn--ngstr-lra8j.com',
                     'www.bilibili.tv', 'tvbc.com.cn',
                     'proxy.cn.fixture.test', 'hk.tv.global.mi.com']:
            assert F.query(port, host, 16) == (0, [])
            assert (host, 16) in foreign.queries and (host, 16) not in domestic.queries, host
        print('PASS: DNS 国内外解析、Fake-IP 及 Tunnel 例外', flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('static', 'smoke', 'full'), default='full')
    parser.add_argument('--mihomo', default=os.environ.get('MIHOMO_BIN', 'mihomo'))
    parser.add_argument('--rules-dir', type=Path, help='共享规则快照；目录不存在时创建，存在时严格校验')
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    print(subprocess.check_output([args.mihomo, '-v'], text=True, timeout=10).strip(), flush=True)
    sources = {name: F.load(ROOT / name) for name in CONFIGS}
    command = ['ruby', str(ROOT / 'scripts/validate-rules.rb')]
    for name in CONFIGS:
        command.extend(['--config', str(ROOT / name)])
    subprocess.run(command, env={**os.environ, 'MIHOMO_BIN': args.mihomo}, check=True, timeout=150)
    for name, source in sources.items():
        static(source, name)
    if args.suite == 'static':
        return
    with tempfile.TemporaryDirectory(prefix='mihomo-rules-') as directory:
        rules_dir = args.rules_dir or Path(directory) / 'snapshot'
        F.snapshot(sources.values(), rules_dir)
        for name, source in sources.items():
            business(source, name, args.mihomo, rules_dir)
        routing(sources[CANDIDATE], args.mihomo, rules_dir)
        if args.suite == 'full':
            node_filters(sources[CANDIDATE], args.mihomo)
            health(sources[CANDIDATE], args.mihomo)
            dns_policy(sources[CANDIDATE], args.mihomo)
    print(f'PASS: {args.suite}', flush=True)


if __name__ == '__main__':
    main()
