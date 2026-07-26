#!/usr/bin/env bash
set -euo pipefail
echo "=== Building douyin ==="

mkdir -p rules/Domain

if [ -f "rules/Domain/douyin.list" ]; then
  grep -E '^(DOMAIN-SUFFIX|DOMAIN|DOMAIN-KEYWORD),' rules/Domain/douyin.list | grep -v '^#' | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN-KEYWORD,/*/g; s/DOMAIN,//g' > rules/Domain/douyin-domain.list || true

  echo "payload:" > rules/Domain/douyin.yaml
  sort -u rules/Domain/douyin-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/douyin.yaml

  mihomo convert-ruleset domain yaml rules/Domain/douyin.yaml rules/Domain/douyin.mrs
  rm -f rules/Domain/douyin-domain.list
fi
