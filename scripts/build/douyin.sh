#!/usr/bin/env bash
set -euo pipefail
echo "=== Building douyin ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/douyin.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for douyin unchanged, skipping build."
  exit 0
fi

mkdir -p rules/Domain

if [ -f "rules/Domain/douyin.list" ]; then
  grep -E '^(DOMAIN-SUFFIX|DOMAIN|DOMAIN-KEYWORD),' rules/Domain/douyin.list | grep -v '^#' | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN-KEYWORD,/*/g; s/DOMAIN,//g' > rules/Domain/douyin-domain.list || true

  echo "payload:" > rules/Domain/douyin.yaml
  sort -u rules/Domain/douyin-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/douyin.yaml

  mihomo convert-ruleset domain yaml rules/Domain/douyin.yaml rules/Domain/douyin.mrs
  rm -f rules/Domain/douyin-domain.list
fi
