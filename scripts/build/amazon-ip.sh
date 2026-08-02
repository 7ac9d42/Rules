#!/usr/bin/env bash
set -euo pipefail
echo "=== Building amazon-ip ==="

# Fetch Amazon IP Rule
mkdir -p rules/IP  # 确保目录存在

# 下载 Amazon IP 规则文件
curl --fail --show-error --silent --location "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/AmazonIP/AmazonIP.list" -o rules/IP/amazon-ip.list

# Convert Amazon IP Rules to YAML
# 将 IP 规则文件转换为 YAML 格式
echo "payload:" > rules/IP/amazon-ip.yaml
while IFS=, read -r type ip cidr; do
  # 过滤空行和注释行
  if [[ -n "$ip" && ! "$ip" =~ ^# &&
        ("$type" == "IP-CIDR" || "$type" == "IP-CIDR6") ]]; then
    echo "  - '$ip'" >> rules/IP/amazon-ip.yaml
  fi
done < rules/IP/amazon-ip.list

# Convert Amazon IP Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset ipcidr yaml rules/IP/amazon-ip.yaml rules/IP/amazon-ip.mrs

# Clean up temporary files
# 删除原始列表文件，但保留 amazon-ip.yaml 和 amazon-ip.mrs
rm -f rules/IP/amazon-ip.list
