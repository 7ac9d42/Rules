#!/usr/bin/env python3
"""新版配置检查：static 为离线基础检查；smoke 按需验证改变的运行机制。"""
import argparse
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import tempfile

import mihomo_fixture as F

CONFIGS = ('configfull_v2.yaml', 'configfull_v2_4.yaml')
ENTRY = ['SUB-RULE,(OR,((NETWORK,tcp),(NETWORK,udp))),分流-业务规则', 'MATCH,REJECT']
PRIVATE = '专用-机场名称1-日本'


def static(source, four, policy):
    probes = policy['probes']
    assert set(probes) == {'CF', 'TG'}
    groups = {g['name']: g for g in source['proxy-groups']}
    assert len(groups) == len(source['proxy-groups']), '重复组名'
    assert not any('-CF' in name or '优先' in name for name in groups)
    assert source['proxies'] == [] and source['rules'] == ENTRY
    assert set(source['sub-rules']) == {'分流-业务规则'}
    assert source['unified-delay'] is True
    providers = source['proxy-providers']
    assert set(providers) == {'Airport_01', 'Airport_03', 'Airport_04'} | ({'Airport_02'} if four else set())
    private = {PRIVATE} | ({'专用-机场名称2-香港'} if four else set())
    known = set(groups) | {'DIRECT', 'REJECT', 'REJECT-DROP'}
    for name, g in groups.items():
        choices = g.get('proxies', [])
        assert set(choices) <= known and len(choices) == len(set(choices)), name
        assert set(g.get('use', [])) <= set(providers), name
        assert g['empty-fallback'] == 'REJECT', name
        assert not set(choices) & private or name in ('AI', '金融', 'Talkatone'), name
        if g['type'] != 'select':
            probe = probes['TG' if name.endswith('-TG') else 'CF']
            assert (g['url'], g['expected-status']) == (probe['url'], probe['expected-status']), name
        if g['type'] == 'select' and name != 'Telegram代理' and not name.endswith('-TG'):
            assert not any(n.endswith('-TG') for n in choices), name
    done = set()
    def visit(name, path=()):
        assert name not in path, ('循环引用', path, name)
        if name in done or name not in groups:
            return
        for child in groups[name].get('proxies', []):
            visit(child, (*path, name))
        done.add(name)
    for name in groups:
        visit(name)
    for provider in providers.values():
        assert (provider['health-check']['url'], provider['health-check']['expected-status']) == (probes['CF']['url'], probes['CF']['expected-status'])
    for name, business in policy['businesses'].items():
        if 'region' in business:
            assert groups[name]['type'] == 'select' and 'proxies' not in groups[name], name
            assert groups[name]['use'] == [p for p in business['use'] if p in providers], name
        else:
            default = business.get('four-default', business['default']) if four else business['default']
            assert groups[name]['proxies'][0] == default, name
    model = policy['models']['four-airports' if four else 'three-airports']
    for name in model['priority-order']:
        for suffix in ('', '-TG'):
            assert groups[name + suffix]['type'] == 'select' and groups[name + suffix]['hidden'] is False
    assert '日本-机场名称1' in groups['Telegram代理']['proxies']
    assert 'DIRECT' not in groups['DNS代理']['proxies']
    assert groups['规则更新']['proxies'][-1] == 'DIRECT'
    for name in private:
        g, shared = groups[name], groups[name.removeprefix('专用-')]
        home = policy['independent-pools'][name].get('home-pool')
        assert g['type'] == ('fallback' if home else 'url-test') and g['hidden'] is False, name
        assert (g['use'], g['filter'], g['url']) == (shared['use'], shared['filter'], shared['url']), name
        if home:
            assert g['proxies'] == [home] and groups[home]['type'] == 'url-test' and groups[home]['hidden'] is True
            assert groups[home]['use'] == g['use']
    assert 'RULE-SET,cf_sensitive_domain,AI' in source['sub-rules']['分流-业务规则']


def routing(source, mihomo):
    # 保留真实菜单与主入口，只替换网络依赖；域名覆盖由维护源对照验收。
    with tempfile.TemporaryDirectory(prefix='mihomo-v2-route-') as directory, ExitStack() as sockets, F.Runtime(directory, mihomo) as rt:
        config = rt.base(source)
        config['rule-providers'], config['proxy-groups'] = {}, []
        for original in source['proxy-groups']:
            name = original['name']
            if original['type'] == 'select':
                g = copy.deepcopy(original)
                for field in ('use', 'filter', 'exclude-filter'):
                    g.pop(field, None)
                g.setdefault('proxies', ['REJECT'])
            else:
                label = 'fixture-' + name
                config['proxies'].append(rt.proxy(label, name))
                g = dict(name=name, type='select', proxies=[label])
            if name in ('机场名称3', '机场名称1'):
                label = 'udp-' + name
                config['proxies'].append(rt.udp_proxy(label, name))
                g['proxies'].append(label)
            config['proxy-groups'].append(g)
        config['sub-rules']['分流-业务规则'] = [
            'DOMAIN,telegram.fixture.test,Telegram代理', 'DOMAIN,ai.fixture.test,AI',
            'DOMAIN,speedtest.fixture.test,Speedtest',
            'DOMAIN,udp.fixture.test,默认代理', 'DOMAIN,udp.fixture.test,下载', 'MATCH,默认代理']
        config['hosts'] = {'udp.fixture.test': '203.0.113.8'}
        bootstrap = rt.server(F.DNSHandler, socketserver.UDPServer)
        bootstrap.answer, bootstrap.answers, bootstrap.queries = '127.0.0.1', {}, set()
        local = f'udp://127.0.0.1:{bootstrap.server_address[1]}'
        dns_port = F.free_port()
        config['dns'] = dict(enable=True, listen=f'127.0.0.1:{dns_port}', **{
            'enhanced-mode': 'redir-host', 'default-nameserver': [local],
            'proxy-server-nameserver': [local], 'nameserver': ['http://dns.fixture.test/dns#DNS代理']})
        upstream = dict(status=200, answer='203.0.113.20', nodes=[], queries=set())
        rt.http.dns_upstreams = {'/dns': upstream}
        rt.start(config)
        # 机制见证显式选择入口；用户在 policy 调整默认项无需同步修改用例。
        for name, choice in [('默认代理', '机场名称3'), ('DNS代理', '机场名称3'),
                             ('Telegram代理', '机场名称1-TG'), ('Speedtest', '默认代理'), ('AI', PRIVATE)]:
            rt.select(name, choice)
        assert rt.request('ordinary.fixture.test') == '机场名称3-日本'
        assert rt.request('speedtest.fixture.test') == '机场名称3-日本'
        rt.select('默认代理', '机场名称1')
        assert rt.request('speedtest.fixture.test') == '机场名称1-日本'
        rt.select('默认代理', '机场名称3')
        assert rt.request('telegram.fixture.test') == '机场名称1-日本-TG'
        rt.select('Telegram代理', '日本-机场名称1')
        assert rt.request('telegram.fixture.test') == '日本-机场名称1'
        assert rt.request('ai.fixture.test') == PRIVATE
        rt.select('下载', '机场名称1')
        rt.select('机场名称1', 'udp-机场名称1')
        # 后续业务确实能收发 UDP；若首命中错误穿透，下面应收到机场1而非拒绝。
        config['sub-rules']['分流-业务规则'].insert(0, 'DOMAIN,control.fixture.test,下载')
        config['hosts']['control.fixture.test'] = '203.0.113.8'
        rt.reload(config)
        assert F.udp_request(rt.mixed, 'control.fixture.test', sockets) == '机场名称1'
        try:
            result = F.udp_request(rt.mixed, 'udp.fixture.test', sockets)
        except socket.timeout:
            pass
        else:
            raise AssertionError(('UDP 穿透首命中业务', result))
        rt.select('机场名称3', 'udp-机场名称3')
        assert F.udp_request(rt.mixed, 'udp.fixture.test', sockets) == '机场名称3'
        rt.select('机场名称3', '机场名称3-日本')
        rt.select('默认代理', 'DIRECT')
        code, ips = F.query(dns_port, 'dns-outlet.fixture.test')
        assert code == 0 and ips == ['203.0.113.20'], (code, ips)
        assert {n for n, q in upstream['nodes'] if q == ('dns-outlet.fixture.test', 1)} == {'机场名称3-日本'}
        rt.api('/configs', 'PATCH', {'mode': 'global'})
        rt.select('GLOBAL', '日本-机场名称1')
        assert rt.request('telegram.fixture.test') == '日本-机场名称1'
    print('PASS: CF/TG 菜单、Speedtest 跟随、固定地区、UDP 首命中、DNS/GLOBAL', flush=True)


def pools(source, mihomo):
    # 一模型见证共同测速机制；四机场的新增入口由 static/routing 检查。
    url = 'http://probe.invalid/cf'
    with tempfile.TemporaryDirectory(prefix='mihomo-v2-pools-') as directory, F.Runtime(directory, mihomo, {'/cf': 204}) as rt:
        config = rt.base(source)
        config.update(proxies=[], **{'rules': ['MATCH,REJECT'], 'sub-rules': {}, 'rule-providers': {}})
        samples = {1: ['东京 fast 1x', '东京 slow 1x', '日本 MITM 1x', '日本住宅 fast 1x', '家宽 东京住宅 slow 1x', '香港住宅 fast 1x', '台湾 1x'],
                   3: ['日本 fast 1x', '日本 slow 1x', '新加坡 fast 1x', '台湾 MITM 1x', '台湾 pornhub 1x', '台湾住宅 1x', '台湾 1x'],
                   4: ['香港 fast 1x', '香港住宅 0.1x', '台湾 1x']}
        config['proxy-providers'], nodes = {}, {}
        for airport, names in samples.items():
            provider = f'Airport_0{airport}'
            nodes[airport] = [f'[机场名称{airport}]{n}' for n in names]
            path = Path(directory) / (provider + '.json')
            path.write_text(json.dumps({'proxies': [rt.proxy(n) for n in nodes[airport]]}))
            config['proxy-providers'][provider] = dict(type='file', path=str(path), **{
                'health-check': dict(enable=False, url=url, interval=86400, **{'expected-status': 204})})
        groups = {g['name']: g for g in source['proxy-groups']}
        root = '机场名称3'
        taiwan = '台湾限定站点'
        home_pool = '机场名称1-家宽'
        names = {root} | {n for n, g in groups.items() if 'use' in g}
        config['proxy-groups'] = [copy.deepcopy(groups[n]) for n in names]
        for g in config['proxy-groups']:
            if g['type'] != 'select':
                g.update(url=url, interval=0, **{'expected-status': 204})
        rt.start(config)
        assert rt.group(taiwan)['all'] == [nodes[a][-1] for a in (3, 1, 4)]
        rt.select(taiwan, nodes[1][-1])
        assert rt.group(taiwan)['now'] == nodes[1][-1]
        residential = {n for values in nodes.values() for n in values if '住宅' in n}
        assert set(rt.group('自建/家宽节点')['all']) == residential
        assert residential <= set(rt.group('全部节点')['all'])
        for name in names - {PRIVATE, home_pool, '自建/家宽节点', '全部节点'}:
            assert not residential.intersection(rt.group(name)['all']), name
        rt.http.nodes[nodes[1][3]].delays['/cf'] = .08  # 住宅比普通节点慢，仍应优先。
        for values in nodes.values():
            for node in values:
                assert rt.probe(node, url, 204)
        ordinary = '机场名称1-日本'
        assert set(rt.group(ordinary)['all']) == set(nodes[1][:2])
        assert rt.group(PRIVATE)['all'] == [home_pool] + nodes[1][:2] + nodes[1][3:5]
        assert rt.group(home_pool)['all'] == nodes[1][3:5]
        F.until(lambda: rt.probe(home_pool, url, 204))
        assert rt.group(home_pool)['now'] == nodes[1][3]
        assert rt.group(PRIVATE)['now'] == home_pool
        rt.http.nodes[nodes[1][3]].statuses['/cf'] = 503
        assert not rt.probe(nodes[1][3], url, 204)
        F.until(lambda: rt.group(home_pool)['now'] == nodes[1][4])
        assert rt.probe(home_pool, url, 204) and rt.group(PRIVATE)['now'] == home_pool
        rt.http.nodes[nodes[1][4]].statuses['/cf'] = 503
        assert not rt.probe(nodes[1][4], url, 204)
        assert not rt.probe(home_pool, url, 204)
        assert rt.group(PRIVATE)['now'] == nodes[1][0]
        rt.http.nodes[nodes[1][3]].statuses.pop('/cf')
        assert rt.probe(nodes[1][3], url, 204)
        F.until(lambda: rt.probe(home_pool, url, 204))
        assert rt.group(PRIVATE)['now'] == home_pool
        rt.select(ordinary, nodes[1][0])
        rt.select(PRIVATE, nodes[1][1])
        assert rt.group(ordinary)['now'] == nodes[1][0] and rt.group(PRIVATE)['now'] == nodes[1][1]
        preferred = '机场名称3-日本'
        F.until(lambda: rt.group(preferred)['now'] == nodes[3][0])
        assert rt.group(root)['now'] == preferred
        for node in nodes[3][:2]:
            rt.http.nodes[node].statuses['/cf'] = 503
            assert not rt.probe(node, url, 204)
        # 地区池故障不自动换地区或机场；只有手选才改变入口。
        assert rt.group(root)['now'] == preferred
        rt.select(root, '机场名称3-新加坡')
        assert rt.group(root)['now'] == '机场名称3-新加坡'
        rt.select(root, ordinary)
        assert rt.group(root)['now'] == ordinary
        rt.http.nodes[nodes[3][0]].statuses.pop('/cf')
        assert rt.probe(nodes[3][0], url, 204)
        assert rt.group(root)['now'] == ordinary
    print('PASS: 同区测速、家宽优先/全故障回退/恢复、准入、台湾手选、地区手选不漂移、独立固定状态', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('static', 'smoke'), default='static')
    parser.add_argument('--mihomo', default=os.environ.get('MIHOMO_BIN', 'mihomo'))
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    subprocess.run(['ruby', str(F.ROOT / 'scripts/build-config-v2.rb'), '--check'], check=True, timeout=30)
    command = ['ruby', str(F.ROOT / 'scripts/validate-rules.rb')]
    for name in CONFIGS:
        command.extend(['--config', str(F.ROOT / name)])
    subprocess.run(command, env={**os.environ, 'MIHOMO_BIN': args.mihomo}, check=True, timeout=150)
    policy = F.load(F.ROOT / 'config-source/v2/policy.yaml')
    sources = [F.load(F.ROOT / name) for name in CONFIGS]
    for source, four in zip(sources, (False, True)):
        static(source, four, policy)
    if args.suite == 'smoke':
        for source in sources:
            routing(source, args.mihomo)
        pools(sources[0], args.mihomo)
    print(f'PASS: v2 {args.suite}', flush=True)


if __name__ == '__main__':
    main()
