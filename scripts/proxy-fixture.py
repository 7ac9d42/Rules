#!/usr/bin/env python3
"""供策略测试复用的回环假代理、故障开关与等待工具；不访问真实订阅。"""

import os
import socket
import socketserver
import threading
import time
import urllib.parse


MIHOMO = os.environ.get("MIHOMO_BIN", "mihomo")
GENERIC = "http://probe.invalid/google"
GITHUB = "http://probe.invalid/github"
CLOUDFLARE = "http://probe.invalid/cloudflare"
EXPECTED = {GENERIC: 204, GITHUB: 200, CLOUDFLARE: 204}
FAILED = set()
NODE_FAILED = set()
LOCK = threading.Lock()
CF_HOSTS = set()

# Tunnel 端点预期独立于配置；::10 是十六进制，::a 不是端点。
TUNNEL_IPS = [f"198.41.192.{n}" for n in (167, 67, 57, 107, 27, 7, 227, 47, 37, 77)]
TUNNEL_IPS += [f"198.41.200.{n}" for n in (13, 193, 33, 233, 53, 63, 113, 73, 43, 23)]
TUNNEL_IPS += [f"2606:4700:{region}::{n}" for region in ("a0", "a8")
              for n in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")]
TUNNEL_CASES = [(host, 7844, "Cloudflare Tunnel") for host in (
    "region1.v2.argotunnel.com", "region2.v2.argotunnel.com", "cftunnel.com", "h2.cftunnel.com", "quic.cftunnel.com",
    "198.41.192.167", "198.41.200.13", "2606:4700:a0::1", "2606:4700:a8::10")]
TUNNEL_CASES += [(host, port, "通用代理") for host, port in (
    ("198.41.192.167", 443), ("2606:4700:a0::1", 443),
    ("198.41.192.1", 7844), ("2606:4700:a0::a", 7844), ("9.9.9.9", 7844))]
TUNNEL_CASES += [(host, port, "DIRECT") for host, port in (
    ("region1.v2.argotunnel.com", 443), ("cftunnel.com", 443),
    ("unknown.argotunnel.com", 7844), ("unknown.cftunnel.com", 7844), ("demo.trycloudflare.com", 7844))]


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class Handler(socketserver.StreamRequestHandler):
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
                service = next((url for url in EXPECTED if path == urllib.parse.urlsplit(url).path), None)
                if service is None:
                    service = CLOUDFLARE if host in CF_HOSTS else (GITHUB if host in {
                        "github.com", "release-assets.githubusercontent.com", "codeload.github.com"} else GENERIC)
                label = self.server.label
                with LOCK:
                    failed = ((service, self.server.airport) in FAILED or
                              (service, label) in NODE_FAILED)
                if method == "HEAD":
                    preferred = {GENERIC: "3-JP", GITHUB: "3-US", CLOUDFLARE: "3-JP"}[service]
                    delay = .01 if label == preferred else .25
                    if service == GITHUB and label == "3-JP2":
                        # 与最快及普通节点均相差超过 50ms 容差，避免合法保留旧节点被误判。
                        delay = .12
                    time.sleep(getattr(self.server, "probe_delays", {}).get(service, delay))
                    status, body = (503 if failed else EXPECTED[service]), b""
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
