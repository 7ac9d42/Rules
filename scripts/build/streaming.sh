#!/usr/bin/env bash
set -euo pipefail
echo "=== Building streaming ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/streaming.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for streaming unchanged, skipping build."
  exit 0
fi

# Fetch and Process streaming_hk
mkdir -p rules/Domain

curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/streaming_hk.list" -o rules/Domain/streaming_hk.list
grep -E 'DOMAIN-SUFFIX|DOMAIN' rules/Domain/streaming_hk.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/streaming_hk-domain.list

echo "payload:" > rules/Domain/streaming_hk.yaml
sort -u rules/Domain/streaming_hk-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/streaming_hk.yaml

mihomo convert-ruleset domain yaml rules/Domain/streaming_hk.yaml rules/Domain/streaming_hk.mrs
rm -f rules/Domain/streaming_hk-domain.list

# Fetch and Process streaming_sg
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/streaming_sg.list" -o rules/Domain/streaming_sg.list
grep -E 'DOMAIN-SUFFIX|DOMAIN' rules/Domain/streaming_sg.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/streaming_sg-domain.list

echo "payload:" > rules/Domain/streaming_sg.yaml
sort -u rules/Domain/streaming_sg-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/streaming_sg.yaml

mihomo convert-ruleset domain yaml rules/Domain/streaming_sg.yaml rules/Domain/streaming_sg.mrs
rm -f rules/Domain/streaming_sg-domain.list

# Fetch and Process streaming_tw
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/streaming_tw.list" -o rules/Domain/streaming_tw.list
grep -E 'DOMAIN-SUFFIX|DOMAIN' rules/Domain/streaming_tw.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/streaming_tw-domain.list

echo "payload:" > rules/Domain/streaming_tw.yaml
sort -u rules/Domain/streaming_tw-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/streaming_tw.yaml

mihomo convert-ruleset domain yaml rules/Domain/streaming_tw.yaml rules/Domain/streaming_tw.mrs
rm -f rules/Domain/streaming_tw-domain.list

# Fetch and Process streaming_uk
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/streaming_uk.list" -o rules/Domain/streaming_uk.list
grep -E 'DOMAIN-SUFFIX|DOMAIN' rules/Domain/streaming_uk.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/streaming_uk-domain.list

echo "payload:" > rules/Domain/streaming_uk.yaml
sort -u rules/Domain/streaming_uk-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/streaming_uk.yaml

mihomo convert-ruleset domain yaml rules/Domain/streaming_uk.yaml rules/Domain/streaming_uk.mrs
rm -f rules/Domain/streaming_uk-domain.list

