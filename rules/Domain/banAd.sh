#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/banAd.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for banAd unchanged, skipping build."
  exit 0
fi

# Ensure mihomo executable
chmod +x /usr/local/bin/mihomo || true

# Fetch BanAd Rules
mkdir -p rules/Domain  # 确保目录存在  

# 下载 BanAd 规则文件  
curl -sL "https://raw.githubusercontent.com/8680/GOODBYEADS/master/data/rules/qx.list" -o rules/Domain/qx.list  
curl -sL "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/geo/geosite/category-ads-all.list" -o rules/Domain/category-ads-all.list  

# 下载 pcdn.json 并提取 domain / domain_suffix
curl -sL "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" -o pcdn.json

# 下载自定义规则 pcdn.list
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/pcdn.list" -o pcdn.list

# Extract DOMAIN rules from qx.list, pcdn.json and pcdn.list
# 提取 qx.list 中的 DOMAIN 和 DOMAIN-SUFFIX 规则  
grep -Eo 'DOMAIN,[^,]+' rules/Domain/qx.list | sed 's/DOMAIN,//' > rules/Domain/banAd-domain.list  
grep -Eo 'DOMAIN-SUFFIX,[^,]+' rules/Domain/qx.list | sed 's/DOMAIN-SUFFIX,//' >> rules/Domain/banAd-domain.list  

# 提取 pcdn.json 中的 domain  
jq -r '.rules[].domain[]?' pcdn.json >> rules/Domain/banAd-domain.list  
# 提取 pcdn.json 中的 domain_suffix，去掉开头的 . 并加上 '*.' 前缀  
jq -r '.rules[].domain_suffix[]?' pcdn.json | sed 's/^\.//' | sed 's/^/*./' >> rules/Domain/banAd-domain.list  

# 处理自定义 pcdn.list 文件
sed -E 's/^DOMAIN-SUFFIX,(.*)/*.\1/; s/^DOMAIN,(.*)/\1/' pcdn.list >> rules/Domain/banAd-domain.list

# Convert BanAd Rules to YAML
echo "payload:" > rules/Domain/banAd.yaml  
sort -u rules/Domain/banAd-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/banAd.yaml

# Convert BanAd Rules to MRS
# 使用 mihomo 转换为 MRS 格式  
mihomo convert-ruleset domain yaml rules/Domain/banAd.yaml rules/Domain/banAd.mrs

# Clean up the source files
# 删除源文件，保留 banAd.yaml、banAd.mrs 和 pcdn.list  
rm -f rules/Domain/qx.list rules/Domain/category-ads-all.list rules/Domain/banAd-domain.list pcdn.json

