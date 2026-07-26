#!/usr/bin/env bash
set -euo pipefail
echo "=== Building emby-ip ==="

# The former upstream was removed and this repository's source file was deleted
# by the builder itself. Keep compiling the last tracked, reviewable payload
# instead of turning an HTTP 404 body into a ruleset.
source_file="rules/IP/emby-ip.yaml"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Emby IP payload: $source_file" >&2
  exit 1
fi

mihomo convert-ruleset ipcidr yaml "$source_file" rules/IP/emby-ip.mrs
