#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building talkatone ==="

source_file="scripts/data/talkatone.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Talkatone source: $source_file" >&2
  exit 1
fi

if ! awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  NF != 2 || $2 == "" { exit 1 }
  $1 != "DOMAIN" && $1 != "DOMAIN-SUFFIX" &&
  $1 != "IP-CIDR" && $1 != "IP-CIDR6" { exit 1 }
' "$source_file"; then
  echo "Talkatone source contains a malformed or unsupported rule" >&2
  exit 1
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
domain_yaml="$work_dir/Talkatone-domain.yaml"
domain_mrs="$work_dir/Talkatone-domain.mrs"
ip_yaml="$work_dir/Talkatone-ip.yaml"
ip_mrs="$work_dir/Talkatone-ip.mrs"

{
  echo "payload:"
  awk -F, '
    $1 == "DOMAIN" { print $2 }
    $1 == "DOMAIN-SUFFIX" { print "+." $2 }
  ' "$source_file" | sort -u | awk 'NF { print "  - \047" $0 "\047" }'
} > "$domain_yaml"

{
  echo "payload:"
  awk -F, '$1 == "IP-CIDR" || $1 == "IP-CIDR6" { print $2 }' \
    "$source_file" | sort -u | awk 'NF { print "  - \047" $0 "\047" }'
} > "$ip_yaml"

if [[ $(wc -l < "$domain_yaml") -le 1 || $(wc -l < "$ip_yaml") -le 1 ]]; then
  echo "Talkatone source must contain both domain and IP rules" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$domain_yaml" "$domain_mrs"
mihomo convert-ruleset ipcidr yaml "$ip_yaml" "$ip_mrs"

mkdir -p rules/Domain rules/IP
cp "$source_file" rules/Domain/talkatone.list
cp "$domain_yaml" "$domain_mrs" rules/Domain/
cp "$ip_yaml" "$ip_mrs" rules/IP/
