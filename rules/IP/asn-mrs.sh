#!/usr/bin/env bash
set -euo pipefail
echo "=== Building asn-mrs ==="

# Create temporary folders
mkdir -p rules/IP/asn rules/IP/asn-yaml

# Get total number of .list files
response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/MetaCubeX/meta-rules-dat/contents/asn?ref=meta")
total_files=$(echo "$response" | jq -r '[.[] | select(.name | test(".list$"))] | length')
echo "Total .list files: $total_files"
echo "TOTAL_FILES=$total_files" >> $GITHUB_ENV

# Download .list files via GitHub API
cd rules/IP/asn
total_files=$TOTAL_FILES
per_page=1000

if [ $total_files -le $per_page ]; then
  response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/MetaCubeX/meta-rules-dat/contents/asn?ref=meta")
  files=$(echo "$response" | jq -r '.[].download_url' | grep '\.list$')
else
  total_pages=$((($total_files + $per_page - 1) / $per_page))
  files=""
  for ((page=1; page<=$total_pages; page++)); do
    response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/MetaCubeX/meta-rules-dat/contents/asn?ref=meta&page=$page&per_page=$per_page")
    files+=$(echo "$response" | jq -r '.[].download_url' | grep '\.list$')$'\n'
  done
fi

for url in $files; do
  echo "Downloading $url"
  curl -sL "$url" -O
done
cd -

# Convert .list files to .yaml (filter out private IPs)
for file in rules/IP/asn/*.list; do
  [ -f "$file" ] || continue
  base=$(basename "$file" .list)
  output="rules/IP/asn-yaml/${base}.yaml"
  echo "Converting $file to $output"
  echo "payload:" > "$output"

  valid=false
  while IFS= read -r line; do
    if [[ -n "$line" && ! "$line" =~ ^(10\..*|172\.(1[6-9]|2[0-9]|3[01])\..*|192\.168\..*|169\.254\..*|22[4-9]\..*|2[3-5][0-9]\..*)$ ]]; then
      echo "  - '$line'" >> "$output"
      valid=true
    fi
  done < "$file"

  # 如果 YAML 文件内容为空（只包含 "payload:"），则删除该文件
  if ! $valid; then
    echo "Deleting empty YAML file: $output"
    rm -f "$output"
  fi
done

# Convert .yaml files to .mrs
for file in rules/IP/asn-yaml/*.yaml; do
  [ -f "$file" ] || continue
  base=$(basename "$file" .yaml)
  output="rules/IP/${base}.mrs"
  echo "Converting $file to $output"
  mihomo convert-ruleset ipcidr yaml "$file" "$output"
done

# Move YAML files to rules/IP
mv rules/IP/asn-yaml/*.yaml rules/IP/

# Remove temporary folders
rm -rf rules/IP/asn rules/IP/asn-yaml

