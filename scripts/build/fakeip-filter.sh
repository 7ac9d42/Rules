#!/usr/bin/env bash
set -euo pipefail
echo "=== Building fakeip-filter ==="

source_file="rules/Domain/fakeip-filter.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing FakeIP filter source: $source_file" >&2
  exit 1
fi

# Convert FakeIP-Filter Rules to YAML
echo "payload:" > rules/Domain/fakeip-filter.yaml
sort -u "$source_file" | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/fakeip-filter.yaml

# Convert FakeIP-Filter Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/fakeip-filter.yaml rules/Domain/fakeip-filter.mrs
