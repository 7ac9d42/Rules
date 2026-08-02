#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building layered banAd rules ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

awa_full_json="$work_dir/awa_full.json"
awa_core_json="$work_dir/awa_core.json"
pcdn_json="$work_dir/pcdn.json"
full_domains="$work_dir/full_domains.list"
core_domains="$work_dir/core_domains.list"
raw_core_domains="$work_dir/raw_core_domains.list"
raw_pcdn_domains="$work_dir/raw_pcdn_domains.list"
pcdn_regex_patterns="$work_dir/pcdn_regex_patterns.json"
pcdn_regex_matches="$work_dir/pcdn_regex_matches.list"
pcdn_domain_candidates="$work_dir/pcdn_domain_candidates.list"
filtered_pcdn_domains="$work_dir/filtered_pcdn_domains.list"
pcdn_domains="$work_dir/pcdn_domains.list"
early_block_domains="$work_dir/early_block_domains.list"
raw_low_domains="$work_dir/raw_low_domains.list"
low_domains="$work_dir/low_domains.list"
combined_domains="$work_dir/combined_domains.list"
expected_domains="$work_dir/expected_domains.list"
unexpected_combined="$work_dir/unexpected_combined.list"
uncovered_expected="$work_dir/uncovered_expected.list"
shadowed_pcdn="$work_dir/shadowed_pcdn.list"
shadowed_low="$work_dir/shadowed_low.list"
invalid_core="$work_dir/invalid_core.list"
full_classical="$work_dir/full_classical.list"
core_classical="$work_dir/core_classical.list"
raw_pcdn_classical="$work_dir/raw_pcdn_classical.list"
pcdn_classical="$work_dir/pcdn_classical.list"
invalid_core_classical="$work_dir/invalid_core_classical.list"
unsupported_low_classical="$work_dir/unsupported_low_classical.list"

full_yaml_file="$work_dir/banAd_mini.yaml"
full_mrs_file="$work_dir/banAd_mini.mrs"
core_yaml_file="$work_dir/banAd_core.yaml"
core_mrs_file="$work_dir/banAd_core.mrs"
pcdn_yaml_file="$work_dir/banAd_pcdn.yaml"
pcdn_mrs_file="$work_dir/banAd_pcdn.mrs"
low_yaml_file="$work_dir/banAd_low.yaml"
low_mrs_file="$work_dir/banAd_low.mrs"
core_classical_file="$work_dir/banAd_core_classical.list"
pcdn_classical_file="$work_dir/banAd_pcdn_classical.list"
provider_test_config="$work_dir/provider-test.yaml"
local_pcdn_sources=(
  rules/Domain/pcdn.list
  scripts/data/banAd_pcdn_extra.list
)

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/refs/heads/main/Filters/AWAvenue-Ads-Rule-Singbox.json" \
  -o "$awa_full_json"
curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/refs/heads/main/Filters/AWAvenue-Ads-Rule-Singbox-No.Unwelcome.json" \
  -o "$awa_core_json"
curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/DDCHlsq/sing-ruleset/refs/heads/master/pcdn.json" \
  -o "$pcdn_json"

extract_domains() {
  local source_file=$1
  local output_file=$2

  jq -r '
    .rules[] |
    (.domain[]?, (.domain_suffix[]? | ltrimstr(".") | "+." + .))
  ' "$source_file" | sort -u > "$output_file"
}

extract_classical() {
  local source_file=$1
  local output_file=$2
  local harden_keywords=${3:-false}
  local raw_output="${output_file}.raw"

  if jq -e 'any(.rules[] | (.domain_keyword[]?, .domain_regex[]?); contains(","))' \
    "$source_file" > /dev/null; then
    echo "Classical domain rule contains an unsupported comma: $source_file" >&2
    exit 1
  fi

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
  ' "$source_file" | sort -u > "$raw_output"

  if [[ "$harden_keywords" == true ]]; then
    # AWAvenue core keywords are domain-tail fragments. Keep that intent while
    # preventing a hostname with an unrelated parent suffix from matching.
    awk -F, '
      function regex_escape(value, result, i, char) {
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          if (index("\\.^$|?*+()[]{}", char)) result = result "\\" char
          else result = result char
        }
        return result
      }
      $1 == "DOMAIN-KEYWORD" {
        value = substr($0, index($0, ",") + 1)
        print "DOMAIN-REGEX,(?i)(^|\\.)[^.]*" regex_escape(value) "$"
        next
      }
      { print }
    ' "$raw_output" | sort -u > "$output_file"
  else
    mv "$raw_output" "$output_file"
  fi
}

validate_domain_source() {
  local source_file=$1

  if ! jq -e '
    ((.rules | type) == "array") and
    ((.rules | length) > 0) and
    all(.rules[];
      (type == "object") and
      ([keys[] | select(
        . != "domain" and
        . != "domain_suffix" and
        . != "domain_keyword" and
        . != "domain_regex" and
        . != "ip_cidr" and
        . != "invert"
      )] | length == 0) and
      (.invert == null or .invert == false) and
      (.domain == null or ((.domain | type) == "array" and all(.domain[]; type == "string" and length > 0))) and
      (.domain_suffix == null or ((.domain_suffix | type) == "array" and all(.domain_suffix[]; type == "string" and length > 0))) and
      (.domain_keyword == null or ((.domain_keyword | type) == "array" and all(.domain_keyword[]; type == "string" and length > 0))) and
      (.domain_regex == null or ((.domain_regex | type) == "array" and all(.domain_regex[]; type == "string" and length > 0))) and
      (.ip_cidr == null or ((.ip_cidr | type) == "array" and (.ip_cidr | length) == 0))
    )
  ' "$source_file" > /dev/null; then
    echo "Source contains an inverted, malformed, or unsupported rule: $source_file" >&2
    exit 1
  fi
}

validate_local_pcdn_source() {
  local source_file=$1

  if ! awk -F, '
    /^[[:space:]]*(#|$)/ { next }
    NF != 2 || $2 == "" { exit 1 }
    $1 !~ /^DOMAIN(-SUFFIX|-KEYWORD|-REGEX)?$/ { exit 1 }
  ' "$source_file"; then
    echo "Local PCDN source contains a malformed or unsupported rule: $source_file" >&2
    exit 1
  fi
}

# 输出 source 中未被 blockers 完整覆盖的规则。`+.example.com` 同时覆盖根域和全部子域。
subtract_covered_domains() {
  local blockers_file=$1
  local source_file=$2
  local output_file=$3

  awk '
    NR == FNR {
      if ($0 == "") next
      exact[$0] = 1
      if (substr($0, 1, 2) == "+.") suffix[substr($0, 3)] = 1
      next
    }
    function covered(rule, domain, parent) {
      if (rule in exact) return 1
      domain = substr(rule, 1, 2) == "+." ? substr(rule, 3) : rule
      for (parent in suffix) {
        if (domain == parent) return 1
        if (length(domain) > length(parent) &&
            substr(domain, length(domain) - length(parent)) == "." parent) return 1
      }
      return 0
    }
    NF && !covered($0) { print }
  ' "$blockers_file" "$source_file" > "$output_file"
}

# 同一层内删除被更宽 `+.` 后缀完整覆盖的精确域名或更窄后缀。
compact_domain_layer() {
  local source_file=$1
  local output_file=$2

  awk '
    NF {
      rules[++count] = $0
      if (substr($0, 1, 2) == "+.") suffix[substr($0, 3)] = 1
    }
    END {
      for (i = 1; i <= count; i++) {
        rule = rules[i]
        is_suffix = substr(rule, 1, 2) == "+."
        domain = is_suffix ? substr(rule, 3) : rule
        covered = 0
        for (parent in suffix) {
          if (!is_suffix && domain == parent) {
            covered = 1
            break
          }
          if (domain != parent && length(domain) > length(parent) &&
              substr(domain, length(domain) - length(parent)) == "." parent) {
            covered = 1
            break
          }
        }
        if (!covered) print rule
      }
    }
  ' "$source_file" > "$output_file"
}

find_covered_domains() {
  local blockers_file=$1
  local source_file=$2
  local output_file=$3
  local uncovered_file="${output_file}.uncovered"

  subtract_covered_domains "$blockers_file" "$source_file" "$uncovered_file"
  comm -23 "$source_file" "$uncovered_file" > "$output_file"
  rm -f "$uncovered_file"
}

validate_domain_source "$awa_full_json"
validate_domain_source "$awa_core_json"
validate_domain_source "$pcdn_json"
for source_file in "${local_pcdn_sources[@]}"; do
  validate_local_pcdn_source "$source_file"
done
extract_domains "$awa_full_json" "$full_domains"
extract_domains "$awa_core_json" "$raw_core_domains"
compact_domain_layer "$raw_core_domains" "$core_domains"
extract_domains "$pcdn_json" "$raw_pcdn_domains"
extract_classical "$awa_full_json" "$full_classical" true
extract_classical "$awa_core_json" "$core_classical" true
extract_classical "$pcdn_json" "$raw_pcdn_classical"

if [[ ! -s "$full_domains" || ! -s "$core_domains" || ! -s "$core_classical" ]]; then
  echo "Upstream source produced an unexpectedly empty rule layer" >&2
  exit 1
fi

# 本地 PCDN 补充与 DDCH 规则合并，再按实际覆盖关系排除已归入 core 的规则。
awk -F, '
  $1 == "DOMAIN" && $2 != "" { print $2 }
  $1 == "DOMAIN-SUFFIX" && $2 != "" { print "+." $2 }
' "${local_pcdn_sources[@]}" >> "$raw_pcdn_domains"
sort -u "$raw_pcdn_domains" -o "$raw_pcdn_domains"

awk '/^DOMAIN-(KEYWORD|REGEX),/' "${local_pcdn_sources[@]}" >> "$raw_pcdn_classical"
sort -u "$raw_pcdn_classical" -o "$raw_pcdn_classical"

# 将命中 PCDN 正则的 AWAvenue 精确域名提升到 PCDN 域名层，避免它们留在后置 low 中失效。
awk -F, '$1 == "DOMAIN-REGEX" { print substr($0, index($0, ",") + 1) }' \
  "$raw_pcdn_classical" |
  jq -Rsc 'split("\n") | map(select(length > 0))' > "$pcdn_regex_patterns"
jq -Rr --slurpfile patterns "$pcdn_regex_patterns" '
  select(length > 0) as $domain |
  select(($domain | startswith("+.")) | not) |
  select([$patterns[0][] as $pattern | $domain | test($pattern)] | any)
' "$full_domains" > "$pcdn_regex_matches"
sort -u "$raw_pcdn_domains" "$pcdn_regex_matches" > "$pcdn_domain_candidates"

# core 必须始终是 AWAvenue full 的子集，否则上游分类结构已改变。
comm -23 "$core_domains" "$full_domains" > "$invalid_core"
comm -23 "$core_classical" "$full_classical" > "$invalid_core_classical"
if [[ -s "$invalid_core" || -s "$invalid_core_classical" ]]; then
  echo "AWAvenue core is not a subset of the full rule set" >&2
  exit 1
fi

# PCDN 是明确拦截目标，单独前置；按 Mihomo 后缀语义去除已被 core 覆盖及层内冗余规则。
subtract_covered_domains "$core_domains" "$pcdn_domain_candidates" "$filtered_pcdn_domains"
compact_domain_layer "$filtered_pcdn_domains" "$pcdn_domains"

# `+.xycdn.com` 已覆盖这些精确子域及专用正则，无需再维护重复匹配。
if grep -Fxq '+.xycdn.com' "$pcdn_domains"; then
  awk '$0 != "DOMAIN-REGEX,^(seeds.*-darwin\\.xycdn\\.com)$"' \
    "$raw_pcdn_classical" > "$work_dir/pcdn_classical_without_xycdn.list"
else
  cp "$raw_pcdn_classical" "$work_dir/pcdn_classical_without_xycdn.list"
fi
comm -23 "$work_dir/pcdn_classical_without_xycdn.list" "$core_classical" > "$pcdn_classical"

# low 只保留未被 core/PCDN 先行规则完整覆盖的 AWAvenue Unwelcome。
sort -u "$core_domains" "$pcdn_domains" > "$early_block_domains"
subtract_covered_domains "$early_block_domains" "$full_domains" "$raw_low_domains"
compact_domain_layer "$raw_low_domains" "$low_domains"

sort -u "$core_domains" "$pcdn_domains" "$low_domains" > "$combined_domains"
sort -u "$full_domains" "$raw_pcdn_domains" > "$expected_domains"

find_covered_domains "$core_domains" "$pcdn_domains" "$shadowed_pcdn"
find_covered_domains "$early_block_domains" "$low_domains" "$shadowed_low"
comm -23 "$combined_domains" "$expected_domains" > "$unexpected_combined"
subtract_covered_domains "$combined_domains" "$expected_domains" "$uncovered_expected"
if [[ -s "$shadowed_pcdn" || -s "$shadowed_low" ||
      -s "$unexpected_combined" || -s "$uncovered_expected" ]]; then
  echo "Generated domain layers contain shadowed rules or do not preserve source coverage" >&2
  exit 1
fi

comm -23 "$full_classical" "$core_classical" > "$unsupported_low_classical"
if [[ -s "$unsupported_low_classical" ]]; then
  echo "AWAvenue Unwelcome contains new classical rules; update the layer mapping" >&2
  exit 1
fi

if [[ ! -s "$pcdn_domains" || ! -s "$pcdn_classical" || ! -s "$low_domains" ]]; then
  echo "Upstream source produced an unexpectedly empty rule layer" >&2
  exit 1
fi

build_ruleset() {
  local source_file=$1
  local output_yaml=$2
  local output_mrs=$3

  echo "payload:" > "$output_yaml"
  awk 'NF { print "  - \047" $0 "\047" }' "$source_file" >> "$output_yaml"
  mihomo convert-ruleset domain yaml "$output_yaml" "$output_mrs"
}

# 保留原有 banAd_mini 域名全集，避免破坏已有外部引用。
build_ruleset "$combined_domains" "$full_yaml_file" "$full_mrs_file"
build_ruleset "$core_domains" "$core_yaml_file" "$core_mrs_file"
build_ruleset "$pcdn_domains" "$pcdn_yaml_file" "$pcdn_mrs_file"
build_ruleset "$low_domains" "$low_yaml_file" "$low_mrs_file"
cp "$core_classical" "$core_classical_file"
cp "$pcdn_classical" "$pcdn_classical_file"

printf '%s\n' \
  'mode: rule' \
  'rule-providers:' \
  '  core_classical:' \
  '    type: file' \
  '    behavior: classical' \
  '    format: text' \
  '    path: ./banAd_core_classical.list' \
  '  pcdn_classical:' \
  '    type: file' \
  '    behavior: classical' \
  '    format: text' \
  '    path: ./banAd_pcdn_classical.list' \
  'rules:' \
  '  - RULE-SET,core_classical,REJECT' \
  '  - RULE-SET,pcdn_classical,REJECT' \
  '  - MATCH,DIRECT' > "$provider_test_config"
mihomo -t -d "$work_dir" -f "$provider_test_config"

cp \
  "$full_yaml_file" "$full_mrs_file" \
  "$core_yaml_file" "$core_mrs_file" \
  "$pcdn_yaml_file" "$pcdn_mrs_file" \
  "$low_yaml_file" "$low_mrs_file" \
  "$core_classical_file" "$pcdn_classical_file" \
  rules/Domain/
