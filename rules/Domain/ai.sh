#!/usr/bin/env bash
set -euo pipefail
echo "=== Building ai ==="

# Smart skip check: if git status shows no modification on source files and output exists
if [ -f "rules/Domain/ai.mrs" ] && git diff --quiet HEAD -- "rules/Domain/" 2>/dev/null; then
  echo "Sources for ai unchanged, skipping build."
  exit 0
fi

# Fetch AI Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 AI 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/ai.yaml" -o rules/Domain/ai.yaml

# Convert AI Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/ai.yaml rules/Domain/ai.mrs

