#!/usr/bin/env bash
set -euo pipefail
echo "=== Building game-mrs ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Game/game-mrs.mrs" ] && git diff --quiet HEAD -- "rules/Game/" 2>/dev/null; then
  echo "Sources for game-mrs unchanged, skipping build."
  exit 0
fi

# Create temporary folder for YAML files
mkdir -p rules/Game/action2

# Get total number of YAML files
# 获取文件总数
response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/Lanlan13-14/Rules/contents/rules/Game?ref=main")
total_files=$(echo "$response" | jq -r '[.[] | select(.name | test(".yaml$"))] | length')
echo "Total YAML files: $total_files"
echo "TOTAL_FILES=$total_files" >> $GITHUB_ENV

# Download YAML files via GitHub API
cd rules/Game/action2
total_files=$TOTAL_FILES
per_page=1000

if [ $total_files -le $per_page ]; then
  # 如果总文件数小于等于1000，直接拉取所有文件
  response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/Lanlan13-14/Rules/contents/rules/Game?ref=main")
  files=$(echo "$response" | jq -r '.[].download_url' | grep '\.yaml$')
  for url in $files; do
    echo "Downloading $url"
    curl -sL "$url" -O
  done
elif [ $total_files -le 2000 ]; then
  # 如果总文件数小于等于2000，分两次拉取
  for page in 1 2; do
    echo "Fetching page $page"
    response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/Lanlan13-14/Rules/contents/rules/Game?ref=main&page=$page&per_page=$per_page")
    files=$(echo "$response" | jq -r '.[].download_url' | grep '\.yaml$')
    for url in $files; do
      echo "Downloading $url"
      curl -sL "$url" -O
    done
  done
elif [ $total_files -le 3000 ]; then
  # 如果总文件数小于等于3000，分三次拉取
  for page in 1 2 3; do
    echo "Fetching page $page"
    response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/Lanlan13-14/Rules/contents/rules/Game?ref=main&page=$page&per_page=$per_page")
    files=$(echo "$response" | jq -r '.[].download_url' | grep '\.yaml$')
    for url in $files; do
      echo "Downloading $url"
      curl -sL "$url" -O
    done
  done
else
  # 如果文件数大于3000，分四次拉取
  total_pages=$((($total_files + $per_page - 1) / $per_page))
  for ((page=1; page<=$total_pages; page++)); do
    echo "Fetching page $page"
    response=$(curl -s -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/Lanlan13-14/Rules/contents/rules/Game?ref=main&page=$page&per_page=$per_page")
    files=$(echo "$response" | jq -r '.[].download_url' | grep '\.yaml$')
    for url in $files; do
      echo "Downloading $url"
      curl -sL "$url" -O
    done
  done
fi
cd -

# Process and convert each YAML file
# 对每个 YAML 文件，先使用 Perl 清除单引号内前后多余空格，再调用 mihomo 转换
for file in rules/Game/action2/*.yaml; do
  echo "Processing file: $file"
  # Perl 命令：将单引号内的内容两侧多余空格去掉，保留内容
  perl -i -pe "s/'\s*([^']*?)\s*'/'\$1'/g" "$file"
  base=$(basename "$file" .yaml)
  output="rules/Game/${base}.mrs"
  echo "Converting $file to $output"
  mihomo convert-ruleset ipcidr yaml "$file" "$output"
done

# Remove temporary folder
rm -rf rules/Game/action2

