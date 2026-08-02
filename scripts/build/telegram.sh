#!/usr/bin/env bash
set -euo pipefail
echo "=== Building Telegram ==="

source_dir="sources/Telegram"
output_dir="rules/Telegram"
rules=(TelegramEU TelegramSG TelegramUS)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

command -v mihomo >/dev/null 2>&1 || {
  echo "mihomo is required to build Telegram rules" >&2
  exit 1
}

for rule in "${rules[@]}"; do
  source_file="$source_dir/$rule.yaml"
  yaml_file="$work_dir/$rule.yaml"
  mrs_file="$work_dir/$rule.mrs"

  if [[ ! -s "$source_file" ]]; then
    echo "Missing required Telegram source: $source_file" >&2
    exit 1
  fi

  cp "$source_file" "$yaml_file"
  mihomo convert-ruleset ipcidr yaml "$yaml_file" "$mrs_file"

  if [[ ! -s "$mrs_file" ]]; then
    echo "Failed to build Telegram ruleset: $mrs_file" >&2
    exit 1
  fi
done

# Publish the three regional partitions together only after all compile.
mkdir -p "$output_dir"
cp "$work_dir"/*.yaml "$work_dir"/*.mrs "$output_dir"/
