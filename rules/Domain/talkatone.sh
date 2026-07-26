#!/usr/bin/env bash
set -euo pipefail
echo "=== Building talkatone ==="

# Fetch Talkatone Rules
mkdir -p rules/Domain rules/IP  # 确保目录存在

# 下载 Talkatone 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/talkatone.list" -o rules/talkatone.list

# Separate domain and ip rules
# 提取域名规则并保存到 Talkatone-domain.list
grep '^DOMAIN-SUFFIX' rules/talkatone.list > rules/Domain/Talkatone-domain.list
grep '^DOMAIN' rules/talkatone.list >> rules/Domain/Talkatone-domain.list

# 提取 IP 规则并保存到 Talkatone-ip.list (去掉 no-resolve)
grep '^IP-CIDR' rules/talkatone.list | sed 's/,no-resolve//' > rules/IP/Talkatone-ip.list

# Convert Talkatone domain rules to YAML
# 将域名规则转换为 YAML 格式
echo 'payload:' > rules/Domain/Talkatone-domain.yaml
while IFS=, read -r type domain; do
  if [[ -n "$domain" && ! "$domain" =~ ^# ]]; then
    # 如果是 DOMAIN-SUFFIX 规则，前面加上 *.
    if [[ "$type" == "DOMAIN-SUFFIX" ]]; then
      domain="*.$domain"
    fi
    # 写入到 YAML 文件
    echo "  - '$domain'" >> rules/Domain/Talkatone-domain.yaml
  fi
done < rules/Domain/Talkatone-domain.list

# Convert Talkatone IP rules to YAML
# 将 IP 规则转换为 YAML 格式
echo 'payload:' > rules/IP/Talkatone-ip.yaml
while IFS=, read -r type ip; do
  if [[ -n "$ip" && ! "$ip" =~ ^# ]]; then
    echo "  - '$ip'" >> rules/IP/Talkatone-ip.yaml
  fi
done < rules/IP/Talkatone-ip.list

# Convert Talkatone domain rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/Talkatone-domain.yaml rules/Domain/Talkatone-domain.mrs

# Convert Talkatone IP rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset ipcidr yaml rules/IP/Talkatone-ip.yaml rules/IP/Talkatone-ip.mrs

# Clean up temporary files
# 删除临时文件，但保留 Talkatone-domain.yaml 和 Talkatone-ip.yaml
rm -f rules/talkatone.list rules/Domain/Talkatone-domain.list rules/IP/Talkatone-ip.list

