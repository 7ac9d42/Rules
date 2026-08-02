#!/usr/bin/env bash
set -euo pipefail
echo "=== Building asn-mrs ==="

# 仅保留配置实际使用的 Google 中国网络；共享云 ASN 不冒充具体应用。
asns=(AS24424)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

for asn in "${asns[@]}"; do
  source_file="$work_dir/$asn.list"
  yaml_file="$work_dir/$asn.yaml"
  mrs_file="$work_dir/$asn.mrs"

  curl --fail --show-error --silent --location \
    "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/asn/$asn.list" \
    -o "$source_file"

  {
    echo "payload:"
    awk 'NF { print "  - \047" $0 "\047" }' "$source_file"
  } > "$yaml_file"

  mihomo convert-ruleset ipcidr yaml "$yaml_file" "$mrs_file"
done

# Publish only after every required ASN has downloaded and compiled.
cp "$work_dir"/AS*.yaml "$work_dir"/AS*.mrs rules/IP/
