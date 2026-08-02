#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building Apple software updates ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/applefirmware.yaml"
mrs_file="$work_dir/applefirmware.mrs"

# MetaCubeX apple-update 跟踪 Apple 官方企业网络文档中的软件更新端点。
curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/apple-update.yaml" \
  -o "$yaml_file"

if ! grep -q '^payload:' "$yaml_file" ||
   [[ $(grep -Ec "^[[:space:]]*-[[:space:]]*'?\+\." "$yaml_file") -lt 10 ]]; then
  echo "Apple update source is malformed or unexpectedly small" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
cp "$yaml_file" "$mrs_file" rules/Domain/
