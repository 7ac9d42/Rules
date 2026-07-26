#!/usr/bin/env bash
set -euo pipefail
echo "=== Building ai ==="

source_file="rules/Domain/ai.yaml"
if [[ ! -s "$source_file" ]]; then
  echo "Missing AI source: $source_file" >&2
  exit 1
fi

# Convert AI Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml "$source_file" rules/Domain/ai.mrs
