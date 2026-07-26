#!/usr/bin/env bash
set -euo pipefail
echo "=== Building streaming ==="

for region in hk sg tw uk; do
  source_file="rules/Domain/streaming_${region}.list"
  yaml_file="rules/Domain/streaming_${region}.yaml"
  mrs_file="rules/Domain/streaming_${region}.mrs"

  if [[ ! -s "$source_file" ]]; then
    echo "Missing streaming source: $source_file" >&2
    exit 1
  fi

  {
    echo "payload:"
    awk -F, '
      $1 == "DOMAIN" && $2 != "" { print "  - \047" $2 "\047" }
      $1 == "DOMAIN-SUFFIX" && $2 != "" { print "  - \047+." $2 "\047" }
    ' "$source_file" | sort -u
  } > "$yaml_file"

  mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
done
