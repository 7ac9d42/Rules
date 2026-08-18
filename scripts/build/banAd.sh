#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
classical_file="$work_dir/banAd_classical.list"
wildcard_classical_file="$work_dir/banAd_wildcard_classical.list"
provider_test_config="$work_dir/provider-test.yaml"
yaml_file="$work_dir/banAd.yaml"
mrs_file="$work_dir/banAd.mrs"
raw_domains_file="$work_dir/domains.raw.list"
domains_file="$work_dir/domains.list"

curl --fail --show-error --silent --location \
  --retry 4 --retry-all-errors --retry-delay 2 \
  "https://raw.githubusercontent.com/8680/GOODBYEADS/master/data/rules/qx.list" \
  -o "$work_dir/qx.list"
curl --fail --show-error --silent --location \
  --retry 4 --retry-all-errors --retry-delay 2 \
  "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" \
  -o "$work_dir/pcdn.json"

# Parse the rule type before the value. Two loose grep expressions made
# DOMAIN-SUFFIX either disappear under pipefail or be treated as an exact domain.
awk -F, '
  $1 == "DOMAIN" && $2 != "" { sub(/\.$/, "", $2); print $2 }
  $1 == "DOMAIN-SUFFIX" && $2 != "" {
    sub(/^\./, "", $2)
    sub(/\.$/, "", $2)
    print "+." $2
  }
' "$work_dir/qx.list" rules/Domain/pcdn.list > "$raw_domains_file"

jq -r '.rules[].domain[]?' "$work_dir/pcdn.json" >> "$raw_domains_file"
jq -r '.rules[].domain_suffix[]?' "$work_dir/pcdn.json" |
  sed -E 's/^\.?/+./' >> "$raw_domains_file"

# Mihomo v1.19.30 only accepts `*` as a complete domain label. Preserve
# embedded-wildcard rules as bounded regular expressions instead of letting the
# domain converter silently discard them.
awk -v classical_file="$wildcard_classical_file" '
  function glob_regex(value, result, i, char) {
    result = "(?i)^"
    for (i = 1; i <= length(value); i++) {
      char = substr(value, i, 1)
      if (char == "*") result = result "[^.]*"
      else {
        if (index("\\.^$|?+()[]{}", char)) result = result "\\"
        result = result char
      }
    }
    return result "$"
  }
  BEGIN { printf "" > classical_file }
  NF {
    value = $0
    count = split(value, labels, ".")
    partial_wildcard = 0
    for (i = 1; i <= count; i++) {
      if (index(labels[i], "*") && labels[i] != "*") partial_wildcard = 1
    }
    if (partial_wildcard) {
      print "DOMAIN-REGEX," glob_regex(value) > classical_file
      next
    }
    sub(/^\*\./, "+.", value)
    print value
  }
' "$raw_domains_file" > "$domains_file"

# domain MRS 无法承载关键词/正则；单独发布 classical，不能静默丢弃 PCDN 规则。
jq -r '
  .rules[] |
  (
    (.domain_keyword[]? | "DOMAIN-KEYWORD," + .),
    (
      .domain_regex[]? |
      if startswith("^") and endswith("$") then . else "^(" + . + ")$" end |
      "DOMAIN-REGEX," + .
    )
  )
' "$work_dir/pcdn.json" > "$classical_file"
awk '/^DOMAIN-(KEYWORD|REGEX),/' "$work_dir/qx.list" rules/Domain/pcdn.list >> "$classical_file"
sort -u "$classical_file" "$wildcard_classical_file" -o "$classical_file"

if [[ ! -s "$classical_file" ]]; then
  echo "banAd classical layer is unexpectedly empty" >&2
  exit 1
fi

{
  echo "payload:"
  # IP literals are not domain rules. Activating them in a domain provider is
  # ineffective; promoting stale advertising IPs would also overblock shared
  # hosting, so the legacy domain artifact deliberately excludes them.
  awk '
      function is_ipv4(value, count, octet, i) {
        sub(/^\+\./, "", value)
        count = split(value, octet, ".")
        if (count != 4) return 0
        for (i = 1; i <= 4; i++) {
          if (octet[i] !~ /^[0-9]+$/ || octet[i] < 0 || octet[i] > 255) return 0
        }
        return 1
      }
      NF && !is_ipv4($0) && index($0, ":") == 0 { print }
    ' "$domains_file" |
    sort -u |
    awk 'NF { print "  - \047" $0 "\047" }'
} > "$yaml_file"

if ! convert_output=$(mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file" 2>&1); then
  printf '%s\n' "$convert_output" >&2
  exit 1
fi
if [[ "$convert_output" == *"invalid domain:"* ]]; then
  printf '%s\n' "$convert_output" >&2
  echo "Mihomo rejected a generated domain rule" >&2
  exit 1
fi
[[ -z "$convert_output" ]] || printf '%s\n' "$convert_output"

printf '%s\n' \
  'mode: rule' \
  'rule-providers:' \
  '  banAd_classical:' \
  '    type: file' \
  '    behavior: classical' \
  '    format: text' \
  '    path: ./banAd_classical.list' \
  'rules:' \
  '  - RULE-SET,banAd_classical,REJECT' \
  '  - MATCH,DIRECT' > "$provider_test_config"
mihomo -t -d "$work_dir" -f "$provider_test_config"

cp "$yaml_file" "$mrs_file" "$classical_file" rules/Domain/
