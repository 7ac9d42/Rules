#!/usr/bin/env bash
set -euo pipefail
echo "=== Building tvb ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/tvb.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for tvb unchanged, skipping build."
  exit 0
fi

# Fetch TVB Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 TVB 规则文件
curl -sL "https://raw.githubusercontent.com/btjson/loon/refs/heads/main/TVB.list" -o rules/Domain/tvb.list

# Convert TVB Rules to YAML
echo "payload:" > rules/Domain/tvb.yaml
while IFS=, read -r type value; do
  if [[ -n "$type" && -n "$value" ]]; then
    # 处理 DOMAIN 规则，直接加入
    if [[ "$type" == "DOMAIN" ]]; then
      echo "  - $value" >> rules/Domain/tvb.yaml
    # 处理 DOMAIN-SUFFIX 规则，加上 *.
    elif [[ "$type" == "DOMAIN-SUFFIX" ]]; then
      echo "  - '*.$value'" >> rules/Domain/tvb.yaml
    fi
  fi
done < rules/Domain/tvb.list

# Convert TVB Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/tvb.yaml rules/Domain/tvb.mrs

