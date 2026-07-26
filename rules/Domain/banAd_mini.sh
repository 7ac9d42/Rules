#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd_mini ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/banAd_mini.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for banAd_mini unchanged, skipping build."
  exit 0
fi

# Fetch BanAd_mini Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 banAd_mini.yaml
curl -sL "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/refs/heads/main/Filters/AWAvenue-Ads-Rule-Clash.yaml" -o rules/Domain/banAd_mini.yaml

# 删除 # 开头的注释行和空行
sed -i '/^\s*#/d;/^\s*$/d' rules/Domain/banAd_mini.yaml

# Fetch, Merge and Add Custom Rules with Deduplication
# 下载 pcdn.json
curl -sL "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" -o pcdn.json

# 下载自定义规则 pcdn.list
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/pcdn.list" -o pcdn.list

# 创建临时文件存放所有规则
tmp_file=$(mktemp)

# 先把原 banAd_mini.yaml 规则提取出来
grep -Eo "^[[:space:]]*-[[:space:]]*'.*'" rules/Domain/banAd_mini.yaml | sed "s/^[[:space:]]*-[[:space:]]*'\(.*\)'/\1/" >> "$tmp_file"

# 提取 pcdn.json 中 domain
jq -r '.rules[].domain[]?' pcdn.json >> "$tmp_file"

# 提取 pcdn.json 中 domain_suffix，去掉开头的 . 并加 '*.' 前缀
jq -r '.rules[].domain_suffix[]?' pcdn.json | sed 's/^\.//' | sed 's/^/*./' >> "$tmp_file"

# 处理 pcdn.list 文件
sed -E 's/^DOMAIN-SUFFIX,(.*)/*.\1/; s/^DOMAIN,(.*)/\1/' pcdn.list >> "$tmp_file"

# 去重并写回 banAd_mini.yaml
echo "payload:" > rules/Domain/banAd_mini.yaml
sort -u "$tmp_file" | awk '{print "  - \047"$0"\047"}' >> rules/Domain/banAd_mini.yaml

rm -f "$tmp_file" pcdn.json pcdn.list

# Convert BanAd_mini Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/banAd_mini.yaml rules/Domain/banAd_mini.mrs

