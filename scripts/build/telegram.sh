#!/usr/bin/env bash
set -euo pipefail
echo "=== Building Telegram ==="

source_dir="sources/Telegram"
output_dir="rules/Telegram"
source_file="$source_dir/Telegram.yaml"
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
yaml_file="$work_dir/Telegram.yaml"
mrs_file="$work_dir/Telegram.mrs"

command -v mihomo >/dev/null 2>&1 || {
  echo "mihomo is required to build Telegram rules" >&2
  exit 1
}

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

# The upstream mirror still contains the retired regional partitions.
# Remove them only after the unified replacement compiles successfully.
legacy_outputs=(
  "$output_dir/TelegramEU.yaml"
  "$output_dir/TelegramEU.mrs"
  "$output_dir/TelegramSG.yaml"
  "$output_dir/TelegramSG.mrs"
  "$output_dir/TelegramUS.yaml"
  "$output_dir/TelegramUS.mrs"
)
rm -f -- "${legacy_outputs[@]}"

# Publish the unified rule.
mkdir -p "$output_dir"
cp "$yaml_file" "$mrs_file" "$output_dir"/
