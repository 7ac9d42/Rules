#!/usr/bin/env python3
"""供策略测试复用的回环假代理、故障开关与等待工具；不访问真实订阅。"""

import os
from pathlib import Path
import socket
import socketserver
import threading
import time
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
MIHOMO = os.environ.get("MIHOMO_BIN", "mihomo")
GENERIC = "http://probe.invalid/google"
GITHUB = "http://probe.invalid/github"
CLOUDFLARE = "http://probe.invalid/cloudflare"
EXPECTED = {GENERIC: 204, GITHUB: 200, CLOUDFLARE: 204}
FAILED = set()
NODE_FAILED = set()
LOCK = threading.Lock()
EVENTS = []


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            line = self.rfile.readline().decode().strip()
            while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                pass
            if not line.startswith("CONNECT "):
                return
            host = line.split()[1].rsplit(":", 1)[0]
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.wfile.flush()
            while True:
                line = self.rfile.readline().decode().strip()
                if not line:
                    return
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
                host = headers.get("host", host).split(":", 1)[0]
                label = self.server.label
                service = next((url for url in EXPECTED if path == urllib.parse.urlsplit(url).path), None)
                if service is None:
                    service = {"release-assets.githubusercontent.com": GITHUB,
                               "codeload.github.com": GITHUB, "github.com": GITHUB,
                               "api.github.com": GITHUB, "raw.githubusercontent.com": GITHUB,
                               "cloudflare.com": CLOUDFLARE, "example.pages.dev": CLOUDFLARE}.get(host, GENERIC)
                with LOCK:
                    failed = ((service, self.server.airport) in FAILED or
                              (service, label) in NODE_FAILED)
                    EVENTS.append((label, method, host, path))
                if method == "HEAD":
                    preferred = {GENERIC: "3-JP", GITHUB: "3-US", CLOUDFLARE: "3-JP"}[service]
                    # GitHub 下载可跨区选美国；网页链在日本地区内选第二个节点。
                    wait = .01 if label == preferred else .15
                    if service == GITHUB and label == "3-JP2":
                        wait = .04
                    time.sleep(wait)
                    status = 503 if failed else EXPECTED[service]
                    body = b""
                else:
                    status = 503 if failed else 200
                    body = label.encode()
                # 允许 unified-delay 在同一连接发送第二次 HEAD，避免模拟服务主动断开干扰结果。
                connection = "keep-alive" if method == "HEAD" else "close"
                self.wfile.write(
                    (f"HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n"
                     f"Connection: {connection}\r\n\r\n").encode() + body)
                self.wfile.flush()
                if method != "HEAD":
                    return
        except (OSError, ValueError):
            return


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def until(check, seconds=18):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except OSError:
            pass
        time.sleep(.15)
    raise AssertionError("等待运行时状态超时")
