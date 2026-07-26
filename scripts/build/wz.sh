#!/usr/bin/env bash
set -euo pipefail
echo "=== Building wz ==="

domain_source="rules/Domain/wz.yaml"
ip_source="rules/IP/wz.yaml"
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

if [[ ! -s "$domain_source" ]]; then
  echo "Missing WZ payload: $domain_source" >&2
  exit 1
fi

domain_yaml="$work_dir/wz-domain.yaml"
ip_yaml="$work_dir/wz-ip.yaml"
domain_mrs="$work_dir/wz-domain.mrs"
ip_mrs="$work_dir/wz-ip.mrs"

echo "payload:" > "$domain_yaml"
echo "payload:" > "$ip_yaml"
awk -v domain_file="$domain_yaml" -v ip_file="$ip_yaml" '
  /^[[:space:]]*-[[:space:]]*/ {
    value = $0
    sub(/^[[:space:]]*-[[:space:]]*["\047]?/, "", value)
    sub(/["\047]?[[:space:]]*$/, "", value)
    if (value ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\/[0-9]+$/) {
      print "  - \047" value "\047" >> ip_file
    } else if (value != "") {
      print "  - \047" value "\047" >> domain_file
    }
  }
' "$domain_source"

# After the first split, the domain source no longer contains IPs. Reuse the
# previously split IP payload so local rebuilds remain idempotent.
if [[ $(wc -l < "$ip_yaml") -eq 1 && -s "$ip_source" ]]; then
  cp "$ip_source" "$ip_yaml"
fi

if [[ $(wc -l < "$domain_yaml") -eq 1 || $(wc -l < "$ip_yaml") -eq 1 ]]; then
  echo "WZ source did not contain both domain and IP rules" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$domain_yaml" "$domain_mrs"
mihomo convert-ruleset ipcidr yaml "$ip_yaml" "$ip_mrs"

mkdir -p rules/Domain rules/IP
cp "$domain_yaml" rules/Domain/wz.yaml
cp "$domain_mrs" rules/Domain/wz.mrs
cp "$ip_yaml" rules/IP/wz.yaml
cp "$ip_mrs" rules/IP/wz.mrs
