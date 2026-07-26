#!/usr/bin/env bash
set -euo pipefail
echo "=== Building direct ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/direct.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for direct unchanged, skipping build."
  exit 0
fi

# Fetch Direct Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 Direct 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/direct.list" -o rules/Domain/direct.list

# Extract DOMAIN and DOMAIN-SUFFIX rules from direct.list
# 提取 DOMAIN-SUFFIX 规则并加上 *.
grep -Eo 'DOMAIN-SUFFIX,[^,]+' rules/Domain/direct.list | sed 's/DOMAIN-SUFFIX,//' | sed 's/^/*./' > rules/Domain/direct-domain.list
# 提取 DOMAIN 规则
grep -Eo 'DOMAIN,[^,]+' rules/Domain/direct.list | sed 's/DOMAIN,//' >> rules/Domain/direct-domain.list

# Convert Direct Rules to YAML
echo "payload:" > rules/Domain/direct.yaml
sort -u rules/Domain/direct-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/direct.yaml

# Convert Direct Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/direct.yaml rules/Domain/direct.mrs
rm -f rules/Domain/direct-domain.list

