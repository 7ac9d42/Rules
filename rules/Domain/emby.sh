#!/usr/bin/env bash
set -euo pipefail
echo "=== Building emby ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/emby.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for emby unchanged, skipping build."
  exit 0
fi

# Fetch and Merge Emby Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 Emby 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/emby.list" -o rules/Domain/emby1.list
curl -sL "https://raw.githubusercontent.com/666OS/YYDS/main/mihomo/rules/emby.list" -o rules/Domain/emby2.list

# 合并去重并排除包含 IC DR 的规则
cat rules/Domain/emby1.list rules/Domain/emby2.list | grep -v '^#' | grep -v 'IC DR' | sort -u > rules/Domain/merged_emby.list

# Convert Emby Rules to YAML
echo "payload:" > rules/Domain/emby.yaml
while IFS=, read -r type value; do
  if [[ -n "$type" && -n "$value" ]]; then
    # 处理 DOMAIN 规则，直接加入
    if [[ "$type" == "DOMAIN" ]]; then
      echo "  - $value" >> rules/Domain/emby.yaml
    # 处理 DOMAIN-SUFFIX 规则，加上 *.
    elif [[ "$type" == "DOMAIN-SUFFIX" ]]; then
      echo "  - '*.$value'" >> rules/Domain/emby.yaml
    fi
  fi
done < rules/Domain/merged_emby.list

# Convert Emby Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/emby.yaml rules/Domain/emby.mrs

# Clean up the source files
# 删除源文件
rm -f rules/Domain/emby1.list rules/Domain/emby2.list rules/Domain/merged_emby.list

