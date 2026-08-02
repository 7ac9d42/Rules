#!/usr/bin/env bash
set -euo pipefail
echo "=== Building banAd ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
classical_file="$work_dir/banAd_classical.list"
provider_test_config="$work_dir/provider-test.yaml"
yaml_file="$work_dir/banAd.yaml"
mrs_file="$work_dir/banAd.mrs"

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
' "$work_dir/qx.list" rules/Domain/pcdn.list > "$work_dir/domains.list"

jq -r '.rules[].domain[]?' "$work_dir/pcdn.json" >> "$work_dir/domains.list"
jq -r '.rules[].domain_suffix[]?' "$work_dir/pcdn.json" |
  sed -E 's/^\.?/+./' >> "$work_dir/domains.list"

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
sort -u "$classical_file" -o "$classical_file"

if [[ ! -s "$classical_file" ]]; then
  echo "banAd classical layer is unexpectedly empty" >&2
  exit 1
fi

{
  echo "payload:"
  sed -E 's/^\*\./+./' "$work_dir/domains.list" |
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
    ' |
    sort -u |
    awk 'NF { print "  - \047" $0 "\047" }'
} > "$yaml_file"

mihomo convert-ruleset domain yaml \
  "$yaml_file" "$mrs_file"

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
