#!/usr/bin/env bash
set -euo pipefail
echo "=== Building fakeip-filter ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/fakeip-filter.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for fakeip-filter unchanged, skipping build."
  exit 0
fi

# Fetch FakeIP-Filter Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 fakeip-filter.list 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/fakeip-filter.list" -o rules/Domain/fakeip-filter.list

# Convert FakeIP-Filter Rules to YAML
echo "payload:" > rules/Domain/fakeip-filter.yaml
sort -u rules/Domain/fakeip-filter.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/fakeip-filter.yaml

# Convert FakeIP-Filter Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/fakeip-filter.yaml rules/Domain/fakeip-filter.mrs

