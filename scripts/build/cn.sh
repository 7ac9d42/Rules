#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

echo "=== Building cn ==="

work_dir=$(mktemp -d)
cleanup() {
  rm -f -- "$work_dir/cn-base.list" "$work_dir/ChinaMax_Domain.txt" \
    "$work_dir/direct-need-to-remove.txt" "$work_dir/cn.yaml" "$work_dir/cn.mrs"
  rmdir -- "$work_dir"
}
trap cleanup EXIT

fetch() {
  curl --fail --show-error --silent --location \
    --connect-timeout 10 --max-time 30 --retry 1 --retry-delay 1 \
    "$1" -o "$2"
}

fetch "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/cn.list" \
  "$work_dir/cn-base.list"
fetch "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/ChinaMax/ChinaMax_Domain.txt" \
  "$work_dir/ChinaMax_Domain.txt"
fetch "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/master/resouces/direct-need-to-remove.txt" \
  "$work_dir/direct-need-to-remove.txt"

ruby - "$work_dir" <<'RUBY'
directory = ARGV.fetch(0)
read_entries = lambda do |filename|
  File.readlines(File.join(directory, filename), chomp: true).map(&:strip)
    .reject { |line| line.empty? || line.start_with?('#') }
end
base = read_entries.call('cn-base.list')
china = read_entries.call('ChinaMax_Domain.txt')
removed = read_entries.call('direct-need-to-remove.txt').to_h { |line| [line, true] }
abort 'CN source is empty or has shrunk below the reviewed minimum' if base.length < 50_000 || china.length < 50_000

# 保留基准匹配语义；只去掉上游 full:host 转换缺陷产生的伪后缀。
base.delete('+.full')
pattern = /\A(?:\+\.|\.)?(?:\*|[a-zA-Z0-9_-]+)(?:\.(?:\*|[a-zA-Z0-9_-]+))*\z/
abort 'CN base contains an invalid domain pattern' unless base.all? { |line| pattern.match?(line) }
entries = base.to_h { |line| [line, true] }
suffixes = base.select { |line| line.start_with?('+.') }.to_h { |line| [line.delete_prefix('+.'), true] }
exact = china.reject { |line| line.start_with?('.') }
abort 'ChinaMax exact-domain source is unexpectedly empty' if exact.empty?
abort 'ChinaMax contains an invalid exact domain' unless exact.all? { |line| /\A[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\z/.match?(line) }

before = entries.length
exact.each do |domain|
  # 沿用上游过滤；删除清单按原始 full:host 精确相减，不扩大为后缀排除。
  next if /google|manhua|ooklaserver|acg.rip/.match?(domain) || removed["full:#{domain}"]
  next if entries[domain]

  labels = domain.split('.')
  next if labels.each_index.any? { |index| suffixes[labels[index..].join('.')] }

  entries[domain] = true
end
File.open(File.join(directory, 'cn.yaml'), 'w') do |file|
  file.puts 'payload:'
  entries.keys.sort.each { |domain| file.puts "  - '#{domain}'" }
end
puts "CN: #{entries.length} rules, restored #{entries.length - before} exact domains"
RUBY

if ! convert_output=$(mihomo convert-ruleset domain yaml "$work_dir/cn.yaml" "$work_dir/cn.mrs" 2>&1); then
  printf '%s\n' "$convert_output" >&2
  exit 1
fi
if [[ "$convert_output" == *"invalid domain:"* ]]; then
  printf '%s\n' "$convert_output" >&2
  echo "Mihomo rejected a CN domain rule" >&2
  exit 1
fi
[[ -z "$convert_output" ]] || printf '%s\n' "$convert_output"
[[ -s "$work_dir/cn.mrs" ]]

mkdir -p rules/Domain
cp "$work_dir/cn.yaml" "$work_dir/cn.mrs" rules/Domain/
