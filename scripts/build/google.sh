#!/usr/bin/env bash
set -euo pipefail
echo "=== Building google ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/google.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for google unchanged, skipping build."
  exit 0
fi

# Fetch and Merge Google Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 Google 规则文件
curl -sL "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/geo/geosite/google-play.list" -o rules/Domain/google-play.list
curl -sL "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/google.list" -o rules/Domain/google.list

# 合并去重
cat rules/Domain/google-play.list rules/Domain/google.list | grep -v '^#' | sort -u > rules/Domain/merged_google.list

# Convert merged Google rules to YAML
echo "payload:" > rules/Domain/google.yaml
while IFS= read -r line; do
  if [[ -n "$line" ]]; then
    echo "  - $line" >> rules/Domain/google.yaml
  fi
done < rules/Domain/merged_google.list

# Convert Google Rules to MRS
mihomo convert-ruleset domain yaml rules/Domain/google.yaml rules/Domain/google.mrs
rm -f rules/Domain/google-play.list rules/Domain/google.list rules/Domain/merged_google.list

