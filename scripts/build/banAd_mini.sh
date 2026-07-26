#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd_mini ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
awa_file="$work_dir/awa.yaml"
yaml_file="$work_dir/banAd_mini.yaml"
mrs_file="$work_dir/banAd_mini.mrs"

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/refs/heads/main/Filters/AWAvenue-Ads-Rule-Clash.yaml" \
  -o "$awa_file"

sed -i '/^\s*#/d;/^\s*$/d' "$awa_file"

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" \
  -o "$work_dir/pcdn.json"

grep -Eo "^[[:space:]]*-[[:space:]]*'.*'" "$awa_file" |
  sed "s/^[[:space:]]*-[[:space:]]*'\(.*\)'/\1/" > "$work_dir/domains.list"

jq -r '.rules[].domain[]?' "$work_dir/pcdn.json" >> "$work_dir/domains.list"

jq -r '.rules[].domain_suffix[]?' "$work_dir/pcdn.json" |
  sed -E 's/^\.?/+./' >> "$work_dir/domains.list"

awk -F, '
  $1 == "DOMAIN" && $2 != "" { print $2 }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "+." $2 }
' rules/Domain/pcdn.list >> "$work_dir/domains.list"

echo "payload:" > "$yaml_file"
sort -u "$work_dir/domains.list" |
  awk 'NF { print "  - \047" $0 "\047" }' >> "$yaml_file"

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
cp "$yaml_file" "$mrs_file" rules/Domain/
