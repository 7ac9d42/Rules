#!/usr/bin/env bash
set -euo pipefail
echo "=== Building tvb ==="

mkdir -p rules/Domain
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/btjson/loon/refs/heads/main/TVB.list" \
  -o "$work_dir/tvb.list"

# USER-AGENT is a declared non-domain record and is intentionally not emitted.
if ! awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  ($1 == "DOMAIN" || $1 == "DOMAIN-SUFFIX") && NF >= 2 && $2 != "" { next }
  $1 == "USER-AGENT" && NF >= 2 && $2 != "" { next }
  { print "Unsupported TVB rule: " $0 > "/dev/stderr"; exit 1 }
' "$work_dir/tvb.list"; then
  echo "TVB source contains an unknown or malformed rule" >&2
  exit 1
fi

yaml_file="$work_dir/tvb.yaml"
mrs_file="$work_dir/tvb.mrs"

awk -F, '
  $1 == "DOMAIN" && $2 != "" { print $2 }
  $1 == "DOMAIN-SUFFIX" && $2 != "" {
    sub(/^\*\./, "", $2)
    sub(/^\./, "", $2)
    print "+." $2
  }
' "$work_dir/tvb.list" |
  awk '$0 == "+.youboranqs01.com" {
         print "infinity-c15.youboranqs01.com"
         next
       }
       { print }' |
  grep -Fvx -e '+.content.jwplatform.com' \
    -e '+.videos-f.jwpsrv.com' \
    -e 'edge.api.brightcove.com' \
    -e 'bcbolt446c5271-a.akamaihd.net' |
  sort -u > "$work_dir/domains.list"

# TVB's upstream repeats children already covered by a parent suffix.
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
' "$work_dir/domains.list" | sort -u > "$work_dir/compact.list"

{
  echo "payload:"
  awk '{ print "  - \047" $0 "\047" }' "$work_dir/compact.list"
} > "$yaml_file"

if [[ $(wc -l < "$work_dir/compact.list") -lt 15 ]]; then
  echo "TVB source shrank below the reviewed minimum" >&2
  exit 1
fi
for required_domain in '+.tvb.com' '+.mytvsuper.com' 'infinity-c15.youboranqs01.com'; do
  if ! grep -Fxq "$required_domain" "$work_dir/compact.list"; then
    echo "TVB source is missing expected domain: $required_domain" >&2
    exit 1
  fi
done

mihomo convert-ruleset domain yaml "$yaml_file" "$mrs_file"
cp "$yaml_file" "$mrs_file" rules/Domain/
