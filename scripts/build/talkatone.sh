#!/usr/bin/env bash
set -euo pipefail
echo "=== Building talkatone ==="

mkdir -p rules/Domain rules/IP

# This file is maintained in the same repository, so use the checked-out source
# instead of downloading the current branch from GitHub.
source_file="rules/Domain/talkatone.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Talkatone source: $source_file" >&2
  exit 1
fi

awk -F, '
  BEGIN { print "payload:" }
  $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "  - \047+." $2 "\047" }
' "$source_file" > rules/Domain/Talkatone-domain.yaml

awk -F, '
  BEGIN { print "payload:" }
  ($1 == "IP-CIDR" || $1 == "IP-CIDR6") && $2 != "" {
    print "  - \047" $2 "\047"
  }
' "$source_file" > rules/IP/Talkatone-ip.yaml

mihomo convert-ruleset domain yaml rules/Domain/Talkatone-domain.yaml rules/Domain/Talkatone-domain.mrs

mihomo convert-ruleset ipcidr yaml rules/IP/Talkatone-ip.yaml rules/IP/Talkatone-ip.mrs
