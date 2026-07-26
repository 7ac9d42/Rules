#!/usr/bin/env bash
set -euo pipefail
echo "=== Building Telegram ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Telegram/telegram.mrs" ] && git diff --quiet HEAD -- "rules/Telegram/" 2>/dev/null; then
  echo "Sources for telegram unchanged, skipping build."
  exit 0
fi

for f in rules/Telegram/Telegram*.yaml; do
  if [ -f "$f" ]; then
    out="${f%.yaml}.mrs"
    mihomo convert-ruleset ipcidr yaml "$f" "$out"
  fi
done
