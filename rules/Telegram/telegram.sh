#!/usr/bin/env bash
set -euo pipefail
echo "=== Building Telegram ==="

for f in rules/Telegram/Telegram*.yaml; do
  if [ -f "$f" ]; then
    out="${f%.yaml}.mrs"
    mihomo convert-ruleset ipcidr yaml "$f" "$out"
  fi
done
