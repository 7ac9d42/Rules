#!/usr/bin/env bash
set -euo pipefail
echo "=== Building wz ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/wz.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for wz unchanged, skipping build."
  exit 0
fi

if [ -f "rules/Domain/wz.yaml" ]; then
  mihomo convert-ruleset domain yaml rules/Domain/wz.yaml rules/Domain/wz.mrs
fi
