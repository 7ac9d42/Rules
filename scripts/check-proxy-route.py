#!/usr/bin/env python3
"""通过实际代理入口测量 URL 响应；只读核验 OpenClash 的 Smart 规避状态。"""

import argparse
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('必须是正数')
    return number


def http_url(value):
    url = urllib.parse.urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname:
        raise argparse.ArgumentTypeError('需要完整的 http:// 或 https:// 地址')
    return value


def probe(args):
    # -q 禁用 curlrc；空 noproxy 防止环境变量让请求绕过指定代理。
    timing = ('{"status":"%{http_code}","connect_s":%{time_connect},'
              '"tls_s":%{time_appconnect},"first_byte_s":%{time_starttransfer},'
              '"total_s":%{time_total},"bytes":%{size_download}}')
    failed = False
    for url in args.urls:
        for attempt in range(1, args.count + 1):
            result = subprocess.run([
                'curl', '-q', '--silent', '--show-error', '--noproxy', '',
                '--proxy', args.proxy, '--connect-timeout', str(min(5, args.timeout)),
                '--max-time', str(args.timeout), '--output', os.devnull,
                '--write-out', timing, '--url', url,
            ], capture_output=True, text=True, timeout=args.timeout + 5)
            stats = json.loads(result.stdout)
            stats['status'] = int(stats['status'])
            ok = result.returncode == 0 and (
                stats['status'] == args.expect if args.expect is not None
                else 200 <= stats['status'] < 400)
            record = {'url': url, 'attempt': attempt, 'ok': ok,
                      'curl_exit': result.returncode, **stats}
            if result.stderr:
                record['error'] = result.stderr.strip()
            failed |= not ok
            if args.json:
                print(json.dumps(record, ensure_ascii=False), flush=True)
            else:
                print(f'{"PASS" if ok else "FAIL"} [{attempt}/{args.count}] {url} '
                      f'HTTP {stats["status"]} | 首字节 {stats["first_byte_s"] * 1000:.0f} ms '
                      f'| 总计 {stats["total_s"] * 1000:.0f} ms', flush=True)
                if record.get('error'):
                    print(record['error'], file=sys.stderr)
    return int(failed)


def check_smart(args):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {}
    if os.environ.get('MIHOMO_SECRET'):
        headers['Authorization'] = 'Bearer ' + os.environ['MIHOMO_SECRET']

    def get(path):
        request = urllib.request.Request(args.controller.rstrip('/') + path, headers=headers)
        with opener.open(request, timeout=args.timeout) as response:
            return json.load(response)

    def text_field(data, key):
        if not isinstance(data, dict) or not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'控制器字段 {key} 必须是非空字符串')
        return data[key]

    version, config, proxies = get('/version'), get('/configs'), get('/proxies')['proxies']
    if not isinstance(proxies, dict) or not proxies:
        raise ValueError('控制器未返回有效的运行中代理列表')
    smart = sorted(name for name, item in proxies.items() if text_field(item, 'type').lower() == 'smart')
    mode = text_field(config, 'mode').lower()
    record = {'version': text_field(version, 'version'), 'mode': mode,
              'smart_groups': smart, 'ok': not smart and mode == 'rule'}
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    else:
        print(f'内核：{record["version"]}；模式：{mode}；Smart 组：{len(smart)}')
        for name in smart:
            print('  ' + name)
        print('PASS：规则模式，未发现 Smart 组。' if record['ok']
              else 'FAIL：请切回规则模式、关闭 Smart 自动转换，并从原始模板重新加载。')
    return int(not record['ok'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    test = commands.add_parser('probe', help='通过混合/HTTP 代理端口发起 GET，不修改分组选择')
    test.add_argument('urls', nargs='+', type=http_url)
    test.add_argument('--proxy', type=http_url, default='http://127.0.0.1:7890')
    test.add_argument('--count', type=int, choices=range(1, 21), default=3, metavar='1..20')
    test.add_argument('--expect', type=int, choices=range(100, 600), metavar='HTTP状态码',
                      help='要求精确状态码；默认接受 200–399，不跟随重定向')
    test.set_defaults(run=probe)
    check = commands.add_parser('check-smart', help='只读检查运行中分组，要求规则模式且没有 Smart 组')
    check.add_argument('--controller', type=http_url, default='http://127.0.0.1:9090')
    check.set_defaults(run=check_smart)
    for command in (test, check):
        command.add_argument('--timeout', type=positive, default=15, help='每次请求超时秒数，默认 15')
        command.add_argument('--json', action='store_true', help='逐行输出 JSON，便于比较或保存')
    args = parser.parse_args()
    try:
        return args.run(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f'ERROR：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
