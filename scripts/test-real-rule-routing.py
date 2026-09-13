#!/usr/bin/env python3
"""用真实规则和回环出口验证业务归属、手选隔离及 Tunnel 端口边界。

--rules-dir 指定规则快照目录：manifest.json 的 providers 数组包含
name、url、status（downloaded/workspace）、file、sha256，目录内保留对应的原始 MRS/text。
--prepare-rules 新建快照：本仓库规则读取当前工作区产物，其他规则从配置 URL 下载。
逐项核对 URL、SHA256 和核心加载结果；实际出站只拨号回环假代理。
"""

import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import runpy
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse


ROOT = Path(__file__).resolve().parent.parent
H = runpy.run_path(str(Path(__file__).with_name('proxy-fixture.py')))
DIRECT_PROXY = 'fixture-DIRECT'
FIXTURE_IP = '1.1.1.1'
# Deliberate CDN/IP overlaps: domain classification must win; unknown hosts retain IP fallback.
HOST_IPS = {
    'www.408os.cn': '106.75.74.76',
    'www.microsoft.com': '106.75.74.76',
    'www.google.com': '45.121.184.1',
    'www.disneyplus.com': '23.246.0.1',
    'ip-only-bilibili.example.com': '106.75.74.76',
}


# 每例明确给出业务入口与默认自动终结出口；预期独立于待测配置。
# 预期按已确认的业务合并边界编写；探针家族不改变业务归属。
CASES = [
    ('whatsapp.com', '境外通信', '机场名称3优先'),
    ('graph.whatsapp.net', '境外通信', '机场名称3优先'),
    ('m.me', '境外通信', '机场名称3优先'),
    ('viber.com', '境外通信', '机场名称3优先'),
    ('vbcdn.net', '境外通信', '机场名称3优先'),
    ('l-0005.l-msedge.net', '境外社媒', '机场名称1优先'),
    ('www.408os.cn', 'DIRECT', 'DIRECT'),
    ('www.microsoft.com', 'Microsoft', '机场名称3优先'),
    ('www.google.com', 'Google', '机场名称1优先'),
    ('www.disneyplus.com', 'DisneyPlus', '机场名称1优先'),
    ('ip-only-bilibili.example.com', '哔哩哔哩', 'DIRECT'),

    ('hk.tv.global.mi.com', '通用代理', '机场名称3优先'),
    ('www.mi.com', 'DIRECT', 'DIRECT'),
    ('weixin.qq.com', 'DIRECT', 'DIRECT'),
    ('wxcdn.weixin.qq.com', 'DIRECT', 'DIRECT'),
    ('wx.qlogo.cn', 'DIRECT', 'DIRECT'),
    ('taobao.com', 'DIRECT', 'DIRECT'),
    ('g.alicdn.com', 'DIRECT', 'DIRECT'),
    ('music.163.com', 'DIRECT', 'DIRECT'),
    ('music.126.net', 'DIRECT', 'DIRECT'),
    ('test.kuapt.top', 'DIRECT', 'DIRECT'),
    ('argotunnel.com', 'DIRECT', 'DIRECT'),
    ('cftunnel.com', 'DIRECT', 'DIRECT'),
    ('cloudflare.com', '通用代理', 'Cloudflare-自动'),
    ('dash.cloudflare.com', '通用代理', 'Cloudflare-自动'),
    ('example.pages.dev', '通用代理', 'Cloudflare-自动'),
    ('example.workers.dev', '通用代理', 'Cloudflare-自动'),
    ('demo.trycloudflare.com', 'DIRECT', 'DIRECT'),
    ('cloudflarechina.cn', 'DIRECT', 'DIRECT'),
    ('cf-china.info', 'DIRECT', 'DIRECT'),
    ('cftest5.cn', 'DIRECT', 'DIRECT'),
    ('cf-ns.com', 'DIRECT', 'DIRECT'),
    ('cloudflare-cn.com', 'DIRECT', 'DIRECT'),
    ('docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com', '开发下载', 'Cloudflare-自动'),
    ('dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com', '开发下载', 'Cloudflare-自动'),
    ('unpkg.com', '开发下载', 'Cloudflare-自动'),
    ('esm.unpkg.com', '开发下载', 'Cloudflare-自动'),
    ('cdnjs.com', '通用代理', 'Cloudflare-自动'),
    ('api.cdnjs.com', '通用代理', 'Cloudflare-自动'),
    ('nodejs.org', '开发下载', 'Cloudflare-自动'),
    ('linux.do', '通用代理', 'Cloudflare-自动'),
    ('cdn.linux.do', '通用代理', 'Cloudflare-自动'),
    ('connect.linux.do', '通用代理', 'Cloudflare-自动'),
    ('unknown.nodejs.org', '开发下载', '机场名称3优先'),
    ('unknown.linux.do', '通用代理', '机场名称3优先'),
    ('cdn.jsdelivr.net', '开发下载', '机场名称3优先'),
    ('discord.com', '境外通信', 'Cloudflare-自动'),
    ('api.discord.com', '境外通信', '机场名称3优先'),
    ('cdn.discordapp.com', '境外通信', '机场名称3优先'),
    ('okx.com.cdn.cloudflare.net', '金融', 'Cloudflare-机场名称1优先'),
    ('gateway.ai.cloudflare.com', 'AI', 'AI'),
    ('openai.com.cdn.cloudflare.net', 'AI', 'AI'),
    ('chatgpt.com', 'AI', 'AI'),
    ('claude.ai', 'AI', 'AI'),
    ('gemini.google.com', 'AI', 'AI'),
    ('opencode.ai', 'AI', 'AI'),
    ('origin-tracker.githubusercontent.com', 'AI', 'AI'),
    ('copilot-proxy.githubusercontent.com', 'AI', 'AI'),
    ('copilotprodattachments.blob.core.windows.net', 'AI', 'AI'),
    ('huggingface.co', '开发下载', '机场名称3优先'),
    ('hf.co', '开发下载', '机场名称3优先'),
    ('registry.ollama.com', '开发下载', '机场名称3优先'),
    ('coderabbit.gallery.vsassets.io', '开发下载', '机场名称3优先'),
    ('openaiassets.blob.core.windows.net', '开发下载', '机场名称3优先'),
    ('openaicomproductionae4b.blob.core.windows.net', '开发下载', '机场名称3优先'),
    ('github.com', '开发下载', 'GitHub-自动'),
    ('raw.githubusercontent.com', '开发下载', 'GitHub-自动'),
    ('release-assets.githubusercontent.com', '纯下载', '纯下载-自动'),
    ('codeload.github.com', '纯下载', '纯下载-自动'),
    ('registry-1.docker.io', '开发下载', '机场名称3优先'),
    ('storage.googleapis.com', '开发下载', '机场名称3优先'),
    ('wise.com', '金融', '机场名称1优先'),
    ('paypal.com', '金融', '机场名称1优先'),
    ('hsbc.com', '金融', '机场名称1优先'),
    ('binance.com', '金融', '机场名称1优先'),
    ('google.com', 'Google', '机场名称1优先'),
    ('cloud.cupronickel.goog', 'Google', '机场名称1优先'),
    ('youtube.com', '境外影音', '机场名称3优先'),
    ('mtalk.google.com', 'Google', '机场名称1优先'),
    ('fcm.googleapis.com', 'Google', '机场名称1优先'),
    ('microsoft.com', 'Microsoft', '机场名称3优先'),
    ('onedrive.live.com', 'Microsoft', '机场名称3优先'),
    ('facebook.com', '境外社媒', '机场名称1优先'),
    ('reddit.com', 'Reddit', '机场名称1优先'),
    ('telegram.org', '境外通信', '机场名称3优先'),
    ('line.me', '境外通信', '机场名称3优先'),
    ('signal.org', '境外通信', '机场名称3优先'),
    ('talkatone.com', 'Talkatone', '机场名称1优先'),
    ('netflix.com', 'NETFLIX', '机场名称1优先'),
    ('disneyplus.com', 'DisneyPlus', '机场名称1优先'),
    ('hbo.com', 'HBO', '机场名称1优先'),
    ('primevideo.com', 'Primevideo', '机场名称1优先'),
    ('spotify.com', 'Spotify', '机场名称1优先'),
    ('tiktok.com', 'TikTok', '机场名称1优先'),
    ('tv.apple.com', '境外影音', '机场名称3优先'),
    ('twitch.tv', '境外影音', '机场名称3优先'),
    ('updates.cdn-apple.com', 'Apple', 'DIRECT'),
    ('mytv.com.hk', 'TVB', '机场名称1优先'),
    ('tvb.com', 'TVB', '机场名称1优先'),
    ('gamer.com.tw', '台湾限定', '台湾-机场名称1优先'),
    ('bilibili.tv', '哔哩东南亚', '新加坡-机场名称1优先'),
    ('bilibili.com', '哔哩哔哩', 'DIRECT'),
    ('amazon.com', '境外电商', '机场名称1优先'),
    ('store.steampowered.com', '游戏平台', '机场名称3优先'),
    ('epicgames.com', '游戏平台', '机场名称3优先'),
    ('ea.com', '游戏平台', '机场名称3优先'),
    ('steamchina.com', 'DIRECT', 'DIRECT'),
    ('steamcdn-a.akamaihd.net', 'DIRECT', 'DIRECT'),
    ('speedtest.net', 'Speedtest', '机场名称3优先'),
    ('ad.doubleclick.net', '隐私拦截', '隐私拦截'),
    ('ghcr.io', '开发下载', 'GitHub-自动'),
    ('npmjs.org', '开发下载', 'GitHub-自动'),
    ('productionresultssa0.blob.core.windows.net', '开发下载', 'GitHub-自动'),
    ('cavporn.github.io', '境外影音', 'GitHub-自动'),
]

# 四机场只改变高要求业务的默认机场顺序；AI仍保持机场名称1手选。
HIGH_BUSINESSES = {
    '金融', 'Talkatone', 'NETFLIX', 'DisneyPlus', 'HBO', 'Primevideo', 'Spotify', 'Reddit',
}
FOUR_AIRPORT_HIGH_OUTLETS = {
    '机场名称1优先': '家宽优先',
    'Cloudflare-机场名称1优先': 'Cloudflare-家宽优先',
    'GitHub-机场名称1优先': 'GitHub-家宽优先',
}


def cases_for_config(source):
    airports = set(source.get('proxy-providers', {}))
    three_airports = {'Airport_01', 'Airport_03', 'Airport_04'}
    if airports == three_airports:
        return list(CASES)
    if airports != three_airports | {'Airport_02'}:
        raise AssertionError(f'只支持机场名称1、机场名称3、机场名称4，或包含机场名称2的四机场配置，实际为 {sorted(airports)}')
    return [(host, business, FOUR_AIRPORT_HIGH_OUTLETS[outlet]
             if business in HIGH_BUSINESSES else outlet)
            for host, business, outlet in CASES]


# 同一高要求政策的金融/Talkatone必须分别接受业务入口的选择。
# 复用已有真实见证，不为交叉测试伪造公开规则内容。
FINANCE_WITNESSES = {
    'paypal.com', 'wise.com', 'hsbc.com', 'binance.com',
    'okx.com.cdn.cloudflare.net',
}
DOWNLOAD_WITNESSES = {
    'github.com', 'huggingface.co', 'registry-1.docker.io', 'cloudflare.com',
    'docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com',
    'release-assets.githubusercontent.com', 'codeload.github.com',
}

def load_config(path):
    content = path.read_bytes()
    result = subprocess.check_output(['ruby', '-ryaml', '-rjson', '-e',
        'puts JSON.generate(YAML.load(STDIN.read, aliases: true))'], input=content, timeout=10)
    return json.loads(result)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_snapshot(source, rules_dir):
    # 在发布前验证本次构建产物；不能下载 main 上尚未更新的自有规则。
    rules_dir.mkdir(parents=True, exist_ok=False)
    local_prefix = 'https://raw.githubusercontent.com/7ac9d42/Rules/refs/heads/main/rules/'

    def collect(item):
        name, provider = item
        url = provider['url']
        path = rules_dir / f'{name}.{provider["format"]}'
        if url.startswith(local_prefix):
            local = ROOT / 'rules' / urllib.parse.unquote(url[len(local_prefix):])
            shutil.copyfile(local, path)
            status = 'workspace'
        else:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '2', '--retry-all-errors', '--max-time', '60', '--output', str(path), url],
                           check=True, timeout=190)
            status = 'downloaded'
        if path.stat().st_size == 0:
            raise AssertionError(f'{name}: 规则文件为空')
        return {'name': name, 'url': url, 'status': status, 'file': path.name, 'sha256': digest(path)}

    items = [(name, provider) for name, provider in source['rule-providers'].items()
             if provider['type'] == 'http']
    with ThreadPoolExecutor(max_workers=4) as executor:
        entries = list(executor.map(collect, items))
    # 全部完成才写清单；任何下载失败都不能生成可用于验收的快照。
    (rules_dir / 'manifest.json').write_text(json.dumps({'providers': entries}, ensure_ascii=False, indent=2) + '\n')
    print(f'Prepared {len(entries)} rule providers in {rules_dir}', flush=True)


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
        target = runtime / f'{name}.{provider["format"]}'
        shutil.copyfile(path, target)
        prepared[name] = {'type': 'file', 'behavior': provider['behavior'],
                          'format': provider['format'], 'path': str(target)}
    return prepared


def policy_targets(source):
    names = {group['name'] for group in source['proxy-groups']}
    targets = set()
    for rules in [source['rules'], *source.get('sub-rules', {}).values()]:
        for rule in rules:
            if rule.startswith('SUB-RULE,'):
                continue
            parts = rule.split(',')
            target = parts[-2] if parts[-1] == 'no-resolve' else parts[-1]
            if target in names:
                targets.add(target)
            elif target not in {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'}:
                raise AssertionError(f'未识别规则出口: {rule}')
    return sorted(targets)


def local_direct(rules):
    result = []
    for rule in rules:
        parts = rule.split(',')
        action = -2 if parts[-1] == 'no-resolve' else -1
        if parts[action] == 'DIRECT':
            parts[action] = DIRECT_PROXY
        result.append(','.join(parts))
    return result


Server = H["Server"]
free_port = H["free_port"]

class Handler(socketserver.StreamRequestHandler):
    def read_request(self):
        first = self.rfile.readline().decode().strip()
        headers = {}
        while True:
            line = self.rfile.readline()
            if line in (b'\r\n', b'\n', b''):
                return first, headers
            key, value = line.decode().split(':', 1)
            headers[key.lower()] = value.strip()

    def handle(self):
        self.connection.settimeout(3)
        try:
            first, headers = self.read_request()
            label = 'DIRECT'
            if first.startswith('CONNECT '):
                authorization = headers.get('proxy-authorization', '')
                if not authorization.startswith('Basic '):
                    return
                username = base64.b64decode(authorization[6:]).decode().split(':', 1)[0]
                label = self.server.labels[username]
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                first, headers = self.read_request()
            host = urllib.parse.urlsplit('//' + headers.get('host', '')).hostname
            if host not in self.server.hosts:
                return
            body = json.dumps({'policy': label, 'host': host}, ensure_ascii=False).encode()
            self.wfile.write((f'HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n'
                              'Connection: close\r\n\r\n').encode() + body)
        except (OSError, ValueError, KeyError):
            return


def get_json(port, target):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        address = urllib.parse.urlsplit(target)
        if address.hostname in HOST_IPS:
            # SOCKS ingress exercises address metadata in addition to HTTP domain routing.
            connection.sock = socket.create_connection(('127.0.0.1', port), timeout=3)
            def read(size):
                data = b''
                while len(data) < size:
                    chunk = connection.sock.recv(size - len(data))
                    if not chunk:
                        raise OSError('SOCKS handshake closed')
                    data += chunk
                return data
            connection.sock.sendall(b'\x05\x01\x00')
            assert read(2) == b'\x05\x00'
            host = address.hostname.encode()
            connection.sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host
                                    + struct.pack('!H', address.port or 80))
            reply = read(4)
            assert reply[:3] == b'\x05\x00\x00', reply
            assert reply[3] in (1, 3, 4), reply
            length = read(1)[0] if reply[3] == 3 else {1: 4, 4: 16}[reply[3]]
            read(length)
            read(2)
        connection.request('GET', target, headers={'Connection': 'close'})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise AssertionError(f'HTTP {response.status}: {body[:160]!r}')
        return json.loads(body)
    finally:
        connection.close()


def run(args):
    source = load_config(args.config)
    if args.prepare_rules:
        create_snapshot(source, args.rules_dir)
    cases = cases_for_config(source)
    targets = policy_targets(source)
    assert DIRECT_PROXY not in targets
    hosts = {host for host, _, _ in cases} | {host for host, _, _ in H["TUNNEL_CASES"]}
    labels = {f'route{i}': target for i, target in enumerate([*targets, 'DIRECT'])}
    business_names = {business for _, business, _ in cases} - {'AI', 'DIRECT', '隐私拦截'}
    business_names.add('Cloudflare Tunnel')
    controlled = [g for g in source['proxy-groups'] if g['name'] in business_names]
    if {g['name'] for g in controlled} != business_names:
        raise AssertionError('真实域名见证引用的业务入口缺失')
    if any(g['type'] != 'select' for g in controlled):
        raise AssertionError('业务入口必须持有独立的 select 选择')
    checked, independence_checked = [], []
    with tempfile.TemporaryDirectory(prefix='mihomo-real-rules-') as directory:
        runtime = Path(directory)
        providers = prepare_rules(source, args.rules_dir, runtime)
        server = Server(('127.0.0.1', 0), Handler)
        server.labels, server.hosts = labels, hosts
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        mixed, controller = free_port(), free_port()
        fixture = {
            'mixed-port': mixed, 'external-controller': f'127.0.0.1:{controller}',
            'bind-address': '127.0.0.1', 'allow-lan': False, 'mode': 'rule', 'ipv6': True,
            'log-level': 'warning', 'dns': {'enable': False}, 'tun': {'enable': False},
            'profile': {'store-selected': False, 'store-fake-ip': False},
            'hosts': {host: HOST_IPS.get(host, FIXTURE_IP) for host in hosts},
            'proxies': [{'name': DIRECT_PROXY if label == 'DIRECT' else 'fixture-' + label if label in {g['name'] for g in controlled} else label,
                         'type': 'http', 'server': '127.0.0.1',
                         'port': port, 'username': username, 'password': 'fixture'}
                        for username, label in labels.items()] + source['proxies'],
            'proxy-groups': [{'name': g['name'], 'type': 'select',
                              'proxies': ['fixture-' + g['name'], DIRECT_PROXY if g['proxies'][0] == 'DIRECT' else g['proxies'][0]]}
                             for g in controlled],
            'rule-providers': providers, 'rules': local_direct(source['rules']),
            'sub-rules': {name: local_direct(rules)
                          for name, rules in source.get('sub-rules', {}).items()},
        }
        config = runtime / 'config.json'
        config.write_text(json.dumps(fixture, ensure_ascii=False))
        core = None
        try:
            validation = subprocess.run([args.mihomo, '-t', '-d', directory, '-f', str(config)],
                                        capture_output=True, text=True, timeout=15)
            if validation.returncode:
                raise AssertionError(validation.stdout + validation.stderr)
            with (runtime / 'core.log').open('w+') as log:
                core = subprocess.Popen([args.mihomo, '-d', directory, '-f', str(config)],
                                        stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 15
                loaded = {}
                while True:
                    try:
                        version = get_json(controller, '/version')
                        loaded = get_json(controller, '/providers/rules')['providers'] or {}
                        if set(loaded) == set(providers) and all(
                                item['ruleCount'] > 0 for item in loaded.values()):
                            break
                    except (OSError, http.client.HTTPException):
                        pass
                    if core.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        missing = sorted(set(providers) - set(loaded))
                        empty = [name for name, item in loaded.items() if not item['ruleCount']]
                        raise AssertionError(f'核心规则未就绪: missing={missing}, empty={empty}; ' + log.read()[-3000:])
                    time.sleep(.1)
                for host, business, _ in cases:
                    actual = get_json(mixed, f'http://{host}:{port}/rule-test')
                    if actual != {'host': host, 'policy': business}:
                        raise AssertionError({'phase': 'business', 'host': host,
                                              'expected': business, 'actual': actual})
                    checked.append({'host': host, 'business': business})

                def select_state(group, automatic=True):
                    connection = http.client.HTTPConnection('127.0.0.1', controller, timeout=3)
                    try:
                        connection.request('PUT', '/proxies/' + urllib.parse.quote(group['name']),
                                           json.dumps({'name': group['proxies'][int(automatic)]}),
                                           {'Content-Type': 'application/json'})
                        response = connection.getresponse()
                        assert response.status == 204, response.read()
                    finally:
                        connection.close()

                def tunnel_checks(automatic):
                    defaults = {'Cloudflare Tunnel': 'DIRECT', '通用代理': '机场名称3优先', 'DIRECT': 'DIRECT'}
                    for host, target_port, business in H['TUNNEL_CASES']:
                        expected = defaults[business] if automatic else business
                        address = '[' + host + ']' if ':' in host else host
                        actual = get_json(mixed, f'http://{address}:{target_port}/rule-test')
                        assert actual == {'host': host, 'policy': expected}, (host, target_port, expected, actual)

                tunnel_checks(False)
                finance = next(g for g in fixture['proxy-groups'] if g['name'] == '金融')
                select_state(finance)
                for host, business, automatic in cases:
                    if host not in FINANCE_WITNESSES and host != 'talkatone.com':
                        continue
                    expected = automatic if business == '金融' else business
                    actual = get_json(mixed, f'http://{host}:{port}/rule-test')
                    if actual != {'host': host, 'policy': expected}:
                        raise AssertionError({'phase': 'business_independence', 'host': host,
                                              'expected': expected, 'actual': actual})
                    independence_checked.append({'phase': 'finance_default', 'host': host,
                                                 'business': business, 'outlet': expected})
                by_business = {g['name']: g for g in fixture['proxy-groups']}
                for left, right, witnesses in [
                    ('开发下载', '纯下载', DOWNLOAD_WITNESSES),
                    ('NETFLIX', 'DisneyPlus', {'netflix.com', 'disneyplus.com'}),
                    ('Google', 'Microsoft', {'google.com', 'cloud.cupronickel.goog',
                                             'mtalk.google.com', 'fcm.googleapis.com',
                                             'microsoft.com', 'onedrive.live.com'}),
                    ('境外影音', 'NETFLIX', {'youtube.com', 'tv.apple.com', 'twitch.tv',
                                            'cavporn.github.io', 'netflix.com'}),
                    ('境外通信', '境外社媒', {'telegram.org', 'line.me', 'signal.org',
                                            'discord.com', 'api.discord.com', 'whatsapp.com', 'viber.com', 'facebook.com'}),
                    ('Reddit', '境外社媒', {'reddit.com', 'facebook.com'}),
                    ('游戏平台', '境外影音', {'store.steampowered.com', 'epicgames.com',
                                            'ea.com', 'youtube.com', 'tv.apple.com'}),
                ]:
                    for automatic_business, manual_business in [(left, right), (right, left)]:
                        select_state(by_business[automatic_business])
                        select_state(by_business[manual_business], automatic=False)
                        for host, business, automatic in cases:
                            if host not in witnesses:
                                continue
                            expected = automatic if business == automatic_business else business
                            actual = get_json(mixed, f'http://{host}:{port}/rule-test')
                            if actual != {'host': host, 'policy': expected}:
                                raise AssertionError({'phase': 'product_independence',
                                                      'automatic_business': automatic_business,
                                                      'host': host, 'expected': expected, 'actual': actual})
                            independence_checked.append({'phase': automatic_business + '_default',
                                                         'host': host, 'business': business, 'outlet': expected})
                for group in fixture['proxy-groups']:
                    select_state(group)
                for item, (host, _, expected) in zip(checked, cases):
                    actual = get_json(mixed, f'http://{host}:{port}/rule-test')
                    if actual != {'host': host, 'policy': expected}:
                        raise AssertionError({'phase': 'auto', 'host': host, 'expected': expected, 'actual': actual})
                    item['automatic_outlet'] = expected
                tunnel_checks(True)

        finally:
            if core is not None and core.poll() is None:
                core.terminate()
                try:
                    core.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    core.kill()
                    core.wait(timeout=5)
            server.shutdown()
            server.server_close()
    report = {'config': str(args.config), 'mihomo': version, 'checks': checked,
              'business_independence': independence_checked, 'tunnel_tcp_checks': 2 * len(H['TUNNEL_CASES'])}
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS: {args.config.name}，{len(checked)} 个域名 × 业务/自动两阶段，'
          f'{len(independence_checked)} 次选择隔离，{report["tunnel_tcp_checks"]} 次 Tunnel TCP 检查')


def interrupted(signum, _frame):
    # SystemExit 经过 run() 的 finally，timeout/SIGTERM 也会清理子核心。
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules-dir', type=Path, required=True,
                        help='含规则文件与 manifest.json 的公开规则快照目录')
    parser.add_argument('--prepare-rules', action='store_true',
                        help='从工作区产物与远程上游建立快照；--rules-dir 必须尚不存在')
    parser.add_argument('--config', type=Path,
                        default=Path(os.environ.get('MIHOMO_DESIGN_CONFIG', str(ROOT / 'configfull_new.yaml'))),
                        help='三机场或四机场的实际配置文件；默认遵循 MIHOMO_DESIGN_CONFIG，否则使用三机场')
    parser.add_argument('--mihomo', default=os.environ.get('MIHOMO_BIN', 'mihomo'))
    parser.add_argument('--report', type=Path, help='可选 JSON 审计报告路径')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
