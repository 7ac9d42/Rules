#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building wechat ==="

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl --fail --show-error --silent --location \
  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/WeChat/WeChat.list" \
  -o "$work_dir/WeChat.list"

# This domain builder intentionally ignores the one declared IP-ASN record, but
# rejects any future rule type instead of silently publishing a partial source.
if ! awk -F, '
  /^[[:space:]]*(#|$)/ { next }
  ($1 == "DOMAIN" || $1 == "DOMAIN-SUFFIX") && NF >= 2 && $2 != "" { next }
  $1 == "IP-ASN" && NF >= 2 && $2 != "" { next }
  { exit 1 }
' "$work_dir/WeChat.list"; then
  echo "WeChat source contains an unknown or malformed rule" >&2
  exit 1
fi

awk -F, '
  $1 == "DOMAIN" { print $2 }
  $1 == "DOMAIN-SUFFIX" { print "+." $2 }
' "$work_dir/WeChat.list" |
  awk '$0 != "apd-pcdnwxlogin.teg.tencent-cloud.net"' |
  sort -u > "$work_dir/domains.list"

if [[ $(wc -l < "$work_dir/domains.list") -lt 20 ]]; then
  echo "WeChat source shrank below the reviewed minimum" >&2
  exit 1
fi
for required_domain in '+.wechat.com' '+.weixin.qq.com' '+.servicewechat.com'; do
  if ! grep -Fxq "$required_domain" "$work_dir/domains.list"; then
    echo "WeChat source is missing expected domain: $required_domain" >&2
    exit 1
  fi
done

{
  echo "payload:"
  awk '{ print "  - \047" $0 "\047" }' "$work_dir/domains.list"
} > "$work_dir/WeChat.yaml"

mihomo convert-ruleset domain yaml \
  "$work_dir/WeChat.yaml" "$work_dir/WeChat.mrs"
mkdir -p rules/Domain
cp "$work_dir/WeChat.yaml" "$work_dir/WeChat.mrs" rules/Domain/
