#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building proxy ==="

source_file="rules/Domain/Proxymini.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing proxy source: $source_file" >&2
  exit 1
fi

# Convert DOMAIN and DOMAIN-SUFFIX rules to a minimal domain payload.
{
  echo "payload:"
  awk -F, '
    /^[[:space:]]*(#|$)/ { next }
    NF != 2 || ($1 != "DOMAIN" && $1 != "DOMAIN-SUFFIX") || $2 == "" { exit 1 }
    { print ($1 == "DOMAIN-SUFFIX" ? "+." : "") tolower($2) }
  ' "$source_file" |
    sort -u |
    awk -f scripts/canonicalize-domain-rules.awk |
    awk '{ print "  - \047" $0 "\047" }'
} > rules/Domain/proxy.yaml

# Convert Proxymini Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/proxy.yaml rules/Domain/proxy.mrs
