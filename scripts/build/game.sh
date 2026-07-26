#!/usr/bin/env bash
set -euo pipefail
echo "=== Building game ==="

work_dir=$(mktemp -d)
source_dir="$work_dir/source"
build_dir="$work_dir/build"
trap 'rm -rf -- "$work_dir"' EXIT

git clone --depth=1 --filter=blob:none --sparse \
  https://github.com/FQrabbit/SSTap-Rule.git "$source_dir"
git -C "$source_dir" sparse-checkout set rules
mkdir -p "$build_dir"

# Only preserve syntactically valid CIDRs. The old code guessed how malformed
# addresses should look and also rewrote valid /24 and /32 networks.
node - "$source_dir/rules" "$build_dir" <<'EOF'
const fs = require('fs');
const net = require('net');
const path = require('path');

const [sourceDir, buildDir] = process.argv.slice(2);
const MIN_IPV4_PREFIX = 16;
const invalidSamples = [];
const broadSamples = [];
let invalidCount = 0;
let privateCount = 0;
let broadCount = 0;
let repairedCount = 0;

function walk(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(fullPath) : [fullPath];
  });
}

function isPrivateIPv4(address) {
  const octets = address.split('.').map(Number);
  return octets[0] === 10 ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168) ||
    (octets[0] === 169 && octets[1] === 254) ||
    octets[0] >= 224;
}

function parseCidr(line) {
  const match = line.match(/^([^/]+)\/(\d{1,3})$/);
  if (!match) return null;

  const address = match[1];
  const prefix = Number(match[2]);
  const version = net.isIP(address);
  if (!version || prefix > (version === 4 ? 32 : 128)) return null;

  return {address, cidr: `${address}/${prefix}`, prefix, version};
}

function repairKnownUpstreamError(file, line) {
  let repaired = line;

  // Maplestory-us.rules contains valid CIDRs followed by CSV delimiters.
  if (repaired.endsWith(',')) {
    repaired = repaired.slice(0, -1).trim();
  }

  // Commit 50a046e6 accidentally removed the dot before the final zero from
  // 72 /24 networks in this file. Its parent commit provides an exact mapping.
  if (path.basename(file) === 'Call-Of-Duty-4-Modern-Warfare.rules') {
    const match = repaired.match(/^(\d+\.\d+\.)(\d+)0\/24$/);
    if (match) repaired = `${match[1]}${Number(match[2])}.0/24`;
  }

  // This source has one otherwise valid IPv4 address with an extra trailing dot.
  if (path.basename(file) === 'Microsoft-Srote.rules') {
    repaired = repaired.replace(/\.(\/\d+)$/, '$1');
  }

  // KuGou-cn has a duplicated leading "61." before a network that already
  // exists in the same source file. Repairing it is safe; Set removes it.
  if (
    path.basename(file) === 'KuGou-cn.rules' &&
    repaired === '61.61.164.210.0/24'
  ) {
    repaired = '61.164.210.0/24';
  }

  if (repaired !== line) repairedCount++;
  return repaired;
}

const outputNames = new Set();
const files = walk(sourceDir).filter((file) => file.endsWith('.rules')).sort();
if (files.length === 0) {
  throw new Error(`No .rules files found in ${sourceDir}`);
}

for (const file of files) {
  const outputName = `${path.basename(file, '.rules')}.yaml`;
  if (outputNames.has(outputName)) {
    throw new Error(`Duplicate output name: ${outputName}`);
  }
  outputNames.add(outputName);

  const payload = new Set();
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const input = rawLine.trim();
    if (!input || input.startsWith('#')) continue;
    const line = repairKnownUpstreamError(file, input);

    const parsed = parseCidr(line);
    if (!parsed) {
      invalidCount++;
      if (invalidSamples.length < 20) invalidSamples.push(`${file}: ${line}`);
      continue;
    }
    if (parsed.version === 4 && isPrivateIPv4(parsed.address)) {
      privateCount++;
      continue;
    }
    // SSTap's own authoring guide discourages prefixes below /16. Those
    // ranges are too broad to identify one game reliably and include known
    // crawler mistakes such as 3.0.0.0/4.
    if (parsed.version === 4 && parsed.prefix < MIN_IPV4_PREFIX) {
      broadCount++;
      if (broadSamples.length < 20) broadSamples.push(`${file}: ${line}`);
      continue;
    }
    payload.add(parsed.cidr);
  }

  const yaml = ['payload:', ...[...payload].map((cidr) => `  - '${cidr}'`), ''].join('\n');
  fs.writeFileSync(path.join(buildDir, outputName), yaml);
}

for (const sample of invalidSamples) {
  console.error(`Skipping malformed CIDR: ${sample}`);
}
for (const sample of broadSamples) {
  console.error(`Skipping unsafe broad game CIDR: ${sample}`);
}
console.log(
  `Generated ${files.length} YAML files; repaired ${repairedCount} known ` +
  `upstream formatting errors; skipped ${invalidCount} malformed and ` +
  `${privateCount} private/reserved IPv4 entries; filtered ${broadCount} ` +
  `IPv4 entries broader than /${MIN_IPV4_PREFIX}.`
);
EOF

# Compile from the YAML generated in this run, so YAML and MRS cannot come from
# different snapshots.
for yaml_file in "$build_dir"/*.yaml; do
  output="${yaml_file%.yaml}.mrs"
  echo "Converting $(basename "$yaml_file")"
  if ! conversion_output=$(
    mihomo convert-ruleset ipcidr yaml "$yaml_file" "$output" 2>&1
  ); then
    printf '%s\n' "$conversion_output" >&2
    exit 1
  fi
  if [[ -n "$conversion_output" ]]; then
    printf 'mihomo rejected entries in %s:\n%s\n' \
      "$yaml_file" "$conversion_output" >&2
    exit 1
  fi
done

# Publish only after every conversion succeeds. Remove stale source and generated
# files owned by this builder, including names left URL-encoded by the old script.
mkdir -p rules/Game
find rules/Game -maxdepth 1 -type f \
  \( -name '*.rules' -o -name '*.yaml' -o -name '*.mrs' \) -delete
cp -a "$build_dir"/. rules/Game/
