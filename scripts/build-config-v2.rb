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
  pool_filter = lambda do |airport, region, probe = nil|
    data = airports.fetch(airport)
    exclude = data.fetch('exclude-overrides', {}).fetch(region, policy['admission'].fetch('standard-exclude'))
    exclusions = [exclude.delete_prefix('(?i)'), special, data.fetch('region-excludes', {})[region]].compact
    # 附加健康检查只读取 filter；TG 也排除住宅，避免测到不会入组的节点。
    exclusions << policy['admission'].fetch('default-exclude').delete_prefix('(?i)') if probe == 'TG'
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
  fixed_regions = automatic_regions.keys.flat_map { |region| priorities.keys.map { |n| pool_name.call(n, region, 'CF') } }
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
          'use' => [data.fetch('provider')], 'filter' => pool_filter.call(airport, region, probe),
          'icon' => regions.fetch(region).fetch('icon'))
      end
    end
    # 机场4只供规则更新的 CF 回退链使用，无需注册闲置 TG 探针。
    if probe == 'CF'
      groups << automatic.call(pool_name.call(reserve, '备用', probe), 'fallback', probe).merge(
        'use' => [reserve_data.fetch('provider')], 'icon' => reserve_data.fetch('icon'),
        'filter' => reserve_data.fetch('region-order').map do |region|
          pattern = regions.key?(region) ? regions[region].fetch('match') : reserve_data.fetch('extra-match').fetch(region)
          admission(pattern, special)
        end.join('`'))
    end
    priorities.each_key do |name|
      groups << automatic.call(probe == 'CF' ? name : "#{name}-TG", 'fallback', probe).merge(
        'hidden' => false, 'proxies' => airports.fetch(name).fetch('region-order').map { |r| pool_name.call(name, r, probe) },
        'icon' => airports.fetch(name).fetch(probe == 'TG' ? 'tg-icon' : 'icon'))
    end
  end
  independent.each do |name, target|
    airport, region = target.values_at('airport', 'region')
    fields = target.slice('icon').merge('use' => [airports.fetch(airport).fetch('provider')])
    if target['home-pool']
      home_filter = admission(policy.fetch('helpers').fetch('自建/家宽节点').fetch('filter'), special)
      region_match = regions.fetch(region).fetch('match').delete_prefix('(?i)')
      groups << automatic.call(target['home-pool'], 'url-test', 'CF').merge(fields,
        'icon' => policy.fetch('helpers').fetch('自建/家宽节点').fetch('icon'),
        'filter' => home_filter.sub('^', "^(?=[\\s\\S]*(?:#{region_match}))"))
    end
    group = automatic.call(name, target['home-pool'] ? 'fallback' : 'url-test', 'CF').merge(fields,
      'hidden' => false, 'filter' => pool_filter.call(airport, region))
    group['proxies'] = [target['home-pool']] if target['home-pool']
    groups << group
  end
  groups << automatic.call('规则更新', 'fallback', 'CF').merge(
    'proxies' => flat_order.call(priorities.fetch(policy.fetch('rule-update-policy')), 'CF') + ['DIRECT'],
    'icon' => policy.fetch('rule-update-icon'))

  groups.each do |group|
    next unless group.key?('use')
    next if independent.key?(group['name']) || independent.values.any? { |target| group['name'] == target['home-pool'] }
    next if ['自建/家宽节点', '全部节点'].include?(group['name'])
    group['exclude-filter'] = policy.fetch('admission').fetch('default-exclude')
  end

  # 仅排序组定义；组内候选及业务规则顺序保持不变。
  display_ranks = (policy.fetch('businesses').keys + policy.fetch('display-order')).each_with_index.to_h
  groups = groups.each_with_index.sort_by do |group, index|
    level = group['hidden'] ? 2 : (policy.fetch('businesses').key?(group['name']) ? 0 : 1)
    [level, display_ranks.fetch(group['name'], display_ranks.length), index]
  end.map(&:first)

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

def smart_compatible_variant(config)
  rules = config.delete('sub-rules').fetch('分流-业务规则').dup
  wrapped_proxy = 'AND,((RULE-SET,proxy_domain),(NOT,((RULE-SET,google_domain)))),默认代理'
  if (proxy_index = rules.index(wrapped_proxy))
    google_index = rules.index('RULE-SET,google_domain,Google')
    abort 'v3: Google must precede the general proxy rule' unless google_index && google_index < proxy_index
    # Google 已先匹配并受下方护栏保护；去掉包装，使 Smart 能识别通用代理集合。
    rules[proxy_index] = 'RULE-SET,proxy_domain,默认代理'
  end

  # Smart 根据 provider 键名识别分类集合，不读取 URL；单服务（含 OpenAI 补充集）保持原名。
  names = {
    'ai!cn_domain' => 'category-ai-!cn', 'social_media_non_cn_domain' => 'category-social-media-!cn',
    'finance_domain' => 'category-finance', 'cryptocurrency_domain' => 'category-cryptocurrency',
    'communication_domain' => 'category-communication', 'ecommerce_domain' => 'category-ecommerce',
    'proxy_domain' => 'category-proxy', 'dev_download_domain' => 'category-dev-download'
  }
  rename_rule = ->(rule) { rule.gsub(/RULE-SET,([^,()]+)/) { "RULE-SET,#{names.fetch($1, $1)}" } }
  config['rule-providers'] = config.fetch('rule-providers').to_h { |name, provider| [names.fetch(name, name), provider] }
  dns = config.fetch('dns')
  config['dns'] = dns.merge(
    'fake-ip-filter' => dns.fetch('fake-ip-filter').map(&rename_rule),
    'nameserver-policy' => dns.fetch('nameserver-policy').transform_keys do |key|
      key.start_with?('rule-set:') ? 'rule-set:' + key.delete_prefix('rule-set:').split(',').map { |n| names.fetch(n, n) }.join(',') : key
    end)
  groups = config.fetch('proxy-groups').map { |group| group.fetch('name') }
  # Smart 需要顶层实际命中规则；护栏保留 UDP 不支持时拒绝、而非穿透后续业务的行为。
  config['rules'] = rules.map(&rename_rule).flat_map do |rule|
    fields = rule.split(',')
    target = fields.length - 1
    target -= 1 while %w[no-resolve src dst].include?(fields[target])
    next [rule] unless groups.include?(fields[target])

    fields[target] = 'REJECT'
    [rule, fields.join(',')]
  end
  config
end

def emit(config, version = 'v2')
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
  command = "scripts/build-config-v2.rb#{version == 'v3' ? ' --v3' : ''}"
  sources = 'config-source/v2/{settings,policy,routing}.yaml'
  "# Generated by #{command}; edit #{sources}.\n" + tree.yaml(nil, line_width: -1)
end

check = false
version = 'v2'
OptionParser.new do |options|
  options.banner = 'Usage: ruby scripts/build-config-v2.rb [--v3] [--check]'
  options.on('--v3', 'Generate the Smart-compatible variant using the shared v2 sources') { version = 'v3' }
  options.on('--check', 'Check both outputs without writing') { check = true }
end.parse!
abort "Unexpected arguments: #{ARGV.join(' ')}" unless ARGV.empty?
settings, policy, routing = %w[settings policy routing].map do |name|
  YAML.safe_load_file(File.join(ROOT, "config-source/v2/#{name}.yaml"), aliases: name == 'settings')
end
outputs = OUTPUTS.to_h do |model, filename|
  config = generate(settings, policy, routing, model)
  config = smart_compatible_variant(config) if version == 'v3'
  [filename.sub('v2', version), [emit(config, version), config.fetch('proxy-groups').length]]
end
# 先生成全部模型，配置错误时不留下只更新了一份的产物。
outputs.each do |filename, (output, count)|
  path = File.join(ROOT, filename)
  if check
    abort "#{filename} is stale: run ruby scripts/build-config-v2.rb#{version == 'v3' ? ' --v3' : ''}" unless File.file?(path) && File.binread(path) == output.b
    puts "#{filename} is current."
  else
    File.write(path, output)
    puts "Generated #{filename} (#{count} groups)."
  end
end
