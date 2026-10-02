#!/usr/bin/env python3
"""配置回归：static=双模型及备份基础；smoke=关键分流；full=共同机制与四机场差异。"""
import argparse
import concurrent.futures
import copy
from contextlib import ExitStack
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
import urllib.parse

import mihomo_fixture as F

ROOT = F.ROOT
ACTIVE_CONFIGS = ('configfull_new.yaml', 'configfull_new_4.yaml')
CONFIGS = ACTIVE_CONFIGS + tuple(name + '.bak' for name in ACTIVE_CONFIGS)
PRIMARY_CONFIG, FOUR_CONFIG = ACTIVE_CONFIGS
FAMILIES = ('Google', 'CF', 'GitHub', 'TG')
URLS = dict(zip(FAMILIES, (
    'https://www.gstatic.com/generate_204', 'https://cp.cloudflare.com/generate_204',
    'https://github.com/robots.txt', 'https://flora.web.telegram.org/apiw1')))
STATUS = dict(zip(FAMILIES, (204, 204, 200, 501)))
LOCAL = {f: f'http://probe.invalid/{i}' for i, f in enumerate(FAMILIES)}
PATHS = {f: urllib.parse.urlsplit(url).path for f, url in LOCAL.items()}
REGIONS = ('香港', '日本', '新加坡', '台湾', '美国')
SAMPLES = ('日本 fast 1x', '日本 slow 1x', '日本 CTCU 1x', '日本 CTCUCM 1x',
           '日本 0.3x', '日本 MITM 1x', '日本 BETA 1x', '日本 6x',
           '新加坡 1x', '香港 1x', 'HongKong 05 1x', '美国 0.1x', '美国 1x',
           '台湾 1x', '台湾 BETA 1x', '德国 1x')


def pool_name(airport, region, family):
    return f"机场名称{airport}-{region}-{family}"


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
    if name not in ACTIVE_CONFIGS:
        return
    four = name == FOUR_CONFIG
    airports = (1, 2, 3) if four else (1, 3)
    priorities = {1: (1, 2, 3), 2: (2, 1, 3), 3: (3, 1, 2)} if four else {1: (1, 3), 3: (3, 1)}
    providers = [f'Airport_0{a}' for a in (*airports, 4)]
    assert list(source['proxy-providers']) == providers
    assert len(groups) == (159 if four else 119)
    assert len(outbounds) == (19 if four else 13)
    tg_groups = {n for n in groups if n.endswith('-TG')}
    assert len(tg_groups) == (16 if four else 11)
    assert source['sub-rules']['分流-TG-出口'] == [
        f'REMATCH-NAME,机场名称{a}优先,机场名称{a}优先-TG' for a in airports] + ['MATCH,REJECT']
    for a in (*airports, 4):
        override = source['proxy-providers'][f'Airport_0{a}']['override']
        assert override['additional-prefix'] == f'[机场名称{a}]'
        assert override.get('additional-suffix', '') == (' [家宽]' if a == 2 else '')
        assert override['skip-cert-verify'] is False
    assert source['tun']['device'] == 'tun0'
    assert source['profile']['store-selected'] and source['profile']['store-fake-ip']
    for g in groups.values():
        assert 'policies' not in g, g['name']
        if g['type'] != 'select':
            assert g['timeout'] == 5000 and g['empty-fallback'] == 'REJECT', g['name']
            assert g.get('url', URLS['Google']) in URLS.values(), g['name']
            family = next(f for f in FAMILIES if URLS[f] == g.get('url', URLS['Google']))
            assert g['expected-status'] == STATUS[family], g['name']
            if g['type'] == 'url-test':
                assert g['tolerance'] == 50, g['name']
            if g.get('use') and family != 'Google':
                assert 'exclude-filter' not in g, g['name']
    for family in FAMILIES:
        for preferred, order_airports in priorities.items():
            policy = f'机场名称{preferred}优先'
            region_order = {1: ('日本', '香港', '新加坡', '美国'),
                            2: ('香港', '日本', '新加坡', '美国'),
                            3: ('日本', '新加坡', '香港', '美国')}
            order = [pool_name(a, r, family) for a in order_airports for r in region_order[a]]
            assert groups[f'{policy}-{family}']['proxies'] == order + [f'机场名称4-备用-{family}']
            for region in REGIONS:
                if family == 'TG':
                    assert f'{region}-{policy}-{family}' not in groups
                    continue
                g = groups[f'{region}-{policy}-{family}']
                assert g['proxies'] == [pool_name(a, region, family) for a in order_airports]
                assert g['use'] == ['Airport_04']
    required = {f'机场名称{a}优先' for a in airports} | {'自建/家宽节点', '全部节点', 'DIRECT'}
    required.update(f'{r}-机场名称{a}优先' for r in REGIONS for a in airports)
    private = {'专用-机场名称1-日本-Google', '专用-机场名称1-日本-CF'}
    if four:
        private |= {'专用-机场名称2-香港-Google', '专用-机场名称2-香港-CF'}
    helpers = {'自建/家宽节点', '低倍率/MITM节点', '全部节点'}
    sensitive = {'AI', '金融', 'Talkatone'}
    businesses = {n for n, g in groups.items() if g['type'] == 'select'} - helpers - {'GLOBAL'}
    assert '下载' in businesses and not {'纯下载', '开发下载'} & businesses
    assert not any(n.startswith('下载-') for n in known)
    assert not any('GitHubRaw' in n or 'GitHub归档' in n for n in known)
    for n, g in groups.items():
        choices = set(g.get('proxies', []))
        assert not choices & businesses, (n, '业务组不应被其他组引用')
        assert not choices & private or n in sensitive, (n, '专用池越界')
        assert '低倍率/MITM节点' not in choices or n == 'Emby', n
        if n not in businesses:
            continue
        extras = private if n in sensitive else set()
        if n == 'Emby':
            extras = {'低倍率/MITM节点'}
        if n == '隐私拦截':
            extras = {'REJECT', 'REJECT-DROP'}
        assert choices == required | extras, n
        assert g['use'] == providers
        assert 'filter' in g and 'exclude-filter' not in g, n
    physical = {n + '-Google' if n in outbounds else n for n in required}
    assert set(groups['GLOBAL']['proxies']) == physical
    for n in sensitive:
        scope = '专用-机场名称2-香港' if four and n != 'AI' else '专用-机场名称1-日本'
        assert groups[n]['proxies'][:2] == [scope + '-Google', scope + '-CF']
        assert set(groups[n]['proxies'][:len(private)]) == private
    for n in private:
        provider = 'Airport_02' if '机场名称2' in n else 'Airport_01'
        assert groups[n]['type'] == 'url-test' and groups[n]['use'] == [provider]
        assert 'proxies' not in groups[n]
    for n in ('低倍率/MITM节点', '全部节点'):
        assert groups[n]['proxies'] == ['REJECT'] and groups[n]['empty-fallback'] == 'REJECT'
    assert groups['下载']['proxies'][0] == '机场名称3优先'
    assert groups['规则更新']['proxies'] == groups['机场名称3优先-GitHub']['proxies'] + ['DIRECT']
    assert groups['规则更新']['url'] == URLS['GitHub']
    if four:
        for n in ('Netflix', 'Disney+', 'HBO', 'Prime Video', 'Spotify', 'Reddit'):
            assert groups[n]['proxies'][0] == '机场名称2优先', n
    assert 'pure_download_domain' not in source['rule-providers']
    assert not re.search(r'(^|\s)[&*][A-Za-z_]|^\s*<<:', (ROOT / name).read_text(), re.M)


def common_settings(three, four):
    # 这些部分完全共享，因此 DNS、UDP 等共同机制不重复运行整套。
    for field in three.keys() | four.keys():
        if field not in {'proxies', 'proxy-providers', 'proxy-groups', 'sub-rules'}:
            assert three.get(field) == four.get(field), ('双模型共同设置不一致', field)
    assert three['sub-rules']['分流-业务规则'] == four['sub-rules']['分流-业务规则']
    assert three['sub-rules']['分流-探针分类'][2:] == four['sub-rules']['分流-探针分类'][2:]
    other = {p['name']: p for p in four['proxies']}
    for p in three['proxies']:
        assert p == other[p['name']], p['name']
    for name, provider in three['proxy-providers'].items():
        assert provider == four['proxy-providers'][name], name


NODE_CASES = {
        "Airport_01": [
            ("HongKong 01", {"hk1"}),
            ("HongKong 02", set()), ("HongKong 03", set()),
            ("HongKong 04", set()), ("HongKong 05", set()),
            ("Hong Kong 06", {"hk1"}),
            ("香港 0.3x", set()), ("香港 0.5x", {"hk1"}),
            ("香港 5x", set()), ("香港 BETA", set()),
            ("日本 MITM 1x", set()), ("美国 0.1x", set()),
            ("HK01", {"hk1"}), ("JP01", {"jp1"}),
            ("HK-06", {"hk1"}), ("JP-01", {"jp1"}),
            ("XHK01", set()), ("JP01test", set()),
        ],
        "Airport_02": [
            ("HongKong 02 1x", {"hk2"}), ("HK01 1x", {"hk2"}),
            ("香港 0.3x", set()), ("香港 0.5x", {"hk2"}),
            ("香港 4.9x", {"hk2"}), ("香港 5x", set()),
            ("香港 BETA 1x", set()), ("香港 wcloud 1x", set()),
            ("香港 traffic 1x", set()), ("日本 1x", {"jp2"}),
            ("JP01 1x", {"jp2"}), ("JP01test", set()),
            ("新加坡 CTCU 1x", {"sg2"}), ("美国 0.1x", set()),
            ("美国 1x", {"us2"}), ("台湾 1x", {"tw2"}),
            ("德国普通", set()),
        ],
        "Airport_03": [
            ("CTCU|日本01", set()), ("日本02|CTCU|0.5x", set()),
            ("日本03|BGP|CTCU", set()),
            ("日本06 CTCU 1x", set()), ("日本07-CTCU-1x", set()),
            ("新加坡05【CTCU】1x", set()), ("新加坡06_CTCU_1x", set()),
            ("CTCUCM|日本04", {"jp3"}),
            ("日本05|CTCUCM", {"jp3"}),
            ("JP01 CTCUCM 1x", {"jp3"}),
            ("SG01 CTCUCM 1x", {"sg3"}),
            ("US01 CTCU 0.1x", {"us3"}),
            ("USA01 0.1x", {"us3"}),
            ("RUS01", set()), ("US01test", set()),
            ("CTCU|新加坡01", set()), ("新加坡02|CTCU|1x", set()),
            ("新加坡03|BGP|CTCU", set()),
            ("新加坡04|CTCUCM", {"sg3"}),
            ("CTCU|美国01|0.1x", {"us3"}),
            ("美国02|CTCU|0.1x", {"us3"}),
            ("美国 0.1x", {"us3"}),
            ("美国 BETA", set()), ("美国 wcloud", set()), ("美国 traffic", set()),
            ("美国 5x", set()), ("美国 5.5倍", set()), ("美国 10x", set()),
            ("美国 4.9x", {"us3"}),
            ("日本 0.3x", set()), ("日本 0.5x", {"jp3"}),
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
        for provider in source['proxy-providers']:
            original_cases = NODE_CASES[provider]
            cases = original_cases + [('日本 mitm home 1x', set()), ('日本 PoRnHuB 1x', set()),
                                      ('台湾 MITM 1x', set()), ('美国 pornhub 0.1x', set())]
            p = copy.deepcopy(source['proxy-providers'][provider])
            prefix = p['override']['additional-prefix']
            proxies = []
            for index, (raw, memberships) in enumerate(cases):
                name = prefix + raw + p['override'].get('additional-suffix', '')
                manual.add(name)
                capabilities[name] = index % 2 == 0
                for membership in memberships:
                    expected.setdefault(membership, set()).add(name)
                if not re.search('MITM|pornhub', raw, re.I):
                    expected.setdefault('ordinary', set()).add(name)
                    if provider == 'Airport_02':
                        expected.setdefault('home', set()).add(name)
                else:
                    expected.setdefault('special', set()).add(name)
                if provider == 'Airport_04' and not re.search('MITM|pornhub', raw, re.I):
                    expected.setdefault('reserve', set()).add(name)
                if (raw.startswith('日本') and re.search('MITM|pornhub', raw, re.I)) or raw in {
                        '香港 0.5x', '香港 0.3x', '日本 0.3x', '日本 0.5x', '香港 0.1x', '日本02|CTCU|0.5x'}:
                    expected.setdefault('low', set()).add(name)
                proxies.append(dict(name=raw, type='socks5', server='127.0.0.1', port=9, udp=capabilities[name]))
            for notice in ('剩余流量: 100 GB', '套餐到期: 2027-01-01', 'Email: support@example.invalid', 'Expired'):
                proxies.append(dict(name=notice, type='socks5', server='127.0.0.1', port=9))
            file = Path(directory) / (provider + '.json')
            file.write_text(json.dumps({'proxies': proxies}))
            p.update(type='file', path=str(file))
            p.pop('url')
            p['health-check'] = {'enable': False}
            providers[provider] = p
        subjects = {'下载': 'ordinary', '自建/家宽节点': 'home', '台湾限定': 'ordinary',
                    'Google FCM': 'ordinary', 'OneDrive': 'ordinary', 'GLOBAL': 'ordinary',
                    'AI': 'ordinary', '金融': 'ordinary', 'Talkatone': 'ordinary',
                    '全部节点': 'manual', '低倍率/MITM节点': 'low'}
        for family in FAMILIES:
            for airport, region, membership in ((1, '香港', 'hk1'), (1, '日本', 'jp1'),
                    (3, '日本', 'jp3'), (3, '新加坡', 'sg3'), (3, '美国', 'us3')):
                subjects[pool_name(airport, region, family)] = membership
            if 'Airport_02' in source['proxy-providers']:
                for region, membership in (('香港', 'hk2'), ('日本', 'jp2'), ('新加坡', 'sg2'), ('美国', 'us2')):
                    subjects[pool_name(2, region, family)] = membership
                if family != 'TG':
                    subjects[pool_name(2, '台湾', family)] = 'tw2'
            subjects[f'机场名称4-备用-{family}'] = 'reserve'
            if family != 'TG':
                subjects[f'台湾-机场名称1优先-{family}'] = 'tw4'
        for family in ('Google', 'CF'):
            subjects[f'专用-机场名称1-日本-{family}'] = 'jp1'
            if 'Airport_02' in source['proxy-providers']:
                subjects[f'专用-机场名称2-香港-{family}'] = 'hk2'
        groups = []
        for original in source['proxy-groups']:
            if original['name'] in subjects:
                g = copy.deepcopy(original)
                # Isolate provider candidates; menu graph is validated separately.
                g.pop('proxies', None)
                if g['name'] in ('全部节点', '低倍率/MITM节点'):
                    g['proxies'] = ['REJECT']
                g.update(url='http://127.0.0.1:9/probe', interval=86400, lazy=True)
                groups.append(g)
        config = rt.base(source)
        config.update(proxies=[], **{'sub-rules': {}, 'rules': ['MATCH,REJECT'],
                      'proxy-providers': providers, 'proxy-groups': groups})
        rt.start(config)
        F.until(lambda: set(rt.group('下载')['all']) == expected['ordinary'])
        actual = rt.api('/proxies')['proxies']
        for name, membership in subjects.items():
            want = manual.copy() if membership == 'manual' else expected[membership].copy()
            if name in ('全部节点', '低倍率/MITM节点'):
                want.add('REJECT')
                assert actual[name]['now'] == 'REJECT'
            assert set(actual[name]['all']) == want, (name, set(actual[name]['all']) ^ want)
        special = '[机场名称1]日本 mitm home 1x'
        rt.select('全部节点', special)
        rt.select('低倍率/MITM节点', special)
        rt.reload(config)
        assert rt.group('全部节点')['now'] == special
        assert rt.group('低倍率/MITM节点')['now'] == special
        # An old raw special-node selection must not bypass the new admission filter.
        unfiltered = copy.deepcopy(config)
        next(g for g in unfiltered['proxy-groups'] if g['name'] == '下载').pop('filter')
        rt.reload(unfiltered)
        rt.select('下载', special)
        rt.reload(config)
        assert rt.group('下载')['now'] != special
        assert rt.group('下载')['now'] in expected['ordinary']
        assert rt.group('全部节点')['now'] == special
        # Deleted manual selections return to explicit REJECT, even with other nodes left.
        path = Path(directory) / 'Airport_01.json'
        data = json.loads(path.read_text())
        data['proxies'] = [n for n in data['proxies'] if n['name'] != '日本 mitm home 1x']
        path.write_text(json.dumps(data))
        rt.api('/providers/proxies/Airport_01', 'PUT')
        F.until(lambda: rt.group('全部节点')['now'] == 'REJECT')
        assert rt.group('低倍率/MITM节点')['now'] == 'REJECT'
        actual_nodes = {n['name']: n for p in rt.api('/providers/proxies')['providers'].values() for n in p['proxies']}
        for name, udp in capabilities.items():
            if name != special:
                assert actual_nodes[name]['udp'] == udp, name
    print('PASS: 普通/专用池准入、特殊节点手选、公告过滤及 UDP 声明', flush=True)


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
                enable=True, url=LOCAL['Google'], interval=86400, timeout=5000, lazy=False, **{'expected-status': 204})})
        config['proxy-groups'] = copy.deepcopy(source['proxy-groups'])
        for g in config['proxy-groups']:
            if 'url' in g:
                g['url'] = LOCAL[next(f for f in FAMILIES if URLS[f] == g['url'])]
            if g['type'] != 'select':
                g['interval'] = 86400
        config['rules'] = ['MATCH,通用代理']
        # URL/filter 注册发生在组类型分派之前；临时 select/interval=0
        # 保留同一注册图，同时关闭物理及兼容 provider 的启动异步检查。
        count_config = copy.deepcopy(config)
        for provider in count_config['proxy-providers'].values():
            provider['health-check']['enable'] = False
        for group in count_config['proxy-groups']:
            group.update(type='select', interval=0)
        count_config['rules'] = ['MATCH,REJECT']
        rt.start(count_config)
        def loaded():
            providers = rt.api('/providers/proxies')['providers']
            return all(provider in providers and
                       {n['name'] for n in providers[provider]['proxies']} == {n['name'] for n in values}
                       for provider, values in nodes.items())
        F.until(loaded)
        expected = {(p, f): {n['name'] for n in nodes[p]} if f == 'Google' else set()
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
        with rt.http.lock:
            before = {n: dict(s.counts) for n, s in rt.http.nodes.items()}
        assert not any(before.values()), before
        for provider in nodes:
            rt.api('/providers/proxies/' + provider + '/healthcheck')
        with rt.http.lock:
            after = {n: dict(s.counts) for n, s in rt.http.nodes.items()}
        for provider, values in nodes.items():
            for node in values:
                name = node['name']
                for f in FAMILIES:
                    delta = after[name].get(PATHS[f], 0) - before[name].get(PATHS[f], 0)
                    assert delta == int(name in expected[provider, f]), (name, f, delta)
        rt.reload(config)
        fast = '[机场名称3]日本 fast 1x'
        F.until(lambda: all(rt.group(pool_name(3, '日本', f))['now'] == fast for f in FAMILIES))
        def probe(name, family):
            return rt.probe(name, LOCAL[family], STATUS[family])
        pairs = [(pool_name(a, r, f), f) for f in FAMILIES for a in (3, 1)
                 for r in ('日本', '新加坡', '香港', '美国')]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda pair: probe(*pair), pairs))
        for family in FAMILIES:
            for name, node in rt.http.nodes.items():
                if name.startswith('[机场名称3]'):
                    node.statuses[PATHS[family]] = 503
            rt.api('/providers/proxies/Airport_03/healthcheck')
            children = [name for name, f in pairs if f == family and name.startswith('机场名称3-')]
            for child in children:
                probe(child, family)
            root = f'机场名称3优先-{family}'
            assert rt.group(root)['now'] == pool_name(1, '日本', family), family
            for other in FAMILIES:
                if other != family:
                    assert rt.group(f'机场名称3优先-{other}')['now'].startswith('机场名称3-'), other
            for node in rt.http.nodes.values():
                node.statuses.clear()
            rt.api('/providers/proxies/Airport_03/healthcheck')
            for child in children:
                assert probe(child, family)
            assert rt.group(root)['now'] == children[0]
        for status in (403, 429, 503):
            rt.http.nodes[fast].statuses[PATHS['GitHub']] = status
            assert not probe(fast, 'GitHub'), status
            assert probe(fast, 'Google')
        rt.http.nodes[fast].statuses.clear()
        rt.http.nodes[fast].delays[PATHS['GitHub']] = 5.3
        assert not probe(fast, 'GitHub'), '超时'
        rt.http.nodes[fast].delays.clear()
        assert not rt.probe(fast, 'https://tls.invalid/3', 200), 'TLS 握手失败'
        assert probe(fast, 'GitHub')
        # TG 必须精确匹配 501；测速 API 返回延迟不等于对应 URL 健康。
        assert probe(fast, 'TG')
        for status in (200, 403, 429, 503):
            rt.http.nodes[fast].statuses[PATHS['TG']] = status
            assert not probe(fast, 'TG'), status
            assert probe(fast, 'Google')
        rt.http.nodes[fast].statuses.clear()
        rt.http.nodes[fast].delays[PATHS['TG']] = 5.3
        assert not probe(fast, 'TG'), 'TG 超时'
        rt.http.nodes[fast].delays.clear()
        assert probe(fast, 'TG')
        # 同机场先换地区；通用探针仍健康时，TG 的日本故障不能阻止香港回退。
        for name, node in rt.http.nodes.items():
            if name.startswith('[机场名称1]日本'):
                node.statuses[PATHS['TG']] = 503
        rt.api('/providers/proxies/Airport_01/healthcheck')
        probe(pool_name(1, '日本', 'TG'), 'TG')
        probe(pool_name(1, '香港', 'TG'), 'TG')
        assert rt.group('机场名称1优先-TG')['now'] == pool_name(1, '香港', 'TG')
        assert rt.group('机场名称1优先-Google')['now'] == pool_name(1, '日本', 'Google')
        for node in rt.http.nodes.values():
            node.statuses.clear()
        rt.api('/providers/proxies/Airport_01/healthcheck')
        assert probe(pool_name(1, '日本', 'TG'), 'TG')
        assert rt.group('机场名称1优先-TG')['now'] == pool_name(1, '日本', 'TG')
        # 两种探针分别失败：默认不更换探针，用户可以主动选择 CF。
        scoped = '专用-机场名称1-日本-Google'
        cf_pool = '专用-机场名称1-日本-CF'
        ordinary = '机场名称1-日本-Google'
        private_choice, ordinary_choice = '[机场名称1]日本 slow 1x', '[机场名称1]日本 fast 1x'
        rt.select(scoped, private_choice)
        rt.select(ordinary, ordinary_choice)
        assert rt.group(scoped)['now'] == private_choice
        assert rt.group(ordinary)['now'] == ordinary_choice
        rt.select(scoped, ordinary_choice)
        for failed, healthy in [('CF', 'Google'), ('Google', 'CF')]:
            for name, node in rt.http.nodes.items():
                if name.startswith('[机场名称1]日本'):
                    node.statuses[PATHS[failed]] = 503
            assert not probe('专用-' + pool_name(1, '日本', failed), failed)
            assert probe('专用-' + pool_name(1, '日本', healthy), healthy)
            for business_name in ('AI', '金融', 'Talkatone'):
                assert rt.group(business_name)['now'] == scoped
            if healthy == 'CF':
                rt.select('AI', cf_pool)
                assert rt.group('AI')['now'] == cf_pool
                assert rt.group('金融')['now'] == scoped
                rt.select('AI', scoped)
            for node in rt.http.nodes.values():
                node.statuses.clear()
            assert probe('专用-' + pool_name(1, '日本', failed), failed)
        rt.select('金融', fast)
        rt.select('AI', cf_pool)
        for restart in (False, True):
            if restart:
                rt.stop()
                rt.start(config)
            else:
                rt.reload(config)
            F.until(lambda: rt.group('金融')['now'] == fast)
            assert rt.group('AI')['now'] == cf_pool and rt.group('Talkatone')['now'] == scoped
        rt.select('AI', scoped)
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
    'github.com': '下载', 'raw.githubusercontent.com': '下载', 'gitbook.com': '下载',
    'codeload.github.com': '下载', 'release-assets.githubusercontent.com': '下载', 'aur.archlinux.org': '下载',
    'cloudflare.com': '通用代理', 'example.pages.dev': '通用代理', 'cf-china.info': 'DIRECT',
    'unpkg.com': '下载', 'registry-1.docker.io': '下载', 'huggingface.co': '下载',
    'google.com': 'Google', 'services.googleapis.cn': 'Google', 'fcm.googleapis.com': 'Google',
    'microsoft.com': 'Microsoft', 'bilibili.tv': '哔哩东南亚', 'gamer.com.tw': '台湾限定',
    'bilibili.com': '哔哩哔哩', 'ad.doubleclick.net': '隐私拦截',
    'mtalk.google.com': 'Google FCM', 'onedrive.live.com': 'OneDrive', 'netflix.com': 'Netflix',
}
DEFAULTS = {
    'google.com': '机场名称3优先-Google',
    'telegram.org': '机场名称1优先-TG', '149.154.167.51': '机场名称1优先-TG',
    'wise.com': '专用-机场名称1-日本-Google', 'talkatone.com': '专用-机场名称1-日本-Google',
    'github.com': '机场名称3优先-GitHub', 'raw.githubusercontent.com': '机场名称3优先-GitHub',
    'codeload.github.com': '机场名称3优先-GitHub', 'cloudflare.com': '机场名称1优先-CF',
    'bilibili.tv': '新加坡-机场名称1优先-Google', 'gamer.com.tw': '台湾-机场名称1优先-Google',
}
FOUR_DEFAULTS = {**DEFAULTS, 'wise.com': '专用-机场名称2-香港-Google',
                 'talkatone.com': '专用-机场名称2-香港-Google', 'netflix.com': '机场名称2优先-Google'}
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
    cases = BUSINESSES
    four = config_name == FOUR_CONFIG
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
        for host, port, expected in [('8.8.8.8', 5228, 'Google FCM'), ('203.208.40.1', 5230, 'Google FCM'),
                ('8.8.8.8', 443, 'Google'), ('1.1.1.1', 5228, '通用代理'),
                ('45.121.184.1', 5230, 'DIRECT')]:
            assert rt.request(host, port) == expected, (config_name, host, port, expected)
        # 只恢复被业务见证覆盖的 select，其他辅助选择保持可追踪标签。
        for name in set(cases.values()) - {'DIRECT', '隐私拦截', 'AI'}:
            choice = selections[name]
            rt.select(name, 'fixture-DIRECT' if choice == 'DIRECT' else choice)
        for host, choices in (FOUR_DEFAULTS if four else DEFAULTS).items():
            actual = rt.request(host)
            assert actual == choices, (config_name, host, choices, actual)
        rt.select('Telegram', '自建/家宽节点')
        assert rt.request('telegram.org') == '自建/家宽节点'
        rt.select('Telegram', 'fixture-Telegram')
        assert rt.request('149.154.167.51') == 'Telegram'
        rt.select('Telegram', selections['Telegram'])
        for name in ('AI', '金融', 'Talkatone'):
            scope = '专用-机场名称2-香港-Google' if four and name != 'AI' else '专用-机场名称1-日本-Google'
            rt.select(name, scope)
        assert rt.request('chatgpt.com') == '专用-机场名称1-日本-Google'
        rt.select('AI', '自建/家宽节点')
        assert rt.request('chatgpt.com') == '自建/家宽节点'
        for name, host in [('金融', 'wise.com'), ('Talkatone', 'talkatone.com')]:
            scope = '专用-机场名称2-香港-Google' if four else '专用-机场名称1-日本-Google'
            assert rt.group(name)['now'] == scope
            assert rt.request(host) == scope
    print(f'PASS: {config_name} 关键业务、默认出口与 Tunnel/FCM 边界', flush=True)


def routing(source, mihomo, rules_dir, four=False):
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
                if name.startswith('机场名称3优先-'):
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
        cases = dict(zip(('www.google.com', 'dash.cloudflare.com', 'github.com', 'telegram.org'), FAMILIES))
        entries = [('通用代理', '机场名称1优先', '机场名称1优先'),
                   ('通用代理', '机场名称3优先', '机场名称3优先'),
                   ('Telegram', '机场名称1优先', '机场名称1优先'),
                   ('Telegram', '机场名称3优先', '机场名称3优先'),
                   ('Telegram', '香港-机场名称1优先', '香港-机场名称1优先'),
                   ('通用代理', '日本-机场名称1优先', '日本-机场名称1优先'),
                   ('Google', '台湾-机场名称3优先', '台湾-机场名称3优先'),
                   ('AI', '机场名称1优先', '机场名称1优先'),
                   ('金融', '日本-机场名称3优先', '日本-机场名称3优先'),
                   ('Talkatone', '美国-机场名称1优先', '美国-机场名称1优先'),
                   ('台湾限定', '日本-机场名称3优先', '日本-机场名称3优先'),
                   ('下载', '机场名称3优先', '机场名称3优先')]
        if four:
            entries = [('Telegram', f'机场名称{a}优先', f'机场名称{a}优先') for a in (1, 2, 3)] + [
                ('Telegram', '香港-机场名称2优先', '香港-机场名称2优先'),
                ('金融', '日本-机场名称2优先', '日本-机场名称2优先')]
        for business_name, entry, target in entries:
            config['rules'] = [f'NETWORK,tcp,{business_name}', f'NETWORK,udp,{business_name}', 'MATCH,DIRECT']
            rt.reload(config)
            rt.select(business_name, entry)
            for host, family in [*cases.items(), ('149.154.171.5', 'TG')]:
                tg_policies = ('机场名称1优先', '机场名称2优先', '机场名称3优先') if four else ('机场名称1优先', '机场名称3优先')
                if family == 'TG' and target not in tg_policies:
                    family = 'Google'
                expected = f'{target}-{family}'
                actual = rt.request(host)
                assert actual == expected, (entry, host, expected, actual)
        config['rules'] = ['NETWORK,tcp,通用代理', 'NETWORK,udp,通用代理', 'MATCH,DIRECT']
        rt.reload(config)
        if four:
            rt.select('通用代理', '机场名称2优先')
            code, ips = F.query(dns_port, 'telegram.org')
            assert code == 0 and ips[0].startswith('198.18.'), ips
            assert rt.request(ips[0]) == '机场名称2优先-TG'
            rt.api('/configs', 'PATCH', {'mode': 'global'})
            rt.select('GLOBAL', '香港-机场名称2优先-Google')
            assert rt.request('github.com') == '香港-机场名称2优先-Google'
            assert rt.request('telegram.org') == '香港-机场名称2优先-Google'
            print('PASS: 四机场三种优先/TG、固定地区、Fake-IP 与 GLOBAL', flush=True)
            return
        rt.select('通用代理', '机场名称3优先')
        for host, family in [('api.github.com', 'GitHub'), ('release-assets.githubusercontent.com', 'GitHub'), ('raw.githubusercontent.com', 'GitHub'), ('codeload.github.com', 'GitHub'),
                ('foo.github.io', 'GitHub'), ('gitbook.com', 'Google'), ('foo.pages.dev', 'CF'),
                ('unknown-cf.fixture.test', 'CF'), ('dns-failed.fixture.test', 'Google')]:
            assert rt.request(host) == f'机场名称3优先-{family}', (host, family)
        # 每类一组 UDP 正反例，不再对同类所有域名重复等待超时。
        for host, family in cases.items():
            name = f'机场名称3优先-{family}'
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
        name = '机场名称3优先-CF'
        rt.select(name, 'fixture-' + name + '-udp')
        assert F.udp_request(rt.mixed, ips[0], sockets) == name
        code, ips = F.query(dns_port, 'telegram.org')
        assert code == 0 and ips[0].startswith('198.18.'), ips
        assert rt.request(ips[0]) == '机场名称3优先-TG'
        rt.api('/configs', 'PATCH', {'mode': 'global'})
        rt.select('GLOBAL', '日本-机场名称3优先-Google')
        assert rt.request('github.com') == '日本-机场名称3优先-Google'
        assert rt.request('telegram.org') == '日本-机场名称3优先-Google'
    print('PASS: 四类分类、TG 作用域、固定地区/下载边界、UDP、Fake-IP 与 GLOBAL', flush=True)


def four_airport_health(source, mihomo):
    # 只覆盖新增机场和第二个敏感地区；状态码/超时等共同机制由三机场覆盖。
    with tempfile.TemporaryDirectory(prefix='mihomo-four-') as directory, F.Runtime(
            directory, mihomo, {PATHS[f]: STATUS[f] for f in FAMILIES}) as rt:
        config = rt.base(source)
        config['proxy-providers'], provider_nodes = {}, {}
        samples = {'Airport_01': ('日本 fast 1x',),
                   'Airport_02': ('香港 fast 1x', '香港 slow 1x', '日本 fast 1x', '台湾 fast 1x'),
                   'Airport_03': ('日本 fast 1x',), 'Airport_04': ('日本 fast 1x',)}
        for provider, values in samples.items():
            nodes = []
            for raw in values:
                name = f'[机场名称{int(provider[-2:])}]{raw}' + (' [家宽]' if provider == 'Airport_02' else '')
                node = rt.proxy(name)
                node['name'] = raw  # 内核使用真实 provider override 加前后缀。
                nodes.append(node)
                delay = .01 if '日本' in raw else .04 if 'fast' in raw else .12
                rt.http.nodes[name].delays.update({PATHS[f]: delay for f in FAMILIES})
            provider_nodes[provider] = nodes
            path = Path(directory) / (provider + '.json')
            path.write_text(json.dumps({'proxies': nodes}))
            p = copy.deepcopy(source['proxy-providers'][provider])
            p.pop('url')
            p.update(type='file', path=str(path))
            p['health-check'].update(url=LOCAL['Google'], interval=86400)
            config['proxy-providers'][provider] = p
        config['proxy-groups'] = copy.deepcopy(source['proxy-groups'])
        for g in config['proxy-groups']:
            if 'url' in g:
                g['url'] = LOCAL[next(f for f in FAMILIES if URLS[f] == g['url'])]
            if g['type'] != 'select':
                g['interval'] = 86400
        config['rules'] = ['MATCH,金融']
        rt.start(config)
        fast, slow = '[机场名称2]香港 fast 1x [家宽]', '[机场名称2]香港 slow 1x [家宽]'
        scoped, scoped_cf = '专用-机场名称2-香港-Google', '专用-机场名称2-香港-CF'
        F.until(lambda: all(rt.group(pool_name(2, '香港', f))['now'] == fast for f in FAMILIES))
        assert rt.group('AI')['now'] == '专用-机场名称1-日本-Google'
        assert rt.group('金融')['now'] == rt.group('Talkatone')['now'] == scoped
        for business_name in ('Netflix', 'Disney+', 'HBO', 'Prime Video', 'Spotify', 'Reddit'):
            assert rt.group(business_name)['now'] == '机场名称2优先', business_name
        def probe(name, family):
            return rt.probe(name, LOCAL[family], STATUS[family])
        for family in FAMILIES:
            # fallback 检查子组包装器的 URL 健康记录，不会从子组 now 推导存活状态。
            for airport, region in ((1, '日本'), (2, '香港'), (2, '日本'), (3, '日本')):
                child = pool_name(airport, region, family)
                try:
                    F.until(lambda: probe(child, family))
                except AssertionError as error:
                    raise AssertionError(('四机场初始子组探测失败', child, rt.group(child))) from error
            for region in ('新加坡', '美国'):
                assert not probe(pool_name(2, region, family), family)
            for preferred, first in ((1, 1), (2, 2), (3, 3)):
                region = '香港' if first == 2 else '日本'
                root = f'机场名称{preferred}优先-{family}'
                expected = pool_name(first, region, family)
                try:
                    F.until(lambda: rt.group(root)['now'] == expected)
                except AssertionError as error:
                    raise AssertionError(('四机场初始优先未收敛', root, expected, rt.group(root))) from error
            if family != 'TG':
                assert rt.group(f'台湾-机场名称2优先-{family}')['now'] == pool_name(2, '台湾', family)
        # 每个 URL 独立失败：香港→日本，再跨机场，恢复后回到香港。
        for family in FAMILIES:
            for name, node in rt.http.nodes.items():
                if name.startswith('[机场名称2]香港'):
                    node.statuses[PATHS[family]] = 503
            rt.api('/providers/proxies/Airport_02/healthcheck')
            assert not probe(pool_name(2, '香港', family), family)
            assert rt.group(f'机场名称2优先-{family}')['now'] == pool_name(2, '日本', family)
            for other in FAMILIES:
                if other != family:
                    assert rt.group(f'机场名称2优先-{other}')['now'] == pool_name(2, '香港', other)
            for name, node in rt.http.nodes.items():
                if name.startswith('[机场名称2]'):
                    node.statuses[PATHS[family]] = 503
            rt.api('/providers/proxies/Airport_02/healthcheck')
            assert not probe(pool_name(2, '日本', family), family)
            assert rt.group(f'机场名称2优先-{family}')['now'] == pool_name(1, '日本', family)
            for node in rt.http.nodes.values():
                node.statuses.pop(PATHS[family], None)
            rt.api('/providers/proxies/Airport_02/healthcheck')
            assert probe(pool_name(2, '香港', family), family)
            assert probe(pool_name(2, '日本', family), family)
            assert rt.group(f'机场名称2优先-{family}')['now'] == pool_name(2, '香港', family)
        ordinary = pool_name(2, '香港', 'Google')
        rt.select(ordinary, fast)
        rt.select(scoped, slow)
        rt.select('金融', scoped_cf)
        for restart in (False, True):
            if restart:
                rt.stop()
                rt.start(config)
            else:
                rt.reload(config)
            F.until(lambda: rt.group('金融')['now'] == scoped_cf)
            assert rt.group('Talkatone')['now'] == scoped
            assert rt.group('AI')['now'] == '专用-机场名称1-日本-Google'
            assert rt.group(scoped)['now'] == slow and rt.group(ordinary)['now'] == fast
        rt.select('AI', scoped_cf)
        assert rt.group('Talkatone')['now'] == scoped
        rt.select('AI', '专用-机场名称1-日本-Google')
        rt.select('金融', fast)
        for restart in (False, True):
            if restart:
                rt.stop()
                rt.start(config)
            else:
                rt.reload(config)
            F.until(lambda: rt.group('金融')['now'] == fast)
        path = Path(directory) / 'Airport_02.json'
        nodes = [n for n in provider_nodes['Airport_02'] if n['name'] != '香港 fast 1x']
        path.write_text(json.dumps({'proxies': nodes}))
        rt.api('/providers/proxies/Airport_02', 'PUT')
        F.until(lambda: rt.group('金融')['now'] == scoped)
        path.write_text(json.dumps({'proxies': [n for n in nodes if not n['name'].startswith('香港')]}))
        rt.api('/providers/proxies/Airport_02', 'PUT')
        for name in (scoped, scoped_cf):
            F.until(lambda: rt.group(name)['all'] == ['REJECT'] and rt.group(name)['now'] == 'REJECT')
        assert rt.group('金融')['now'] == rt.group('Talkatone')['now'] == scoped
        assert rt.group('AI')['now'] == '专用-机场名称1-日本-Google'
        assert probe(pool_name(2, '日本', 'Google'), 'Google')
        # URLTest 各组分别缓存 fastNode 10 秒；收敛后还须复测子组包装器，
        # fallback 才能依其 URL 健康记录跳过空池。订阅更新不会直接更新该记录。
        def empty():
            state = rt.group(ordinary)
            return state['all'] == ['REJECT'] and state['now'] == 'REJECT'
        try:
            F.until(empty)
            assert not probe(ordinary, 'Google'), rt.group(ordinary)
            F.until(lambda: rt.group('机场名称2优先-Google')['now'] == pool_name(2, '日本', 'Google'))
        except AssertionError as error:
            raise AssertionError(('四机场空池回退未收敛', rt.group(ordinary),
                                  rt.group('机场名称2优先-Google'))) from error
    print('PASS: 四机场地区/机场回退、探针隔离、专用与普通池隔离、缓存及空池', flush=True)


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
    subprocess.run(['ruby', str(ROOT / 'scripts/build-config.rb'), '--check'], check=True)
    sources = {name: F.load(ROOT / name) for name in CONFIGS}
    command = ['ruby', str(ROOT / 'scripts/validate-rules.rb')]
    for name in CONFIGS:
        command.extend(['--config', str(ROOT / name)])
    subprocess.run(command, env={**os.environ, 'MIHOMO_BIN': args.mihomo}, check=True, timeout=150)
    for name, source in sources.items():
        static(source, name)
    common_settings(sources[PRIMARY_CONFIG], sources[FOUR_CONFIG])
    if args.suite == 'static':
        return
    with tempfile.TemporaryDirectory(prefix='mihomo-rules-') as directory:
        rules_dir = args.rules_dir or Path(directory) / 'snapshot'
        F.snapshot([sources[name] for name in ACTIVE_CONFIGS], rules_dir)
        business(sources[PRIMARY_CONFIG], PRIMARY_CONFIG, args.mihomo, rules_dir)
        routing(sources[PRIMARY_CONFIG], args.mihomo, rules_dir)
        business(sources[FOUR_CONFIG], FOUR_CONFIG, args.mihomo, rules_dir)
        routing(sources[FOUR_CONFIG], args.mihomo, rules_dir, four=True)
        if args.suite == 'full':
            for name in ACTIVE_CONFIGS:
                node_filters(sources[name], args.mihomo)
            health(sources[PRIMARY_CONFIG], args.mihomo)
            four_airport_health(sources[FOUR_CONFIG], args.mihomo)
            dns_policy(sources[PRIMARY_CONFIG], args.mihomo)
    print(f'PASS: {args.suite}', flush=True)


if __name__ == '__main__':
    main()
