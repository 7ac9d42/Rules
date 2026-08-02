#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building streaming ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

for region in hk sg tw uk; do
  source_file="scripts/data/streaming_${region}.list"
  yaml_file="$work_dir/streaming_${region}.yaml"
  mrs_file="$work_dir/streaming_${region}.mrs"

  if [[ ! -s "$source_file" ]]; then
    echo "Missing curated streaming source: $source_file" >&2
    exit 1
  fi

  if ! awk -F, '
    /^[[:space:]]*(#|$)/ { next }
    NF != 2 || $2 == "" { exit 1 }
    $1 != "DOMAIN" && $1 != "DOMAIN-SUFFIX" { exit 1 }
  ' "$source_file"; then
    echo "Streaming source contains a malformed rule: $source_file" >&2
    exit 1
  fi

  {
    echo "payload:"
    awk -F, '
      $1 == "DOMAIN" { print "  - \047" $2 "\047" }
      $1 == "DOMAIN-SUFFIX" { print "  - \047+." $2 "\047" }
    ' "$source_file" | sort -u
  } > "$yaml_file"

  if [[ $(wc -l < "$yaml_file") -le 1 ]]; then
    echo "Streaming source produced an empty payload: $source_file" >&2
    exit 1
  fi

  mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
done

# Do not publish a mixed regional snapshot when one source fails validation or
# conversion. All four regions reach this point before any tracked file changes.
for region in hk sg tw uk; do
  cp "scripts/data/streaming_${region}.list" "rules/Domain/streaming_${region}.list"
  cp "$work_dir/streaming_${region}.yaml" \
    "$work_dir/streaming_${region}.mrs" rules/Domain/
done
