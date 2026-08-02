#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building emby ==="

source_file="scripts/data/emby.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Emby domain source: $source_file" >&2
  exit 1
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/emby.yaml"
mrs_file="$work_dir/emby.mrs"
classical_file="$work_dir/emby_classical.list"

if ! awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  NF != 2 || $2 == "" { exit 1 }
  $1 != "DOMAIN" && $1 != "DOMAIN-SUFFIX" &&
  $1 != "DOMAIN-KEYWORD" && $1 != "DOMAIN-REGEX" { exit 1 }
' "$source_file"; then
  echo "Emby source contains a malformed or unsupported rule: $source_file" >&2
  exit 1
fi

{
  echo "payload:"
  awk -F, '
    $1 == "DOMAIN" { print $2 }
    $1 == "DOMAIN-SUFFIX" { print "+." $2 }
  ' "$source_file" |
    sort -u |
    awk 'NF { print "  - \047" $0 "\047" }'
} > "$yaml_file"

awk -F, '$1 == "DOMAIN-KEYWORD" || $1 == "DOMAIN-REGEX"' "$source_file" |
  sort -u > "$classical_file"

if [[ $(wc -l < "$yaml_file") -le 1 || ! -s "$classical_file" ]]; then
  echo "Emby source produced an unexpectedly empty rule layer" >&2
  exit 1
fi

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"

printf '%s\n' \
  'mode: rule' \
  'rule-providers:' \
  '  emby_classical:' \
  '    type: file' \
  '    behavior: classical' \
  '    format: text' \
  '    path: ./emby_classical.list' \
  'rules:' \
  '  - RULE-SET,emby_classical,DIRECT' \
  '  - MATCH,DIRECT' > "$work_dir/provider-test.yaml"
mihomo -t -d "$work_dir" -f "$work_dir/provider-test.yaml"

cp "$source_file" rules/Domain/emby.list
cp "$yaml_file" "$mrs_file" "$classical_file" rules/Domain/

# The former IP source disappeared upstream and the remaining host /32s age too
# quickly to be a reliable public rule. Suppress the stale files restored by the
# upstream rules mirror; Emby routing is domain/classical-only now.
rm -f rules/IP/emby-ip.yaml rules/IP/emby-ip.mrs
