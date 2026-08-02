#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building GoogleVPN ==="

source_file="scripts/data/googleVPN.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Google VPN source: $source_file" >&2
  exit 1
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/googleVPN.yaml"
mrs_file="$work_dir/googleVPN.mrs"

if ! awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  NF != 2 || $1 != "DOMAIN-SUFFIX" || $2 == "" { exit 1 }
' "$source_file"; then
  echo "Google VPN source contains an unsupported rule: $source_file" >&2
  exit 1
fi

{
  echo "payload:"
  awk -F, '$1 == "DOMAIN-SUFFIX" { print "+." $2 }' "$source_file" |
    sort -u |
    awk 'NF { print "  - \047" $0 "\047" }'
} > "$yaml_file"

if [[ $(wc -l < "$yaml_file") -ne 2 ]]; then
  echo "Google VPN source must contain exactly one dedicated suffix" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
cp "$source_file" rules/Domain/googleVPN.list
cp "$yaml_file" "$mrs_file" rules/Domain/
