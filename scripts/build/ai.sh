#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
echo "=== Building ai ==="

source_file="scripts/data/ai.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing AI source: $source_file" >&2
  exit 1
fi

# 在生成前校验维护源，避免同步上游后丢失本地补充。
awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  NF != 2 || ($1 != "DOMAIN" && $1 != "DOMAIN-SUFFIX") ||
    $2 !~ /^[[:alnum:]][[:alnum:].-]*$/ { exit 1 }
' "$source_file"

{
  echo "payload:"
  awk -F, '
    /^[[:space:]]*(#|$)/ { next }
    { print ($1 == "DOMAIN-SUFFIX" ? "+." : "") tolower($2) }
  ' "$source_file" |
    sort -u |
    awk -f scripts/canonicalize-domain-rules.awk |
    awk '{ print "  - \047" $0 "\047" }'
} > rules/Domain/ai.yaml

mihomo convert-ruleset domain yaml rules/Domain/ai.yaml rules/Domain/ai.mrs
