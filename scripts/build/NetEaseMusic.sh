#!/usr/bin/env bash
set -euo pipefail
echo "=== Building NetEaseMusic ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/NetEaseMusic.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for NetEaseMusic unchanged, skipping build."
  exit 0
fi

# Fetch NetEaseMusic Rules
mkdir -p rules/Domain rules/IP  # 确保目录存在

# 下载 NetEaseMusic 规则文件
curl -sL "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/NetEaseMusic/NetEaseMusic.list" -o rules/NetEaseMusic.list

# Separate domain and ip rules
# 提取域名规则并保存到 NetEaseMusic-domain.list
grep '^DOMAIN-SUFFIX' rules/NetEaseMusic.list > rules/Domain/NetEaseMusic-domain.list
grep '^DOMAIN' rules/NetEaseMusic.list >> rules/Domain/NetEaseMusic-domain.list

# 提取 IP 规则并保存到 NetEaseMusic-ip.list (去掉 no-resolve)
grep '^IP-CIDR' rules/NetEaseMusic.list | sed 's/,no-resolve//' > rules/IP/NetEaseMusic-ip.list

# Convert NetEaseMusic domain rules to YAML
# 将域名规则转换为 YAML 格式
echo "payload:" > rules/Domain/NetEaseMusic-domain.yaml
while IFS=, read -r type domain; do
  if [[ -n "$domain" && ! "$domain" =~ ^# ]]; then
    # 如果是 DOMAIN-SUFFIX 规则，前面加上 *.
    if [[ "$type" == "DOMAIN-SUFFIX" ]]; then
      domain="*.$domain"
    fi
    # 写入到 YAML 文件
    echo "  - $domain" >> rules/Domain/NetEaseMusic-domain.yaml
  fi
done < rules/Domain/NetEaseMusic-domain.list

# Convert NetEaseMusic IP rules to YAML
# 将 IP 规则转换为 YAML 格式
echo "payload:" > rules/IP/NetEaseMusic-ip.yaml
while IFS=, read -r type ip; do
  if [[ -n "$ip" && ! "$ip" =~ ^# ]]; then
    echo "  - $ip" >> rules/IP/NetEaseMusic-ip.yaml
  fi
done < rules/IP/NetEaseMusic-ip.list

# Convert NetEaseMusic domain rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/NetEaseMusic-domain.yaml rules/Domain/NetEaseMusic-domain.mrs

# Convert NetEaseMusic IP rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset ipcidr yaml rules/IP/NetEaseMusic-ip.yaml rules/IP/NetEaseMusic-ip.mrs

# Clean up temporary files
# 删除临时文件，但保留 NetEaseMusic-domain.yaml 和 NetEaseMusic-ip.yaml
rm -f rules/NetEaseMusic.list rules/Domain/NetEaseMusic-domain.list rules/IP/NetEaseMusic-ip.list

