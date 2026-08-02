#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building google ==="

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/geo/geosite/google-play.list" \
  -o "$work_dir/google-play.list"
curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/refs/heads/meta/geo/geosite/google.list" \
  -o "$work_dir/google.list"

# awk processes files as records, so a missing trailing newline cannot join two
# domains into one syntactically valid but useless rule.
awk '!/^[[:space:]]*(#|$)/ { print }' \
  "$work_dir/google-play.list" "$work_dir/google.list" |
  sort -u > "$work_dir/merged.list"

for required_domain in \
  redirector.c.play.google.com \
  google-ohttp-relay-safebrowsing.fastly-edge.com; do
  if ! grep -Fxq "$required_domain" "$work_dir/merged.list"; then
    echo "Google source is missing expected domain: $required_domain" >&2
    exit 1
  fi
done

# Remove exact/narrow rules already covered by a broader +. suffix in this set.
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
        if (!is_suffix && domain == parent) { covered = 1; break }
        if (domain != parent && length(domain) > length(parent) &&
            substr(domain, length(domain) - length(parent)) == "." parent) {
          covered = 1
          break
        }
      }
      if (!covered) print rule
    }
  }
' "$work_dir/merged.list" | sort -u > "$work_dir/compact.list"

if [[ $(wc -l < "$work_dir/compact.list") -lt 600 ]]; then
  echo "Google source shrank below the reviewed minimum" >&2
  exit 1
fi
for required_domain in \
  '+.google.com' \
  '+.googleapis.com' \
  '+.googlevideo.com' \
  '+.gstatic.com' \
  'google-ohttp-relay-safebrowsing.fastly-edge.com'; do
  if ! grep -Fxq "$required_domain" "$work_dir/compact.list"; then
    echo "Compacted Google source is missing expected domain: $required_domain" >&2
    exit 1
  fi
done

yaml_file="$work_dir/google.yaml"
mrs_file="$work_dir/google.mrs"
{
  echo "payload:"
  awk '{ print "  - \047" $0 "\047" }' "$work_dir/compact.list"
} > "$yaml_file"

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
mkdir -p rules/Domain
cp "$yaml_file" "$mrs_file" rules/Domain/
