#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/8680/GOODBYEADS/master/data/rules/qx.list" \
  -o "$work_dir/qx.list"
curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" \
  -o "$work_dir/pcdn.json"

# Parse the rule type before the value. Two loose grep expressions made
# DOMAIN-SUFFIX either disappear under pipefail or be treated as an exact domain.
awk -F, '
  $1 == "DOMAIN" && $2 != "" { sub(/\.$/, "", $2); print $2 }
  $1 == "DOMAIN-SUFFIX" && $2 != "" {
    sub(/^\./, "", $2)
    sub(/\.$/, "", $2)
    print "+." $2
  }
' "$work_dir/qx.list" rules/Domain/pcdn.list > "$work_dir/domains.list"

jq -r '.rules[].domain[]?' "$work_dir/pcdn.json" >> "$work_dir/domains.list"
jq -r '.rules[].domain_suffix[]?' "$work_dir/pcdn.json" |
  sed -E 's/^\.?/+./' >> "$work_dir/domains.list"

{
  echo "payload:"
  sed -E 's/^\*\./+./' "$work_dir/domains.list" |
    sort -u |
    awk 'NF { print "  - \047" $0 "\047" }'
} > rules/Domain/banAd.yaml

mihomo convert-ruleset domain yaml \
  rules/Domain/banAd.yaml rules/Domain/banAd.mrs
