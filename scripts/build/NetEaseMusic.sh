#!/usr/bin/env bash
set -euo pipefail
echo "=== Building NetEaseMusic ==="

mkdir -p rules/Domain rules/IP
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/NetEaseMusic/NetEaseMusic.list" \
  -o "$work_dir/netease.list"

# The old '^DOMAIN' pass also matched every DOMAIN-SUFFIX line, duplicating it.
awk -F, '
  BEGIN { print "payload:" }
  $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "  - \047+." $2 "\047" }
' "$work_dir/netease.list" > rules/Domain/NetEaseMusic-domain.yaml

awk -F, '
  BEGIN { print "payload:" }
  ($1 == "IP-CIDR" || $1 == "IP-CIDR6") && $2 != "" {
    print "  - \047" $2 "\047"
  }
' "$work_dir/netease.list" > rules/IP/NetEaseMusic-ip.yaml

mihomo convert-ruleset domain yaml rules/Domain/NetEaseMusic-domain.yaml rules/Domain/NetEaseMusic-domain.mrs

mihomo convert-ruleset ipcidr yaml rules/IP/NetEaseMusic-ip.yaml rules/IP/NetEaseMusic-ip.mrs
