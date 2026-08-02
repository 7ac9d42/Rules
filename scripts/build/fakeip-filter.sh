#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building fakeip-filter ==="

source_file="scripts/data/fakeip-filter.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing FakeIP filter source: $source_file" >&2
  exit 1
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/fakeip-filter.yaml"
mrs_file="$work_dir/fakeip-filter.mrs"

{
  echo "payload:"
  awk '!/^[[:space:]]*(#|$)/ { print }' "$source_file" |
    sort -u |
    awk '{ print "  - \047" $0 "\047" }'
} > "$yaml_file"

if [[ $(wc -l < "$yaml_file") -le 1 ]]; then
  echo "FakeIP filter source produced an empty payload" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
mkdir -p rules/Domain
cp "$source_file" rules/Domain/fakeip-filter.list
cp "$yaml_file" "$mrs_file" rules/Domain/
