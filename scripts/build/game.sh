#!/usr/bin/env bash
set -euo pipefail
echo "=== Building game ==="

work_dir=$(mktemp -d)
source_dir="$work_dir/source"
build_dir="$work_dir/build"
publish_dir=""
backup_dir=""
cleanup() {
  rm -rf -- "$work_dir"
  if [[ -n "$publish_dir" && -d "$publish_dir" ]]; then
    rm -rf -- "$publish_dir"
  fi
  if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
    if [[ -e rules/Game ]]; then
      rm -rf -- "$backup_dir"
    else
      mv "$backup_dir" rules/Game
    fi
  fi
}
trap cleanup EXIT

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
const MIN_IPV6_PREFIX = 32;
const EXCLUDED_SOURCES = new Set([
  'BypassCNandLan.rules',
  'BypassCNandLan_someip.rules',
  'China-IP-only.rules',
  'Skip-all-China-IP-mini-and-LAN.rules',
  // The upstream file is labelled WoW-EU but contains World of Warships Asia.
  'WoW-EU.rules',
]);
const invalidSamples = [];
const broadSamples = [];
let invalidCount = 0;
let nonGlobalCount = 0;
let broadCount = 0;
let repairedCount = 0;
let inputCidrCount = 0;
let outputCidrCount = 0;
let aggregateBroadCount = 0;
const aggregateBroadSamples = [];

function walk(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(fullPath) : [fullPath];
  });
}

function parseIPv4(address) {
  const octets = address.split('.').map(Number);
  if (octets.length !== 4 || octets.some((octet) =>
    !Number.isInteger(octet) || octet < 0 || octet > 255
  )) return null;
  return octets.reduce((value, octet) => (value << 8n) | BigInt(octet), 0n);
}

function parseIPv6(address) {
  let normalized = address.toLowerCase();
  if (normalized.includes('.')) {
    const lastColon = normalized.lastIndexOf(':');
    if (lastColon < 0) return null;
    const ipv4 = parseIPv4(normalized.slice(lastColon + 1));
    if (ipv4 === null) return null;
    normalized = `${normalized.slice(0, lastColon + 1)}` +
      `${(ipv4 >> 16n).toString(16)}:${(ipv4 & 0xffffn).toString(16)}`;
  }

  const halves = normalized.split('::');
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(':') : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  const missing = 8 - left.length - right.length;
  if ((halves.length === 1 && missing !== 0) ||
      (halves.length === 2 && missing < 1)) return null;

  const groups = [...left, ...Array(missing).fill('0'), ...right];
  if (groups.length !== 8 || groups.some((group) =>
    !/^[0-9a-f]{1,4}$/.test(group)
  )) return null;
  return groups.reduce((value, group) =>
    (value << 16n) | BigInt(`0x${group}`), 0n
  );
}

function prefixMask(bits, prefix) {
  if (prefix === 0) return 0n;
  return ((1n << BigInt(prefix)) - 1n) << BigInt(bits - prefix);
}

function parseCidr(line) {
  const match = line.match(/^([^/]+)\/(\d{1,3})$/);
  if (!match) return null;

  const address = match[1];
  const prefix = Number(match[2]);
  const version = net.isIP(address);
  if (!version || prefix > (version === 4 ? 32 : 128)) return null;

  const bits = version === 4 ? 32 : 128;
  const value = version === 4 ? parseIPv4(address) : parseIPv6(address);
  if (value === null) return null;
  return {network: value & prefixMask(bits, prefix), prefix, version, bits};
}

function formatIPv4(value) {
  return [24n, 16n, 8n, 0n]
    .map((shift) => Number((value >> shift) & 0xffn))
    .join('.');
}

function formatIPv6(value) {
  const groups = [];
  for (let shift = 112n; shift >= 0n; shift -= 16n) {
    groups.push(((value >> shift) & 0xffffn).toString(16));
  }

  let bestStart = -1;
  let bestLength = 0;
  for (let start = 0; start < groups.length;) {
    if (groups[start] !== '0') {
      start++;
      continue;
    }
    let end = start;
    while (end < groups.length && groups[end] === '0') end++;
    if (end - start > bestLength) {
      bestStart = start;
      bestLength = end - start;
    }
    start = end;
  }

  if (bestLength < 2) return groups.join(':');
  const left = groups.slice(0, bestStart).join(':');
  const right = groups.slice(bestStart + bestLength).join(':');
  return `${left}::${right}`;
}

function formatCidr(cidr) {
  const address = cidr.version === 4
    ? formatIPv4(cidr.network)
    : formatIPv6(cidr.network);
  return `${address}/${cidr.prefix}`;
}

function overlaps(network, prefix, range) {
  const commonPrefix = Math.min(prefix, range.prefix);
  const mask = prefixMask(range.bits, commonPrefix);
  return (network & mask) === (range.network & mask);
}

const RESERVED_IPV4 = [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10],
  ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12],
  ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.168.0.0', 16],
  ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
  ['224.0.0.0', 4], ['240.0.0.0', 4],
].map(([address, prefix]) => ({
  network: parseIPv4(address) & prefixMask(32, prefix), prefix, bits: 32,
}));

const RESERVED_IPV6 = [
  ['::', 128], ['::1', 128], ['fc00::', 7], ['fe80::', 10],
  ['ff00::', 8], ['2001:db8::', 32],
].map(([address, prefix]) => ({
  network: parseIPv6(address) & prefixMask(128, prefix), prefix, bits: 128,
}));

function isNonGlobal(cidr) {
  const reserved = cidr.version === 4 ? RESERVED_IPV4 : RESERVED_IPV6;
  return reserved.some((range) => overlaps(cidr.network, cidr.prefix, range));
}

// Remove covered CIDRs and merge complete sibling blocks. This is exact set
// union within one game only; it never combines traffic from different games.
function compactCidrs(cidrs, version, minPrefix) {
  const bits = version === 4 ? 32 : 128;
  const byPrefix = Array.from({length: bits + 1}, () => new Set());
  const sorted = cidrs
    .filter((cidr) => cidr.version === version)
    .sort((a, b) => a.prefix - b.prefix ||
      (a.network < b.network ? -1 : a.network > b.network ? 1 : 0));

  for (const cidr of sorted) {
    let covered = false;
    for (let prefix = 0; prefix < cidr.prefix; prefix++) {
      const parent = cidr.network & prefixMask(bits, prefix);
      if (byPrefix[prefix].has(parent)) {
        covered = true;
        break;
      }
    }
    if (!covered) byPrefix[cidr.prefix].add(cidr.network);
  }

  // Never merge back into a block broader than the safety boundary enforced
  // above.  The union stays exact, but publishing (for example) an Akamai /12
  // as one game's range defeats the point of rejecting broad source entries.
  for (let prefix = bits; prefix > minPrefix; prefix--) {
    const blockSize = 1n << BigInt(bits - prefix);
    for (const network of [...byPrefix[prefix]]) {
      if (!byPrefix[prefix].has(network)) continue;
      const sibling = network ^ blockSize;
      if (!byPrefix[prefix].has(sibling)) continue;
      byPrefix[prefix].delete(network);
      byPrefix[prefix].delete(sibling);
      byPrefix[prefix - 1].add(network & prefixMask(bits, prefix - 1));
    }
  }

  return byPrefix.flatMap((networks, prefix) =>
    [...networks].map((network) => ({network, prefix, version, bits}))
  );
}

function removeUnsafeAggregates(cidrs, version, minPrefix, file) {
  const versionCidrs = cidrs.filter((cidr) => cidr.version === version);
  const unsafe = compactCidrs(versionCidrs, version, 0)
    .filter((cidr) => cidr.prefix < minPrefix);
  if (unsafe.length === 0) return versionCidrs;

  aggregateBroadCount += unsafe.length;
  for (const cidr of unsafe) {
    if (aggregateBroadSamples.length >= 20) break;
    aggregateBroadSamples.push(`${file}: ${formatCidr(cidr)}`);
  }

  // A source can disguise a shared provider supernet as a complete set of
  // narrower siblings. Drop that whole aggregate instead of merely printing
  // the same unsafe coverage as many /16 or /32 entries.
  return versionCidrs.filter((cidr) => !unsafe.some((range) =>
    (cidr.network & prefixMask(cidr.bits, range.prefix)) === range.network
  ));
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
const allFiles = walk(sourceDir).filter((file) => file.endsWith('.rules')).sort();
const files = allFiles.filter((file) => !EXCLUDED_SOURCES.has(path.basename(file)));
if (files.length === 0) {
  throw new Error(`No .rules files found in ${sourceDir}`);
}

for (const file of files) {
  const outputName = `${path.basename(file, '.rules')}.yaml`;
  if (outputNames.has(outputName)) {
    throw new Error(`Duplicate output name: ${outputName}`);
  }
  outputNames.add(outputName);

  const payload = [];
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
    inputCidrCount++;
    if (isNonGlobal(parsed)) {
      nonGlobalCount++;
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
    if (parsed.version === 6 && parsed.prefix < MIN_IPV6_PREFIX) {
      broadCount++;
      if (broadSamples.length < 20) broadSamples.push(`${file}: ${line}`);
      continue;
    }
    payload.push(parsed);
  }

  const safePayload = [
    ...removeUnsafeAggregates(payload, 4, MIN_IPV4_PREFIX, file),
    ...removeUnsafeAggregates(payload, 6, MIN_IPV6_PREFIX, file),
  ];
  const compacted = [
    ...compactCidrs(safePayload, 4, MIN_IPV4_PREFIX),
    ...compactCidrs(safePayload, 6, MIN_IPV6_PREFIX),
  ].sort((a, b) =>
    a.version - b.version ||
    (a.network < b.network ? -1 : a.network > b.network ? 1 : a.prefix - b.prefix)
  );
  if (compacted.length === 0) {
    throw new Error(`No usable game CIDRs remain in ${file}`);
  }
  outputCidrCount += compacted.length;
  const yaml = [
    'payload:',
    ...compacted.map((cidr) => `  - '${formatCidr(cidr)}'`),
    '',
  ].join('\n');
  fs.writeFileSync(path.join(buildDir, outputName), yaml);
}

for (const sample of invalidSamples) {
  console.error(`Skipping malformed CIDR: ${sample}`);
}
for (const sample of broadSamples) {
  console.error(`Skipping unsafe broad game CIDR: ${sample}`);
}
for (const sample of aggregateBroadSamples) {
  console.error(`Skipping disguised broad game aggregate: ${sample}`);
}
if (invalidCount > 0) {
  throw new Error(
    `Found ${invalidCount} unrecognized malformed CIDRs; add only reviewed, exact repairs.`
  );
}
console.log(
  `Generated ${files.length} YAML files; excluded ` +
  `${allFiles.length - files.length} misclassified sources; repaired ` +
  `${repairedCount} reviewed upstream errors; skipped ${nonGlobalCount} ` +
  `non-global entries, ${broadCount} unsafe broad entries and ` +
  `${aggregateBroadCount} disguised broad aggregates; compacted ` +
  `${inputCidrCount} parsed inputs to ${outputCidrCount} exact CIDRs.`
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

# Publish only after every conversion succeeds. Stage beside the destination so
# an interrupted local build can restore the complete previous snapshot.
mkdir -p rules
publish_dir=$(mktemp -d rules/.Game.publish.XXXXXX)
cp -a "$build_dir"/. "$publish_dir"/
backup_dir="rules/.Game.backup.$$"
if [[ -e "$backup_dir" ]]; then
  echo "Refusing to overwrite stale game backup: $backup_dir" >&2
  exit 1
fi
if [[ -d rules/Game ]]; then
  mv rules/Game "$backup_dir"
fi
if ! mv "$publish_dir" rules/Game; then
  echo "Failed to publish game snapshot" >&2
  exit 1
fi
publish_dir=""
if [[ -d "$backup_dir" ]]; then
  rm -rf -- "$backup_dir"
fi
backup_dir=""
