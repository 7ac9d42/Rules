#!/usr/bin/env bash
set -euo pipefail
echo "=== Building steamCDN ==="

# Fetch Steam Rules
mkdir -p rules/Domain rules/IP  # 确保目录存在

# 下载 Steam 规则文件
curl -sL "https://raw.githubusercontent.com/Aethersailor/Custom_OpenClash_Rules/main/rule/Steam_CDN.list" -o rules/Steam_CDN.list

# Extract DOMAIN and IP rules from Steam list
# 提取 DOMAIN 和 IP-CIDR 规则
grep -E 'DOMAIN|DOMAIN-SUFFIX' rules/Steam_CDN.list > rules/Domain/Steam-domain.list
grep -E 'IP-CIDR' rules/Steam_CDN.list > rules/IP/Steam-ip.list

# Convert Steam DOMAIN rules to YAML
# 将 DOMAIN 和 DOMAIN-SUFFIX 规则转换为 YAML 格式
echo "payload:" > rules/Domain/Steam-domain.yaml
while IFS=, read -r type domain; do
  if [[ -n "$domain" && ! "$domain" =~ ^# ]]; then
    echo "  - $domain" >> rules/Domain/Steam-domain.yaml
  fi
done < rules/Domain/Steam-domain.list

# Convert Steam IP rules to YAML
# 将 IP-CIDR 规则转换为 YAML 格式并保留为 steamCDN-ip.yaml
echo "payload:" > rules/IP/steamCDN-ip.yaml
while IFS=, read -r type ip cidr; do
  if [[ -n "$ip" && ! "$ip" =~ ^# && "$type" == "IP-CIDR" ]]; then
    echo "  - '$ip'" >> rules/IP/steamCDN-ip.yaml
  fi
done < rules/IP/Steam-ip.list

# Convert Steam DOMAIN rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/Steam-domain.yaml rules/Domain/Steam-domain.mrs

# Convert Steam IP rules to MRS
# 使用 mihomo 转换为 MRS 格式，并命名为 steamCDN-ip.mrs
mihomo convert-ruleset ipcidr yaml rules/IP/steamCDN-ip.yaml rules/IP/steamCDN-ip.mrs

# Clean up temporary files
# 删除临时文件，但保留 steamCDN-ip.yaml 和 steamCDN-ip.mrs
rm -f rules/Steam_CDN.list rules/Domain/Steam-domain.list rules/IP/Steam-ip.list

