#!/usr/bin/env bash
set -euo pipefail
echo "=== Building steamCDN ==="

mkdir -p rules/Domain rules/IP
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/Aethersailor/Custom_OpenClash_Rules/main/rule/Steam_CDN.list" \
  -o "$work_dir/steam.list"

# DOMAIN-SUFFIX must remain a suffix rule. Dropping the type narrowed each rule
# to one exact host.
awk -F, '
  BEGIN { print "payload:" }
  $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "  - \047+." $2 "\047" }
' "$work_dir/steam.list" > rules/Domain/Steam-domain.yaml

awk -F, '
  BEGIN { print "payload:" }
  ($1 == "IP-CIDR" || $1 == "IP-CIDR6") && $2 != "" {
    print "  - \047" $2 "\047"
  }
' "$work_dir/steam.list" > rules/IP/steamCDN-ip.yaml

mihomo convert-ruleset domain yaml rules/Domain/Steam-domain.yaml rules/Domain/Steam-domain.mrs

mihomo convert-ruleset ipcidr yaml rules/IP/steamCDN-ip.yaml rules/IP/steamCDN-ip.mrs
