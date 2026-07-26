#!/usr/bin/env bash
set -euo pipefail
echo "=== Building tvb ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/btjson/loon/refs/heads/main/TVB.list" \
  -o "$work_dir/tvb.list"

yaml_file="$work_dir/tvb.yaml"
mrs_file="$work_dir/tvb.mrs"
{
  echo "payload:"
  awk -F, '
    $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
    $1 == "DOMAIN-SUFFIX" && $2 != "" {
      sub(/^\*\./, "", $2)
      sub(/^\./, "", $2)
      print "  - \047+." $2 "\047"
    }
  ' "$work_dir/tvb.list" | sort -u
} > "$yaml_file"

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
cp "$yaml_file" "$mrs_file" rules/Domain/
