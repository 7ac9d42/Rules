#!/usr/bin/env bash
set -euo pipefail
echo "=== Building google-cn-ip ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/IP/google-cn-ip.mrs" ] && git diff --quiet HEAD -- "rules/IP/" 2>/dev/null; then
  echo "Sources for google-cn-ip unchanged, skipping build."
  exit 0
fi

# Fetch Google IP Rule
mkdir -p rules/IP  # 确保目录存在

# 下载 Google IP 规则文件
curl -sL "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/asn/AS24424.list" -o rules/IP/AS24424.list

# Convert Google IP Rules to YAML
# 直接把内容按格式写入 YAML
echo "payload:" > rules/IP/AS24424.yaml
cat rules/IP/AS24424.list | while read line; do
  # 跳过空行和注释行
  if [[ -n "$line" && ! "$line" =~ ^# ]]; then
    echo "  - '$line'" >> rules/IP/AS24424.yaml
  fi
done

# Check YAML Content
# 输出文件内容，确保格式正确
cat rules/IP/AS24424.yaml

# Convert Google IP Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset ipcidr yaml rules/IP/AS24424.yaml rules/IP/AS24424.mrs

# Clean up temporary files
# 删除原始列表文件，但保留 AS24424.yaml 和 AS24424.mrs
rm -f rules/IP/AS24424.list

