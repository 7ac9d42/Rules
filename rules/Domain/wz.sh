#!/usr/bin/env bash
set -euo pipefail
echo "=== Building wz ==="

if [ -f "rules/Domain/wz.yaml" ]; then
  mihomo convert-ruleset domain yaml rules/Domain/wz.yaml rules/Domain/wz.mrs
fi
