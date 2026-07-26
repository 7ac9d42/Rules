#!/usr/bin/env bash
set -euo pipefail
echo "=== Building ai ==="

# Fetch AI Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 AI 规则文件
curl -sL "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/Domain/ai.yaml" -o rules/Domain/ai.yaml

# Convert AI Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/ai.yaml rules/Domain/ai.mrs

