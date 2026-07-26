#!/usr/bin/env bash
set -euo pipefail
echo "=== Building emby ==="

source_file="rules/Domain/emby.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Emby domain source: $source_file" >&2
  exit 1
fi

awk -F, '
  BEGIN { print "payload:" }
  $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "  - \047+." $2 "\047" }
' "$source_file" > rules/Domain/emby.yaml

mihomo convert-ruleset domain yaml rules/Domain/emby.yaml rules/Domain/emby.mrs
