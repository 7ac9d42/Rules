#!/usr/bin/env ruby
# frozen_string_literal: true

# Generates the two importable configs from maintained sources; never writes backups.
require 'json'
require 'optparse'
require 'yaml'

root = File.expand_path('..', __dir__)
check = false
OptionParser.new do |options|
  options.banner = 'Usage: ruby scripts/build-config.rb [--check]'
  options.on('--check', 'Fail if either generated config is stale; do not write') { check = true }
end.parse!
abort "Unexpected arguments: #{ARGV.join(' ')}" unless ARGV.empty?
common = YAML.safe_load_file(File.join(root, 'config-source/common.yaml'), aliases: false)
models = {'three-airports' => 'configfull_new.yaml', 'four-airports' => 'configfull_new_4.yaml'}

# A positive filter limits provider nodes without filtering explicit helper names.
# Extra provider health checks also receive this complete predicate (not exclude-filter).
def admission(include_pattern, exclude_pattern)
  include_pattern = include_pattern.delete_prefix('(?i)')
  exclude_pattern = exclude_pattern.delete_prefix('(?i)')
  "(?i)^(?![\\s\\S]*(?:#{exclude_pattern}))(?=[\\s\\S]*(?:#{include_pattern}))[\\s\\S]*$"
end

def generate(s)
  airports = s.fetch('active-airports').to_h { |name| [name, s.fetch('airports').fetch(name)] }
  regions = s.fetch('regions')
  probes = s.fetch('probes').transform_values(&:dup)
  # TG only follows the model's top-level priority policies, never fixed-region policies.
  probes.fetch('TG')['policies'] = s.fetch('priority-order').keys
  special = s.fetch('admission').fetch('special')
  ordinary = admission('.*', special)
  providers = airports.values.map { |a| a.fetch('provider') }
  reserve = s.fetch('reserve').fetch('airport')
  pool_name = ->(airport, region, probe) { "#{airport}-#{region}-#{probe}" }
  pool_filter = lambda do |airport, region|
    include_pattern = regions.fetch(region).fetch('match')
    exclude_pattern = s['admission']['exclude-overrides'].dig(airport, region) || s['admission'].fetch('standard-exclude')
    exclusions = [exclude_pattern.delete_prefix('(?i)'), special, s['admission']['region-excludes'].dig(airport, region)].compact
    admission(include_pattern, exclusions.join('|'))
  end
  automatic = lambda do |name, type, probe|
    {'name' => name, 'type' => type}.merge(s.fetch('automatic-defaults'),
      s.fetch("#{type}-defaults"), probes.fetch(probe).slice('url', 'expected-status'))
  end

  policies = s.fetch('priority-order').dup
  policy_regions = {}
  regions.each_key do |region|
    s['priority-order'].each do |name, order|
      policy = "#{region}-#{name}"
      policies[policy] = order
      policy_regions[policy] = region
    end
  end
  probe_policies = probes.to_h do |probe, fields|
    names = fields.fetch('policies', policies.keys)
    names.each { |name| policies.fetch(name) }
    [probe, names]
  end
  flat_order = lambda do |order, probe|
    order.flat_map do |airport|
      s.fetch('airport-region-order').fetch(airport).map { |region| pool_name.call(airport, region, probe) }
    end + ["#{reserve}-备用-#{probe}"]
  end

  groups = []
  sensitive = s.fetch('sensitive-targets')
  private_targets = sensitive.values.uniq
  private_pair = lambda do |target|
    s.fetch('sensitive-probes').map { |probe| '专用-' + pool_name.call(target.fetch('airport'), target.fetch('region'), probe) }
  end
  private_names = private_targets.flat_map { |target| private_pair.call(target) }
  menu = policies.keys + s.fetch('manual-menu')
  businesses = s.fetch('businesses').transform_values(&:dup)
  s.fetch('business-defaults').each { |name, default| businesses.fetch(name)['default'] = default }
  businesses.each do |name, business|
    choices = menu + business.fetch('extra', [])
    if sensitive.key?(name)
      own_pair = private_pair.call(sensitive.fetch(name))
      choices = own_pair + (private_names - own_pair) + choices
    end
    choices = choices.map { |n| policies.key?(n) ? "#{n}-Google" : n } if name == 'GLOBAL'
    default = business.fetch('default')
    abort "#{name}: default #{default} is outside its menu" unless choices.include?(default)
    choices = [default] + choices.reject { |n| n == default }
    groups << {'name' => name, 'type' => 'select', 'proxies' => choices, 'use' => providers,
               'filter' => ordinary, 'empty-fallback' => 'REJECT', 'icon' => business.fetch('icon')}
  end
  s.fetch('helpers').each do |name, fields|
    group = {'name' => name, 'type' => 'select', 'use' => providers, 'empty-fallback' => 'REJECT'}.merge(fields)
    group['filter'] = admission(group.fetch('filter'), special) if name == '自建/家宽节点'
    if name == '低倍率/MITM节点'
      region_pattern = group.delete('filter-regions').map do |region|
        regions.fetch(region).fetch('match').delete_prefix('(?i)')
      end.join('|')
      tags = group.fetch('filter-tags')
      group.delete('filter-tags')
      group['filter'] = "(?i)(?:(?:#{region_pattern}).*(?:#{tags})|(?:#{tags}).*(?:#{region_pattern}))"
    end
    groups << group
  end
  probes.each_key do |probe|
    active = probe_policies.fetch(probe)
    required_pools = active.flat_map do |policy|
      policies.fetch(policy).flat_map do |airport|
        needed_regions = policy_regions.key?(policy) ? [policy_regions.fetch(policy)] : s['airport-region-order'].fetch(airport)
        needed_regions.map { |region| [airport, region] }
      end
    end.uniq
    s['airport-region-order'].each_key do |airport|
      next unless airports.key?(airport)
      regions.each do |region, details|
        next unless required_pools.include?([airport, region])
        groups << automatic.call(pool_name.call(airport, region, probe), 'url-test', probe).merge(
          'use' => [airports.fetch(airport).fetch('provider')], 'filter' => pool_filter.call(airport, region),
          'icon' => details.fetch('icon'))
      end
    end
    # Backtick-separated filters preserve reserve region ordering and deduplicate nodes.
    groups << automatic.call("#{reserve}-备用-#{probe}", 'fallback', probe).merge(
      'use' => [airports.fetch(reserve).fetch('provider')],
      'filter' => s['reserve']['region-order'].map do |region|
        pattern = regions.key?(region) ? regions[region].fetch('match') : s['reserve']['extra-match'].fetch(region)
        admission(pattern, special)
      end.join('`'))
    s['priority-order'].each do |policy, order|
      if active.include?(policy)
        groups << automatic.call("#{policy}-#{probe}", 'fallback', probe).merge('proxies' => flat_order.call(order, probe))
      end
      regions.each do |region, details|
        next unless active.include?("#{region}-#{policy}")
        groups << automatic.call("#{region}-#{policy}-#{probe}", 'fallback', probe).merge(
          'proxies' => order.map { |a| pool_name.call(a, region, probe) },
          'use' => [airports.fetch(reserve).fetch('provider')],
          'filter' => admission(details.fetch('match'), special), 'icon' => details.fetch('icon'))
      end
    end
  end
  private_targets.each do |target|
    airport, region = target.values_at('airport', 'region')
    s.fetch('sensitive-probes').zip(private_pair.call(target)).each do |probe, name|
      groups << automatic.call(name, 'url-test', probe).merge(
        'use' => [airports.fetch(airport).fetch('provider')], 'filter' => pool_filter.call(airport, region))
    end
  end
  groups << automatic.call('规则更新', 'fallback', 'GitHub').merge(
    'proxies' => flat_order.call(s['priority-order'].fetch(s.fetch('rule-update-policy')), 'GitHub') + ['DIRECT'])

  config = s.fetch('settings').dup
  config['proxy-providers'] = airports.to_h do |_name, airport|
    [airport.fetch('provider'), s.fetch('provider-defaults').merge(airport.slice('url', 'override'))]
  end
  config['proxies'] = [{'name' => '分流-业务入口', 'type' => 'rematch', 'target-sub-rule' => '分流-业务规则'}]
  policies.each_key do |name|
    config['proxies'] << {'name' => name, 'type' => 'rematch', 'target-rematch-name' => name, 'target-sub-rule' => '分流-探针分类'}
  end
  config['proxy-groups'] = groups
  config['rules'] = s.fetch('rules')
  classification = s.fetch('classification').flat_map do |branch|
    match, probe = branch.values_at('match', 'probe')
    if probes.fetch(probe).key?('policies')
      scope = probe_policies.fetch(probe).map { |name| "(REMATCH-NAME,#{name})" }.join(',')
      match = "AND,((OR,(#{scope})),(#{match}))"
    end
    ["SUB-RULE,(#{match}),分流-#{probe}-出口", "AND,((NETWORK,udp),(#{match})),REJECT"]
  end
  config['sub-rules'] = {'分流-业务规则' => s.fetch('business-rules'), '分流-探针分类' => classification + ['MATCH,REJECT']}
  probes.each_key do |probe|
    config['sub-rules']["分流-#{probe}-出口"] = probe_policies.fetch(probe).map { |n| "REMATCH-NAME,#{n},#{n}-#{probe}" } + ['MATCH,REJECT']
  end
  config['rule-providers'] = s.fetch('rule-providers').transform_values do |provider|
    provider['type'] == 'inline' ? provider : s.fetch('rule-provider-defaults').merge(provider)
  end

  # Break shared Ruby object identity before dumping so clients never need YAML aliases.
  yaml_tree = YAML.parse_stream(YAML.dump(JSON.parse(JSON.generate(config)), line_width: -1))
  group_nodes = yaml_tree.children.first.root.children.each_slice(2).find { |key, _| key.value == 'proxy-groups' }.last
  group_nodes.children.each do |group|
    group.children.each_slice(2) do |key, value|
      next unless %w[proxies use].include?(key.value)
      value.style = Psych::Nodes::Sequence::FLOW
      # Let the emitter quote flow-sensitive names without adding explicit YAML tags.
      value.children.each { |name| name.quoted = true }
    end
  end
  [yaml_tree.yaml(nil, line_width: -1), groups.length]
end

# Only these shallow model fields differ; no recursive inheritance or YAML aliases.
outputs = models.to_h do |model, filename|
  variant = YAML.safe_load_file(File.join(root, "config-source/#{model}.yaml"), aliases: false)
  yaml, count = generate(common.merge(variant))
  header = "# Generated by scripts/build-config.rb; edit config-source/common.yaml and config-source/#{model}.yaml.\n"
  [filename, [header + yaml, count]]
end
outputs.each do |filename, (output, count)|
  path = File.join(root, filename)
  if check
    abort "#{filename} is stale: run ruby scripts/build-config.rb" unless File.file?(path) && File.binread(path) == output.b
    puts "#{filename} is current."
  else
    File.write(path, output)
    puts "Generated #{filename} (#{count} groups)."
  end
end
