#!/usr/bin/env bash
set -euo pipefail
echo "=== Building emby-ip ==="

# Fetch Emby IP Rules
mkdir -p rules/IP  # 确保目录存在

# 下载 Emby IP 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/IP/emby_ip.list" -o rules/IP/emby_ip.list
curl -sL "https://raw.githubusercontent.com/666OS/YYDS/refs/heads/main/mihomo/rules/emby.list" -o rules/IP/emby.list

# Convert Emby IP Rules to YAML
echo "payload:" > rules/IP/emby-ip.yaml
cat rules/IP/emby_ip.list rules/IP/emby.list | grep '^IP-CIDR' | awk -F, '{print "  - "$2}' >> rules/IP/emby-ip.yaml

# Convert Emby IP Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset ipcidr yaml rules/IP/emby-ip.yaml rules/IP/emby-ip.mrs

# 清理临时文件，删除 emby_ip.list 和 emby.list，但保留 emby-ip.yaml
rm -f rules/IP/emby.list rules/IP/emby_ip.list

