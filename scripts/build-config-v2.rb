#!/usr/bin/env ruby
# frozen_string_literal: true

# 新版只展开 CF 通用政策和 Telegram 顶层政策，不读取或改写旧配置。
require 'json'
require 'optparse'
require 'yaml'

ROOT = File.expand_path('..', __dir__)
OUTPUTS = {'three-airports' => 'configfull_v2.yaml', 'four-airports' => 'configfull_v2_4.yaml'}.freeze

def admission(include_pattern, exclude_pattern)
  include_pattern = include_pattern.delete_prefix('(?i)')
  exclude_pattern = exclude_pattern.delete_prefix('(?i)')
  "(?i)^(?![\\s\\S]*(?:#{exclude_pattern}))(?=[\\s\\S]*(?:#{include_pattern}))[\\s\\S]*$"
end

def generate(settings, policy, routing, model_name)
  model = policy.fetch('models').fetch(model_name)
  airports = model.fetch('active-airports').to_h { |n| [n, policy.fetch('airports').fetch(n)] }
  priorities = model.fetch('priority-order')
  regions = policy.fetch('regions')
  automatic_regions = regions.except('台湾')
  probes = policy.fetch('probes')
  reserve = policy.fetch('reserve-airport')
  reserve_data = airports.fetch(reserve)
  special = policy.fetch('admission').fetch('special')
  providers = airports.values.map { |a| a.fetch('provider') }
  pool_name = ->(airport, region, probe) { "#{airport}-#{region}#{probe == 'TG' ? '-TG' : ''}" }
  pool_filter = lambda do |airport, region|
    data = airports.fetch(airport)
    exclude = data.fetch('exclude-overrides', {}).fetch(region, policy['admission'].fetch('standard-exclude'))
    exclusions = [exclude.delete_prefix('(?i)'), special, data.fetch('region-excludes', {})[region]].compact
    admission(regions.fetch(region).fetch('match'), exclusions.join('|'))
  end
  automatic = lambda do |name, type, probe|
    {'name' => name, 'type' => type}.merge(policy.fetch('automatic-defaults'),
      policy.fetch("#{type}-defaults"), probes.fetch(probe))
  end
  flat_order = lambda do |order, probe|
    order.flat_map do |airport|
      airports.fetch(airport).fetch('region-order').map { |region| pool_name.call(airport, region, probe) }
    end + [pool_name.call(reserve, '备用', probe)]
  end
  independent = policy.fetch('independent-pools').select do |_name, target|
    policy.fetch('airports').fetch(target.fetch('airport'))
    airports.key?(target.fetch('airport'))
  end
  fixed_regions = automatic_regions.keys.flat_map { |region| priorities.keys.map { |n| "#{region}-#{n}" } }
  menu = priorities.keys + fixed_regions + policy.fetch('manual-menu')

  groups = policy.fetch('businesses').map do |name, business|
    if business['region']
      next {'name' => name, 'type' => 'select', 'use' => business.fetch('use') & providers,
            'filter' => admission(regions.fetch(business.fetch('region')).fetch('match'), special),
            'empty-fallback' => 'REJECT', 'icon' => business.fetch('icon')}
    end
    default = model_name == 'four-airports' ? business.fetch('four-default', business.fetch('default')) : business.fetch('default')
    choices = menu.dup
    choices = choices.map { |n| priorities.key?(n) ? "#{n}-TG" : n } if name == 'Telegram代理'
    choices.delete('DIRECT') if name == 'DNS代理'
    choices = independent.keys + choices if business['independent']
    choices += business.fetch('extra', [])
    abort "#{name}: default #{default} is outside its menu" unless choices.include?(default)
    {'name' => name, 'type' => 'select', 'proxies' => [default] + choices.reject { |n| n == default },
     'empty-fallback' => 'REJECT', 'icon' => business.fetch('icon')}
  end
  policy.fetch('helpers').each do |name, fields|
    group = {'name' => name, 'type' => 'select', 'use' => providers, 'empty-fallback' => 'REJECT'}.merge(fields)
    group['filter'] = admission(group.fetch('filter'), special) if name == '自建/家宽节点'
    if name == '低倍率/MITM节点'
      pattern = group.delete('filter-regions').map { |r| regions.fetch(r).fetch('match').delete_prefix('(?i)') }.join('|')
      tags = group.delete('filter-tags')
      group['filter'] = "(?i)(?:(?:#{pattern}).*(?:#{tags})|(?:#{tags}).*(?:#{pattern}))"
      group.merge!(probes.fetch('CF'))
    end
    groups << group
  end

  %w[CF TG].each do |probe|
    airports.each do |airport, data|
      next if airport == reserve
      # CF 支持全部固定地区菜单；TG 只需要机场菜单实际使用的地区。
      pool_regions = probe == 'CF' ? automatic_regions.keys : data.fetch('region-order')
      pool_regions.each do |region|
        groups << automatic.call(pool_name.call(airport, region, probe), 'url-test', probe).merge(
          'use' => [data.fetch('provider')], 'filter' => pool_filter.call(airport, region),
          'icon' => regions.fetch(region).fetch('icon'))
      end
    end
    groups << automatic.call(pool_name.call(reserve, '备用', probe), 'fallback', probe).merge(
      'use' => [reserve_data.fetch('provider')],
      'filter' => reserve_data.fetch('region-order').map do |region|
        pattern = regions.key?(region) ? regions[region].fetch('match') : reserve_data.fetch('extra-match').fetch(region)
        admission(pattern, special)
      end.join('`'))
    priorities.each do |name, order|
      groups << {'name' => probe == 'CF' ? name : "#{name}-TG", 'type' => 'select',
                 'hidden' => false, 'empty-fallback' => 'REJECT', 'proxies' => flat_order.call(order, probe)}
      next if probe == 'TG'
      automatic_regions.each do |region, details|
        groups << automatic.call("#{region}-#{name}", 'fallback', 'CF').merge(
          'proxies' => order.map { |a| pool_name.call(a, region, 'CF') },
          'use' => [reserve_data.fetch('provider')],
          'filter' => admission(details.fetch('match'), special), 'icon' => details.fetch('icon'))
      end
    end
  end
  independent.each do |name, target|
    airport, region = target.values_at('airport', 'region')
    fields = target.slice('icon').merge('use' => [airports.fetch(airport).fetch('provider')])
    if target['home-pool']
      home_filter = admission(policy.fetch('helpers').fetch('自建/家宽节点').fetch('filter'), special)
      region_match = regions.fetch(region).fetch('match').delete_prefix('(?i)')
      groups << automatic.call(target['home-pool'], 'url-test', 'CF').merge(fields,
        'filter' => home_filter.sub('^', "^(?=[\\s\\S]*(?:#{region_match}))"))
    end
    group = automatic.call(name, target['home-pool'] ? 'fallback' : 'url-test', 'CF').merge(fields,
      'hidden' => false, 'filter' => pool_filter.call(airport, region))
    group['proxies'] = [target['home-pool']] if target['home-pool']
    groups << group
  end
  groups << automatic.call('规则更新', 'fallback', 'CF').merge(
    'proxies' => flat_order.call(priorities.fetch(policy.fetch('rule-update-policy')), 'CF') + ['DIRECT'])

  groups.each do |group|
    next unless group.key?('use')
    next if independent.key?(group['name']) || independent.values.any? { |target| group['name'] == target['home-pool'] }
    next if ['自建/家宽节点', '全部节点'].include?(group['name'])
    group['exclude-filter'] = policy.fetch('admission').fetch('default-exclude')
  end

  config = settings.dup
  defaults = policy.fetch('provider-defaults')
  config['proxy-providers'] = airports.to_h do |_name, airport|
    [airport.fetch('provider'), defaults.merge(airport.slice('url', 'override'),
      'health-check' => defaults.fetch('health-check').merge(probes.fetch('CF')))]
  end
  config['proxies'] = []
  config['proxy-groups'] = groups
  # 子规则返回首个业务；UDP 出口不支持时，外层直接拒绝，避免穿透后续业务。
  config['rules'] = ['SUB-RULE,(OR,((NETWORK,tcp),(NETWORK,udp))),分流-业务规则', 'MATCH,REJECT']
  config['sub-rules'] = {'分流-业务规则' => routing.fetch('rules')}
  config['rule-providers'] = routing.fetch('rule-providers').transform_values do |provider|
    provider['type'] == 'inline' ? provider : routing.fetch('rule-provider-defaults').merge(provider)
  end
  config
end

def emit(config)
  # 输出原生 YAML，不让客户端依赖别名；菜单行内展示，保持候选顺序。
  tree = YAML.parse_stream(YAML.dump(JSON.parse(JSON.generate(config)), line_width: -1))
  groups = tree.children.first.root.children.each_slice(2).find { |key, _| key.value == 'proxy-groups' }.last
  groups.children.each do |group|
    group.children.each_slice(2) do |key, value|
      next unless %w[proxies use].include?(key.value)
      value.style = Psych::Nodes::Sequence::FLOW
      value.children.each { |name| name.quoted = true }
    end
  end
  "# Generated by scripts/build-config-v2.rb; edit config-source/v2/{settings,policy,routing}.yaml.\n" + tree.yaml(nil, line_width: -1)
end

check = false
OptionParser.new do |options|
  options.banner = 'Usage: ruby scripts/build-config-v2.rb [--check]'
  options.on('--check', 'Check both v2 outputs without writing') { check = true }
end.parse!
abort "Unexpected arguments: #{ARGV.join(' ')}" unless ARGV.empty?
settings, policy, routing = %w[settings policy routing].map do |name|
  YAML.safe_load_file(File.join(ROOT, "config-source/v2/#{name}.yaml"), aliases: name == 'settings')
end
outputs = OUTPUTS.to_h do |model, filename|
  config = generate(settings, policy, routing, model)
  [filename, [emit(config), config.fetch('proxy-groups').length]]
end
# 先生成全部模型，配置错误时不留下只更新了一份的产物。
outputs.each do |filename, (output, count)|
  path = File.join(ROOT, filename)
  if check
    abort "#{filename} is stale: run ruby scripts/build-config-v2.rb" unless File.file?(path) && File.binread(path) == output.b
    puts "#{filename} is current."
  else
    File.write(path, output)
    puts "Generated #{filename} (#{count} groups)."
  end
end
