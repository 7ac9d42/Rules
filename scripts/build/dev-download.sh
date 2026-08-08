#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building dev-download ==="

source_file="scripts/data/dev-download.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing developer download source: $source_file" >&2
  exit 1
fi

if ! awk '
  /^[[:space:]]*(#|$)/ { next }
  $0 !~ /^\+\.[[:alnum:]][[:alnum:].-]*$/ { exit 1 }
' "$source_file"; then
  echo "Developer download source contains an invalid suffix: $source_file" >&2
  exit 1
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/dev-download.yaml"
mrs_file="$work_dir/dev-download.mrs"

{
  echo "payload:"
  awk '!/^[[:space:]]*(#|$)/ { print }' "$source_file" |
    sort -u |
    awk '{ print "  - \047" $0 "\047" }'
} > "$yaml_file"

if [[ $(wc -l < "$yaml_file") -lt 30 ]]; then
  echo "Developer download source shrank below the reviewed minimum" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
mkdir -p rules/Domain
cp "$yaml_file" "$mrs_file" rules/Domain/
