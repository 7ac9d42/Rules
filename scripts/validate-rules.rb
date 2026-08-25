#!/usr/bin/env ruby
# frozen_string_literal: true

require "ipaddr"
require "open3"
require "set"
require "tmpdir"
require "yaml"

ROOT = File.expand_path("..", __dir__)
MIHOMO_BIN = ENV.fetch("MIHOMO_BIN", "mihomo")
errors = []

def duplicate_mapping_keys(path)
  # Inspect the source AST: merged anchors stay aliases, so a valid explicit override is not a duplicate.
  document = Psych.parse_file(path)
  duplicates = []

  walk = lambda do |node, location|
    case node
    when Psych::Nodes::Mapping
      seen = {}
      node.children.each_slice(2) do |key_node, value_node|
        if key_node.is_a?(Psych::Nodes::Scalar)
          key = key_node.value
          key_location = key_node.start_line + 1
          if seen.key?(key)
            duplicates << "#{location}: duplicate mapping key #{key.inspect} " \
                          "at lines #{seen[key]} and #{key_location}"
          else
            seen[key] = key_location
          end
          child_location = "#{location}.#{key}"
        else
          child_location = "#{location}.<complex-key>"
        end
        walk.call(value_node, child_location)
      end
    when Psych::Nodes::Sequence
      node.children.each_with_index { |child, index| walk.call(child, "#{location}[#{index}]") }
    end
  end

  walk.call(document.root, "$")
  duplicates
end

def add_duplicate_value_errors(errors, label, values)
  duplicates = values.tally.select { |_value, count| count > 1 }.keys
  errors << "#{label}: duplicate entries: #{duplicates.first(3).join(', ')}" unless duplicates.empty?
end

def add_single_final_match_error(errors, label, rules)
  match_indexes = rules.each_index.select do |index|
    rules[index].split(",", 2).first.strip.upcase == "MATCH"
  end
  unless match_indexes.length == 1
    errors << "#{label}: must contain exactly one MATCH rule (found #{match_indexes.length})"
    return
  end

  errors << "#{label}: MATCH must be the final rule" unless match_indexes.first == rules.length - 1
end

def add_regex_sample_errors(errors, label, source, required:, forbidden:)
  pattern = Regexp.new(source)
  required.each { |value| errors << "config: #{label} misses #{value}" unless pattern.match?(value) }
  forbidden.each { |value| errors << "config: #{label} overmatches #{value}" if pattern.match?(value) }
rescue RegexpError => e
  errors << "config: invalid #{label}: #{e.message}"
end

def add_domain_provider_errors(errors, label, name, providers)
  provider = providers[name]
  unless provider
    errors << "#{label} references missing provider #{name}"
    return
  end

  behavior = provider["behavior"]
  return if %w[domain classical].include?(behavior)

  errors << "#{label} provider #{name} has behavior #{behavior.inspect}; expected domain or classical"
end

def canonical_domain_rules(entries)
  entries = entries.map(&:downcase).uniq.sort
  suffixes = entries.select { |entry| entry.start_with?("+.") }

  entries.reject do |entry|
    domain = entry.delete_prefix("+.")
    suffixes.any? do |suffix|
      next false if entry == suffix

      suffix_domain = suffix.delete_prefix("+.")
      domain == suffix_domain || domain.end_with?(".#{suffix_domain}")
    end
  end
end

def domain_payload_from_classical_source(path)
  entries = []
  File.foreach(path).with_index(1) do |line, line_number|
    line = line.strip
    next if line.empty? || line.start_with?("#")

    type, value, extra = line.split(",", 3)
    unless extra.nil? && !value.to_s.empty? && %w[DOMAIN DOMAIN-SUFFIX].include?(type)
      raise "#{path.delete_prefix("#{ROOT}/")}: malformed domain rule at line #{line_number}: #{line}"
    end

    entries << (type == "DOMAIN-SUFFIX" ? "+.#{value.delete_prefix(".")}" : value)
  end
  canonical_domain_rules(entries)
end

def domain_rules_intersect?(left, right)
  left_suffix = left.start_with?("+.")
  right_suffix = right.start_with?("+.")
  left_domain = left.delete_prefix("+.").downcase
  right_domain = right.delete_prefix("+.").downcase

  if left_suffix && right_suffix
    left_domain == right_domain ||
      left_domain.end_with?(".#{right_domain}") ||
      right_domain.end_with?(".#{left_domain}")
  elsif left_suffix
    right_domain == left_domain || right_domain.end_with?(".#{left_domain}")
  elsif right_suffix
    left_domain == right_domain || left_domain.end_with?(".#{right_domain}")
  else
    left_domain == right_domain
  end
end

def payload_for(path)
  document = YAML.load_file(path)
  document.is_a?(Hash) ? document["payload"] : nil
rescue Psych::SyntaxError => e
  raise "invalid YAML: #{e.message.lines.first.strip}"
end

def canonical_cidr(value)
  address, prefix_text = value.split("/", 2)
  raise IPAddr::InvalidAddressError, "missing prefix" unless prefix_text&.match?(/\A\d+\z/)

  ip = IPAddr.new(address)
  prefix = Integer(prefix_text, 10)
  max_prefix = ip.ipv4? ? 32 : 128
  raise IPAddr::InvalidPrefixError, prefix unless prefix.between?(0, max_prefix)

  "#{ip.mask(prefix)}/#{prefix}"
end

def valid_mihomo_domain_wildcards?(domain)
  labels = domain.split(".", -1)
  labels.each_with_index.all? do |label, index|
    valid_star = !label.include?("*") || label == "*"
    valid_plus = !label.include?("+") || (label == "+" && index.zero? && labels.length > 1)
    valid_star && valid_plus
  end
end

yaml_payloads = {}
yaml_files = Dir.glob(File.join(ROOT, "rules", "**", "*.yaml")).sort

yaml_files.each do |path|
  relative = path.delete_prefix("#{ROOT}/")
  begin
    duplicate_mapping_keys(path).each { |error| errors << "#{relative}: #{error}" }
    payload = payload_for(path)
    unless payload.is_a?(Array) && !payload.empty? && payload.all? { |item| item.is_a?(String) && !item.empty? }
      errors << "#{relative}: payload must be a non-empty string array"
      next
    end

    add_duplicate_value_errors(errors, relative, payload)
    yaml_payloads[path] = payload

    if relative.start_with?("rules/Domain/")
      invalid_wildcards = payload.reject { |rule| valid_mihomo_domain_wildcards?(rule) }
      unless invalid_wildcards.empty?
        errors << "#{relative}: invalid Mihomo domain wildcards: #{invalid_wildcards.first(3).join(', ')}"
      end

      payload.each do |rule|
        candidate = rule.delete_prefix("+.")
        begin
          IPAddr.new(candidate)
          errors << "#{relative}: IP literal in domain provider: #{rule}"
        rescue IPAddr::InvalidAddressError
          nil
        end
      end
    elsif File.basename(path).start_with?("localip_")
      payload.each do |rule|
        match = rule.match(/\AIP-CIDR6?,([^,]+)(?:,no-resolve)?\z/)
        errors << "#{relative}: invalid classical IP rule: #{rule}" and next unless match
        canonical_cidr(match[1])
      end
    else
      payload.each do |cidr|
        canonical = canonical_cidr(cidr)
        next unless relative.start_with?("rules/Game/")

        ip = IPAddr.new(canonical.split("/", 2).first)
        prefix = Integer(canonical.split("/", 2).last, 10)
        minimum = ip.ipv4? ? 16 : 32
        errors << "#{relative}: game CIDR broader than /#{minimum}: #{cidr}" if prefix < minimum
      end
    end
  rescue StandardError => e
    errors << "#{relative}: #{e.message}"
  end
end

mrs_files = Dir.glob(File.join(ROOT, "rules", "**", "*.mrs")).sort
yaml_payloads.each_key do |yaml_path|
  next if File.basename(yaml_path).start_with?("localip_")

  mrs_path = yaml_path.sub(/\.yaml\z/, ".mrs")
  errors << "#{yaml_path.delete_prefix("#{ROOT}/")}: missing paired MRS" unless File.exist?(mrs_path)
end
mrs_files.each do |mrs_path|
  yaml_path = mrs_path.sub(/\.mrs\z/, ".yaml")
  relative = mrs_path.delete_prefix("#{ROOT}/")
  errors << "#{relative}: orphan MRS without YAML source" unless yaml_payloads.key?(yaml_path)
end

Dir.mktmpdir("rules-validate") do |tmp_dir|
  yaml_payloads.each_with_index do |(yaml_path, _expected_payload), index|
    mrs_path = yaml_path.sub(/\.yaml\z/, ".mrs")
    next unless File.exist?(mrs_path)

    behavior = yaml_path.include?("/Domain/") ? "domain" : "ipcidr"
    rebuilt_mrs = File.join(tmp_dir, "#{index}.mrs")
    expected_path = File.join(tmp_dir, "#{index}-expected.list")
    actual_path = File.join(tmp_dir, "#{index}-actual.list")

    stdout, stderr, status = Open3.capture3(
      MIHOMO_BIN, "convert-ruleset", behavior, "yaml", yaml_path, rebuilt_mrs
    )
    unless status.success?
      detail = stderr.strip.empty? ? stdout.strip : stderr.strip
      errors << "#{yaml_path.delete_prefix("#{ROOT}/")}: cannot rebuild MRS: #{detail}"
      next
    end

    [[rebuilt_mrs, expected_path], [mrs_path, actual_path]].each do |source, output|
      stdout, stderr, status = Open3.capture3(
        MIHOMO_BIN, "convert-ruleset", behavior, "mrs", source, output
      )
      next if status.success?

      detail = stderr.strip.empty? ? stdout.strip : stderr.strip
      raise "cannot decode #{source}: #{detail}"
    end

    expected_lines = File.readlines(expected_path, chomp: true).reject { |line| line.empty? || line.start_with?("#") }
    actual_lines = File.readlines(actual_path, chomp: true).reject { |line| line.empty? || line.start_with?("#") }
    if behavior == "ipcidr"
      expected = expected_lines.map { |value| canonical_cidr(value) }.to_set
      actual = actual_lines.map { |value| canonical_cidr(value) }.to_set
    else
      expected = expected_lines.map(&:downcase).to_set
      actual = actual_lines.map(&:downcase).to_set
    end
    next if expected == actual

    missing = (expected - actual).first(3)
    extra = (actual - expected).first(3)
    errors << "#{mrs_path.delete_prefix("#{ROOT}/")}: YAML/MRS mismatch " \
              "missing=#{missing.inspect} extra=#{extra.inspect}"
  rescue StandardError => e
    errors << "#{mrs_path.delete_prefix("#{ROOT}/")}: #{e.message}"
  end
end

config_path = File.join(ROOT, "configfull_new.yaml")
begin
  duplicate_mapping_keys(config_path).each { |error| errors << "config: #{error}" }
  config = YAML.load_file(config_path, aliases: true)
  groups = config.fetch("proxy-groups")
  group_names = groups.map { |group| group.fetch("name") }
  proxy_names = Array(config["proxies"]).map { |proxy| proxy.fetch("name") }
  providers = config.fetch("rule-providers")
  proxy_providers = config.fetch("proxy-providers")
  provider_names = providers.keys.to_set
  proxy_provider_names = proxy_providers.keys.to_set
  known_targets = (group_names + proxy_names + %w[DIRECT REJECT REJECT-DROP PASS COMPATIBLE]).to_set

  if providers.any? { |_name, provider| provider["type"] == "http" } && !known_targets.include?("规则更新")
    errors << "config: missing 规则更新 proxy group"
  end
  providers.each do |name, provider|
    next unless provider["type"] == "http"

    unless provider["proxy"] == "规则更新"
      errors << "config: HTTP rule provider #{name} must use proxy 规则更新"
    end
  end
  proxy_providers.each do |name, provider|
    next unless provider["type"] == "http"

    errors << "config: proxy provider #{name} must use proxy DIRECT" unless provider["proxy"] == "DIRECT"
  end

  duplicate_groups = group_names.tally.select { |_name, count| count > 1 }.keys
  errors << "config: duplicate proxy groups: #{duplicate_groups.join(', ')}" unless duplicate_groups.empty?

  custom_direct_proxies = Array(config["proxies"]).select { |proxy| proxy["type"] == "direct" }
  unless custom_direct_proxies.empty?
    names = custom_direct_proxies.map { |proxy| proxy["name"] }
    errors << "config: custom direct proxies are redundant with built-in DIRECT: #{names.join(', ')}"
  end

  redundant_wrapper_groups = group_names & ["全球直连", "🚫 拒绝", "⚪ 丢弃"]
  unless redundant_wrapper_groups.empty?
    errors << "config: redundant single-target wrapper groups: #{redundant_wrapper_groups.join(', ')}"
  end

  single_target_select_groups = groups.select do |group|
    group["type"] == "select" && Array(group["use"]).empty? && Array(group["proxies"]).one?
  end
  unless single_target_select_groups.empty?
    names = single_target_select_groups.map { |group| group["name"] }
    errors << "config: single-target select groups add no selection semantics: #{names.join(', ')}"
  end

  privacy_group = groups.find { |group| group["name"] == "隐私拦截" }
  unless privacy_group && privacy_group["type"] == "select" &&
         privacy_group["proxies"] == ["REJECT", "REJECT-DROP", "DIRECT", "节点选择"]
    errors << "config: 隐私拦截 must expose built-in reject/direct targets without wrapper groups"
  end

  lowrate_group = groups.find { |group| group["name"] == "低倍率/MITM节点" }
  unless lowrate_group && lowrate_group["hidden"] == true
    errors << "config: 低倍率/MITM节点 must remain hidden as an Emby-only helper"
  end

  %w[Urltest_Base Loadbalance_Base].each do |template_name|
    redundant_health_fields = config.fetch(template_name).keys & %w[url interval lazy]
    unless redundant_health_fields.empty?
      errors << "config: #{template_name} must inherit provider health checks instead of defining #{redundant_health_fields.join(', ')}"
    end
  end

  fallback_health_schedules = {
    "机场名称3优先" => [45, false, 2],
    "机场名称1优先" => [60, true, 2],
  }
  groups.select { |group| group["type"] == "fallback" }.each do |group|
    expected = fallback_health_schedules.fetch(group["name"], [60, true, 3])
    actual = group.values_at("interval", "lazy", "max-failed-times")
    next if actual == expected

    errors << "config: #{group.fetch("name")} fallback health schedule must be " \
              "interval=#{expected[0]}, lazy=#{expected[1]}, max-failed-times=#{expected[2]}"
  end

  airport2_enabled = proxy_provider_names.include?("Airport_02")
  airport_numbers = airport2_enabled ? %w[1 2 3 4] : %w[1 3 4]
  expected_airport_providers = airport_numbers.map { |number| "Airport_0#{number}" }
  unless config["use_ap_all"] == expected_airport_providers
    errors << "config: use_ap_all must be #{expected_airport_providers.inspect}"
  end
  expected_primary_providers = expected_airport_providers.reject { |provider| provider == "Airport_04" }
  unless config["use_ap_primary"] == expected_primary_providers
    errors << "config: use_ap_primary must be #{expected_primary_providers.inspect}"
  end

  provider_prefixes = {}
  expected_airport_providers.each do |provider_name|
    provider = proxy_providers[provider_name]
    unless provider
      errors << "config: missing proxy provider #{provider_name}"
      next
    end

    errors << "config: proxy provider #{provider_name} must be http" unless provider["type"] == "http"
    errors << "config: proxy provider #{provider_name} must use proxy DIRECT" unless provider["proxy"] == "DIRECT"
    url = provider["url"]
    unless url.is_a?(String) && !url.strip.empty?
      errors << "config: proxy provider #{provider_name} must have a non-empty string url"
    end
    prefix_value = provider.dig("override", "additional-prefix")
    prefix = prefix_value.strip if prefix_value.is_a?(String)
    if prefix.nil? || prefix.empty?
      errors << "config: proxy provider #{provider_name} must have a non-empty additional-prefix"
    elsif provider_prefixes.key?(prefix)
      errors << "config: proxy providers #{provider_prefixes[prefix]} and #{provider_name} share additional-prefix #{prefix.inspect}"
    else
      provider_prefixes[prefix] = provider_name
    end
    unless provider.dig("override", "skip-cert-verify") == true
      errors << "config: proxy provider #{provider_name} must enable skip-cert-verify"
    end
    errors << "config: proxy provider #{provider_name} must enable udp" unless provider.dig("override", "udp") == true
  end

  airport3_first_numbers = ["3"] + airport_numbers.reject { |number| number == "3" }
  expected_airport3_fallback_proxies = airport3_first_numbers.map { |number| "机场名称#{number}地区优先" }
  airport3_fallback_group = groups.find { |group| group["name"] == "机场名称3优先" }
  if airport3_fallback_group
    errors << "config: 机场名称3优先 must be a fallback group" unless airport3_fallback_group["type"] == "fallback"
    errors << "config: 机场名称3优先 must remain visible" if airport3_fallback_group["hidden"] == true
    errors << "config: 机场名称3优先 empty-fallback must be REJECT" unless airport3_fallback_group["empty-fallback"] == "REJECT"
    unless airport3_fallback_group["proxies"] == expected_airport3_fallback_proxies
      errors << "config: 机场名称3优先 proxies must be #{expected_airport3_fallback_proxies.inspect}"
    end
  else
    errors << "config: missing 机场名称3优先 proxy group"
  end

  airport_numbers.each do |number|
    fallback_name = "机场名称#{number}地区优先"
    provider_name = "Airport_0#{number}"
    region_order = number == "3" ? %w[日本 新加坡 香港 美国] : %w[香港 日本 新加坡 美国]
    expected_children = region_order.map { |region| "机场名称#{number}-#{region}" }
    region_fallback = groups.find { |group| group["name"] == fallback_name }
    unless region_fallback
      errors << "config: missing #{fallback_name} proxy group"
      next
    end

    errors << "config: #{fallback_name} must be a fallback group" unless region_fallback["type"] == "fallback"
    unless region_fallback["proxies"] == expected_children
      errors << "config: #{fallback_name} proxies must be #{expected_children.inspect}"
    end
    expected_children.each do |region_name|
      region_group = groups.find { |group| group["name"] == region_name }
      unless region_group && region_group["type"] == "url-test" && Array(region_group["use"]) == [provider_name]
        errors << "config: #{fallback_name} child #{region_name} must be a url-test using only #{provider_name}"
      end
    end
  end

  {
    "机场名称3-日本" => "region_jp_no_ctcu",
    "机场名称3-新加坡" => "region_sg_no_ctcu",
  }.each do |group_name, filter_name|
    group = groups.find { |candidate| candidate["name"] == group_name }
    unless group && group["filter"] == config.fetch(filter_name) &&
           group["exclude-filter"] == config.fetch("exclude_lowrate")
      errors << "config: #{group_name} must exclude pure CTCU while preserving the common rate filter"
    end
  end

  airport3_us_group = groups.find { |group| group["name"] == "机场名称3-美国" }
  unless airport3_us_group && airport3_us_group["filter"] == config.fetch("region_us") &&
         !airport3_us_group.key?("exclude-filter")
    errors << "config: 机场名称3-美国 must keep low-rate Airport_03 nodes in its automatic pool"
  end

  multi_airport_group = groups.find { |group| group["name"] == "机场名称1优先" }
  expected_multi_airport_proxies = airport_numbers.map { |number| "机场名称#{number}地区优先" }
  if multi_airport_group
    errors << "config: 机场名称1优先 must be a fallback group" unless multi_airport_group["type"] == "fallback"
    errors << "config: 机场名称1优先 must remain visible" if multi_airport_group["hidden"] == true
    errors << "config: 机场名称1优先 empty-fallback must be REJECT" unless multi_airport_group["empty-fallback"] == "REJECT"
    unless multi_airport_group["proxies"] == expected_multi_airport_proxies
      errors << "config: 机场名称1优先 proxies must be #{expected_multi_airport_proxies.inspect}"
    end
  else
    errors << "config: missing 机场名称1优先 proxy group"
  end

  node_selector = groups.find { |group| group["name"] == "节点选择" }
  unless node_selector && node_selector["type"] == "select" &&
         Array(node_selector["proxies"]).first(2) == ["机场名称3优先", "机场名称1优先"]
    errors << "config: 节点选择 must expose 机场名称3优先 then 机场名称1优先"
  end

  %w[香港 日本 新加坡 美国].each do |region|
    cross_airport_name = "#{region}-机场名称1优先"
    cross_airport_group = groups.find { |group| group["name"] == cross_airport_name }
    expected_cross_airport_proxies = airport_numbers.map { |number| "机场名称#{number}-#{region}" }
    if cross_airport_group
      errors << "config: #{cross_airport_name} must be a fallback group" unless cross_airport_group["type"] == "fallback"
      unless cross_airport_group["proxies"] == expected_cross_airport_proxies
        errors << "config: #{cross_airport_name} proxies must be #{expected_cross_airport_proxies.inspect}"
      end
    else
      errors << "config: missing #{cross_airport_name} proxy group"
    end

    region_selector_name = "#{region}节点"
    region_selector = groups.find { |group| group["name"] == region_selector_name }
    expected_region_selector_proxies = [cross_airport_name] + expected_cross_airport_proxies + ["#{region}均衡"]
    if region_selector
      errors << "config: #{region_selector_name} must be a select group" unless region_selector["type"] == "select"
      unless region_selector["proxies"] == expected_region_selector_proxies
        errors << "config: #{region_selector_name} proxies must be #{expected_region_selector_proxies.inspect}"
      end
      unless Array(region_selector["use"]) == expected_airport_providers
        errors << "config: #{region_selector_name} use must be #{expected_airport_providers.inspect}"
      end
    else
      errors << "config: missing #{region_selector_name} proxy group"
    end

    airport3_cross_name = "#{region}-机场名称3优先"
    airport3_cross_group = groups.find { |group| group["name"] == airport3_cross_name }
    expected_airport3_cross_proxies = airport3_first_numbers.map { |number| "机场名称#{number}-#{region}" }
    if airport3_cross_group
      errors << "config: #{airport3_cross_name} must be a fallback group" unless airport3_cross_group["type"] == "fallback"
      errors << "config: #{airport3_cross_name} must be hidden" unless airport3_cross_group["hidden"] == true
      unless airport3_cross_group["proxies"] == expected_airport3_cross_proxies
        errors << "config: #{airport3_cross_name} proxies must be #{expected_airport3_cross_proxies.inspect}"
      end
    else
      errors << "config: missing #{airport3_cross_name} proxy group"
    end
  end

  expected_taiwan_proxies = airport_numbers.map { |number| "机场名称#{number}-台湾" }
  airport_numbers.each do |number|
    group_name = "机场名称#{number}-台湾"
    group = groups.find { |candidate| candidate["name"] == group_name }
    unless group && group["type"] == "url-test" && Array(group["use"]) == ["Airport_0#{number}"]
      errors << "config: #{group_name} must be a url-test using only Airport_0#{number}"
    end
  end

  taiwan_quality_group = groups.find { |group| group["name"] == "台湾-机场名称1优先" }
  if taiwan_quality_group
    errors << "config: 台湾-机场名称1优先 must be a fallback group" unless taiwan_quality_group["type"] == "fallback"
    errors << "config: 台湾-机场名称1优先 must be hidden" unless taiwan_quality_group["hidden"] == true
    unless taiwan_quality_group["proxies"] == expected_taiwan_proxies
      errors << "config: 台湾-机场名称1优先 proxies must be #{expected_taiwan_proxies.inspect}"
    end
  else
    errors << "config: missing 台湾-机场名称1优先 proxy group"
  end

  taiwan_selector = groups.find { |group| group["name"] == "台湾节点" }
  expected_taiwan_selector_proxies = ["台湾-机场名称1优先"] + expected_taiwan_proxies + ["台湾自动", "台湾均衡"]
  unless taiwan_selector && taiwan_selector["type"] == "select" &&
         taiwan_selector["proxies"] == expected_taiwan_selector_proxies &&
         Array(taiwan_selector["use"]) == expected_airport_providers
    errors << "config: 台湾节点 must prefer 台湾-机场名称1优先 and expose all airport-specific Taiwan groups"
  end

  primary_automatic_groups = %w[台湾自动 香港均衡 新加坡均衡 日本均衡 台湾均衡 美国均衡]
  primary_automatic_groups.each do |name|
    group = groups.find { |candidate| candidate["name"] == name }
    unless group && Array(group["use"]) == expected_primary_providers
      errors << "config: #{name} must use primary airports only: #{expected_primary_providers.inspect}"
    end
  end

  telegram_region_orders = {
    "TelegramEU" => %w[新加坡 日本 香港],
    "TelegramSG" => %w[新加坡 日本 香港],
    "TelegramUS" => %w[美国 新加坡 日本 香港],
  }
  telegram_region_orders.each do |name, regions|
    group = groups.find { |candidate| candidate["name"] == name }
    unless group
      errors << "config: missing #{name} proxy group"
      next
    end

    expected_prefix = regions.map { |region| "#{region}-机场名称3优先" }
    unless Array(group["proxies"]).first(expected_prefix.length) == expected_prefix
      errors << "config: #{name} must preserve DC order with airport-3-first regional fallbacks"
    end
    stale_candidates = Array(group["proxies"]) & (["节点选择"] + regions.map { |region| "#{region}-机场名称1优先" })
    unless stale_candidates.empty?
      errors << "config: #{name} retains stale quality-first candidates: #{stale_candidates.inspect}"
    end
  end

  rule_update_group = groups.find { |group| group["name"] == "规则更新" }
  expected_rule_update_proxies = expected_airport3_fallback_proxies + ["DIRECT"]
  if rule_update_group
    errors << "config: 规则更新 must be a fallback group" unless rule_update_group["type"] == "fallback"
    errors << "config: 规则更新 must be hidden" unless rule_update_group["hidden"] == true
    unless rule_update_group["proxies"] == expected_rule_update_proxies
      errors << "config: 规则更新 proxies must be #{expected_rule_update_proxies.inspect}"
    end
  end

  airport1_service_groups = %w[
    GoogleVPN Google Meta Microsoft Discord Talkatone LINE Signal TikTok NETFLIX DisneyPlus HBO
    Primevideo AppleTV Spotify 境外影音 境外社媒 境外通信 境外金融 加密资产 Wise 境外电商
  ]
  airport1_service_groups.each do |name|
    group = groups.find { |candidate| candidate["name"] == name }
    unless group && group["type"] == "select" && Array(group["proxies"]).first == "机场名称1优先"
      errors << "config: #{name} must be a select group preferring 机场名称1优先"
    end
  end

  airport3_service_groups = %w[
    YouTube FCM HuggingFace GitHub Docker 开发下载 Kryptex OneDrive 游戏平台 Speedtest STEAM
  ]
  airport3_service_groups.each do |name|
    group = groups.find { |candidate| candidate["name"] == name }
    unless group
      errors << "config: missing #{name} proxy group"
      next
    end

    errors << "config: #{name} must be a select group" unless group["type"] == "select"
    unless Array(group["proxies"]).first == "机场名称3优先"
      errors << "config: #{name} must prefer 机场名称3优先"
    end
    direct_candidates = Array(group["proxies"]) & ["全球直连", "🟢 直连", "DIRECT"]
    unless direct_candidates.empty?
      errors << "config: #{name} must not expose direct candidates: #{direct_candidates.inspect}"
    end
    if Array(group["proxies"]).include?("机场名称3地区优先")
      errors << "config: #{name} must not retain the stale airport-3 direct selection"
    end
    unless Array(group["proxies"]).include?("美国节点")
      errors << "config: #{name} must expose 美国节点 for temporary regional selection"
    end
  end

  {"AI" => "日本节点", "PayPal" => "日本节点", "哔哩东南亚" => "机场名称1优先"}.each do |name, expected|
    group = groups.find { |candidate| candidate["name"] == name }
    unless group && group["type"] == "select" && Array(group["proxies"]).first == expected
      errors << "config: #{name} must prefer #{expected}"
    end
  end

  global_group = groups.find { |group| group["name"] == "GLOBAL" }
  if global_group
    (airport1_service_groups + airport3_service_groups + %w[AI PayPal 哔哩东南亚]).uniq.each do |name|
      errors << "config: GLOBAL must expose #{name}" unless Array(global_group["proxies"]).include?(name)
    end
  else
    errors << "config: missing GLOBAL proxy group"
  end

  groups.each do |group|
    Array(group["use"]).each do |provider|
      errors << "config: #{group['name']} uses missing proxy provider #{provider}" unless proxy_provider_names.include?(provider)
    end
    Array(group["proxies"]).each do |target|
      errors << "config: #{group['name']} references missing proxy/group #{target}" unless known_targets.include?(target)
    end
  end

  referenced_providers = Set.new
  rules = config.fetch("rules")
  unless rules.is_a?(Array) && !rules.empty? && rules.all? { |rule| rule.is_a?(String) && !rule.empty? }
    raise "rules must be a non-empty string array"
  end
  add_duplicate_value_errors(errors, "config rules", rules)
  add_single_final_match_error(errors, "config rules", rules)

  expected_epic_rule = "RULE-SET,Epic_domain,游戏平台"
  unless rules.grep(/\ARULE-SET,Epic_domain,/) == [expected_epic_rule]
    errors << "config: Epic_domain must route through 游戏平台"
  end

  expected_bahamut_rule = "RULE-SET,bahamut_domain,台湾节点"
  unless rules.grep(/\ARULE-SET,bahamut_domain,/) == [expected_bahamut_rule]
    errors << "config: bahamut_domain must route directly through 台湾节点 without a wrapper group"
  end

  rules.each_with_index do |rule, index|
    fields = rule.split(",")
    if fields.first == "RULE-SET"
      referenced_providers << fields[1]
      errors << "config: rule #{index + 1} references missing provider #{fields[1]}" unless provider_names.include?(fields[1])
      target = fields[2]
    else
      target = fields.first == "MATCH" ? fields[1] : fields[-1]
      target = fields[-2] if fields[-1] == "no-resolve"
    end
    errors << "config: rule #{index + 1} has missing target #{target}" unless known_targets.include?(target)
  end

  quality_category_routes = {
    "finance_domain" => "境外金融",
    "cryptocurrency_domain" => "加密资产",
    "communication_domain" => "境外通信",
    "ecommerce_domain" => "境外电商",
  }
  quality_category_routes.each do |provider, target|
    expected = "RULE-SET,#{provider},#{target}"
    unless rules.grep(/\ARULE-SET,#{Regexp.escape(provider)},/) == [expected]
      errors << "config: #{provider} must route exactly once through #{target}"
    end
  end

  priority_download_rules = [
    "DOMAIN-SUFFIX,huggingface.co,HuggingFace",
    "DOMAIN-SUFFIX,hf.co,HuggingFace",
    "DOMAIN-SUFFIX,docker.io,Docker",
    "DOMAIN,production.cloudfront.docker.com,Docker",
    "DOMAIN,docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com,Docker",
    "DOMAIN,download.docker.com,Docker",
    "DOMAIN,desktop.docker.com,Docker",
    "DOMAIN,get.docker.com,Docker",
    "DOMAIN-SUFFIX,googlesource.com,开发下载",
    "DOMAIN,storage.googleapis.com,开发下载",
    "DOMAIN-SUFFIX,dl.google.com,开发下载",
    "RULE-SET,dev_download_domain,开发下载",
  ]
  priority_download_rules.each do |rule|
    errors << "config: missing priority download rule #{rule}" unless rules.include?(rule)

    predicate = rule.split(",").first(2)
    first_same_predicate = rules.find { |candidate| candidate.split(",").first(2) == predicate }
    unless first_same_predicate == rule
      errors << "config: #{predicate.join(',')} is first routed by #{first_same_predicate.inspect}, expected #{rule}"
    end
  end

  order = lambda do |prefix|
    rules.index { |rule| rule.start_with?(prefix) } || raise("missing ordered rule #{prefix}")
  end
  download_precedence = [
    ["DOMAIN-SUFFIX,huggingface.co,", "RULE-SET,proxy_domain,"],
    ["DOMAIN-SUFFIX,huggingface.co,", "RULE-SET,ai!cn_domain,"],
    ["DOMAIN-SUFFIX,hf.co,", "RULE-SET,proxy_domain,"],
    ["DOMAIN-SUFFIX,hf.co,", "RULE-SET,ai!cn_domain,"],
    ["DOMAIN-SUFFIX,docker.io,", "RULE-SET,proxy_domain,"],
    ["DOMAIN,production.cloudfront.docker.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN,download.docker.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN,desktop.docker.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN,get.docker.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN-SUFFIX,googlesource.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN-SUFFIX,googlesource.com,", "RULE-SET,google_domain,"],
    ["DOMAIN,storage.googleapis.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN,storage.googleapis.com,", "RULE-SET,google_domain,"],
    ["DOMAIN-SUFFIX,dl.google.com,", "RULE-SET,proxy_domain,"],
    ["DOMAIN-SUFFIX,dl.google.com,", "RULE-SET,google_domain,"],
    ["RULE-SET,dev_download_domain,", "RULE-SET,proxy_domain,"],
    ["RULE-SET,dev_download_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,dev_download_domain,", "RULE-SET,github_domain,"],
    ["RULE-SET,dev_download_domain,", "RULE-SET,onedrive_domain,"],
    ["RULE-SET,dev_download_domain,", "RULE-SET,microsoft_domain,"],
  ]
  download_precedence.each do |before, after|
    errors << "config: #{before} must precede #{after}" unless order.call(before) < order.call(after)
  end

  fake_ip_mode = config.dig("dns", "fake-ip-filter-mode")
  errors << "config: dns.fake-ip-filter-mode must be rule" unless fake_ip_mode == "rule"
  fake_ip_rules = config.dig("dns", "fake-ip-filter")
  unless fake_ip_rules.is_a?(Array) && !fake_ip_rules.empty? &&
         fake_ip_rules.all? { |rule| rule.is_a?(String) && !rule.empty? }
    raise "dns.fake-ip-filter must be a non-empty string array"
  end
  add_duplicate_value_errors(errors, "config fake-ip-filter", fake_ip_rules)
  add_single_final_match_error(errors, "config fake-ip-filter", fake_ip_rules)

  fake_ip_rule_types = %w[DOMAIN DOMAIN-SUFFIX DOMAIN-KEYWORD DOMAIN-REGEX DOMAIN-WILDCARD GEOSITE RULE-SET MATCH]
  fake_ip_rules.each_with_index do |rule, index|
    fields = rule.split(",").map(&:strip)
    type = fields.first.to_s.upcase
    unless fake_ip_rule_types.include?(type)
      errors << "config: fake-ip-filter rule #{index + 1} has unsupported type #{type.inspect}"
      next
    end

    if type == "MATCH"
      unless fields.length == 2
        errors << "config: fake-ip-filter rule #{index + 1} MATCH must have exactly one action"
        next
      end
      action = fields[1]
    elsif type == "DOMAIN-REGEX"
      if fields.length < 3 || fields[1...-1].join(",").empty?
        errors << "config: fake-ip-filter rule #{index + 1} is malformed"
        next
      end
      action = fields.last
    else
      if fields.length != 3 || fields[1].to_s.empty?
        errors << "config: fake-ip-filter rule #{index + 1} is malformed"
        next
      end
      action = fields[2]
    end
    unless %w[fake-ip real-ip].include?(action.downcase)
      errors << "config: fake-ip-filter rule #{index + 1} has invalid action #{action.inspect}"
    end

    next unless type == "RULE-SET"

    provider = fields[1]
    referenced_providers << provider
    add_domain_provider_errors(errors, "config: fake-ip-filter", provider, providers)
  end

  (config.dig("dns", "nameserver-policy") || {}).each_key do |key|
    next unless key.downcase.start_with?("rule-set:")

    names = key.split(":", 2).last.split(",").map(&:strip)
    errors << "config: nameserver-policy has empty rule-set reference in #{key.inspect}" if names.any?(&:empty?)
    names.reject(&:empty?).each do |provider|
      referenced_providers << provider
      add_domain_provider_errors(errors, "config: nameserver-policy", provider, providers)
    end
  end

  unused_providers = provider_names - referenced_providers
  errors << "config: unused rule providers: #{unused_providers.to_a.sort.join(', ')}" unless unused_providers.empty?

  lowrate = Regexp.new(config.fetch("lowrate_mitm"))
  ["香港0.5x", "日本 0.4倍", "0.05x 新加坡", "HK MITM", "pornhub SG"].each do |name|
    errors << "config: lowrate_mitm misses #{name}" unless lowrate.match?(name)
  end
  ["香港10.5x", "日本0.51倍", "新加坡0x", "美国0.5x"].each do |name|
    errors << "config: lowrate_mitm overmatches #{name}" if lowrate.match?(name)
  end

  excluded_rate = Regexp.new(config.fetch("exclude_lowrate"))
  ["香港0.05x", "日本0.25倍", "新加坡0.3x", "香港5x", "日本10.5倍"].each do |name|
    errors << "config: exclude_lowrate misses #{name}" unless excluded_rate.match?(name)
  end
  ["香港0.4x", "日本4.99倍", "美国10.5节点"].each do |name|
    errors << "config: exclude_lowrate overmatches #{name}" if excluded_rate.match?(name)
  end

  region_samples = {
    "region_hk" => {
      required: ["香港 01", "HK 01", "Hong Kong 01"],
      forbidden: ["SHK 01", "Singapore 01"],
    },
    "region_sg" => {
      required: ["新加坡 01", "SG 01", "Singapore 01"],
      forbidden: ["SGP 01", "消息更新节点"],
    },
    "region_jp" => {
      required: ["日本 01", "JP 01", "Japan 01"],
      forbidden: ["JPN 01", "jupiter 01"],
    },
    "region_sg_no_ctcu" => {
      required: ["新加坡专线|HY2", "新加坡高速|CTCUCM", "SG Premium"],
      forbidden: ["新加坡高速|CTCU", "CTCU|Singapore", "日本高速|CUCM"],
    },
    "region_jp_no_ctcu" => {
      required: ["日本专线|HY2", "日本高速|CUCM", "JP Premium"],
      forbidden: ["日本高速|CTCU", "CTCU|Japan", "新加坡高速|CTCUCM"],
    },
    "region_us" => {
      required: ["美国 01", "US 01", "United States 01", "Seattle 01"],
      forbidden: ["BUS 01", "Russia Moscow 01"],
    },
    "region_tw" => {
      required: ["台湾 01", "台灣 01", "臺灣 01", "TW 01", "Taiwan 01", "Taipei 01", "新北 01", "台中 01"],
      forbidden: ["后台维护节点", "电视台专线", "舞台节点"],
    },
    "region_eu" => {
      required: ["德国 法兰克福", "Germany Frankfurt", "DE Frankfurt", "UK London",
                 "GB London", "France Paris", "Berlin 01", "Madrid 01", "Warsaw 01"],
      forbidden: ["UPDATE 01", "GUIDE 01", "US Seattle", "台湾 Taipei",
                  "Chrome Optimized", "Latency Comparison", "CyberLink Relay"],
    },
  }
  region_samples.each do |name, samples|
    add_regex_sample_errors(
      errors,
      name,
      config.fetch(name),
      required: samples[:required],
      forbidden: samples[:forbidden]
    )
  end

  provider_template = config.fetch("PProviders")
  information_nodes = [
    "Traffic: 100 GB", "traffic: 100 GB", "Expire: 2026-12-31", "EXPIRED",
    "Used: 20 GB", "TOTAL: 100 GB", "Email: user@example.com", "Panel: status",
    "Panel Notice", "剩余流量：100 GB", "已用流量：20 GB", "套餐到期：2026-12-31",
  ]
  real_nodes = [
    "香港备用 01", "日本支持流媒体 02", "美国更新线路 03",
    "机场专线 新加坡 04", "香港直连优化 05", "Traffic Optimized 香港 06",
    "Remaining Fast 日本 07", "Total Freedom 美国 08", "Email Relay 香港 09", "Panel Pro 新加坡 10",
  ]
  if provider_template["exclude-filter"]
    add_regex_sample_errors(
      errors,
      "PProviders.exclude-filter",
      provider_template["exclude-filter"],
      required: information_nodes,
      forbidden: real_nodes
    )
  elsif provider_template["filter"]
    pattern = Regexp.new(provider_template["filter"])
    information_nodes.each do |name|
      errors << "config: PProviders.filter keeps subscription information #{name}" if pattern.match?(name)
    end
    real_nodes.each do |name|
      errors << "config: PProviders.filter excludes real node #{name}" unless pattern.match?(name)
    end
  else
    errors << "config: PProviders must define filter or exclude-filter"
  end

  # Providers served by this repository must exist in the just-built tree.
  # Otherwise a missing builder can be hidden by an older remote artifact and
  # `mihomo -t` still succeeds.
  config.fetch("rule-providers").each do |name, provider|
    url = provider["url"].to_s
    match = url.match(%r{\Ahttps://raw\.githubusercontent\.com/7ac9d42/Rules/(?:refs/heads/)?[^/]+/(rules/.+)\z})
    next unless match

    local_path = File.join(ROOT, match[1])
    unless File.file?(local_path) && File.size?(local_path)
      errors << "config: local provider #{name} has no non-empty built artifact #{match[1]}"
    end

    extension = File.extname(local_path)
    expected_format = extension == ".mrs" ? "mrs" : "text"
    errors << "config: local provider #{name} must use format #{expected_format}" unless provider["format"] == expected_format

    expected_behavior = if extension == ".list"
                          "classical"
                        elsif match[1].start_with?("rules/Domain/")
                          "domain"
                        else
                          "ipcidr"
                        end
    unless provider["behavior"] == expected_behavior
      errors << "config: local provider #{name} must use behavior #{expected_behavior}"
    end
  end

  ordering = [
    ["RULE-SET,banAd_core_domain,", "RULE-SET,banAd_pcdn_domain,"],
    ["RULE-SET,banAd_pcdn_domain,", "RULE-SET,wechat_domain,"],
    ["RULE-SET,wechat_domain,", "RULE-SET,banAd_low_domain,"],
    ["RULE-SET,direct_domain,", "RULE-SET,banAd_low_domain,"],
    ["RULE-SET,banAd_low_domain,", "RULE-SET,apple_domain,"],
    ["RULE-SET,apple_update_domain,", "RULE-SET,apple_cn_domain,"],
    ["RULE-SET,apple_cn_domain,", "RULE-SET,apple_domain,"],
    ["RULE-SET,apple_domain,", "RULE-SET,proxy_domain,"],
    ["RULE-SET,biliintl_domain,", "RULE-SET,bilibili_domain,"],
    ["RULE-SET,bilibili_domain,", "RULE-SET,proxy_domain,"],
    ["RULE-SET,proxy_domain,", "RULE-SET,cn_domain,"],
    ["RULE-SET,cn_domain,", "RULE-SET,telegram_domain,"],
    ["RULE-SET,cn_domain,", "RULE-SET,finance_domain,"],
    ["RULE-SET,cn_domain,", "RULE-SET,cryptocurrency_domain,"],
    ["RULE-SET,cn_domain,", "RULE-SET,communication_domain,"],
    ["RULE-SET,cn_domain,", "RULE-SET,ecommerce_domain,"],
    ["RULE-SET,telegram_domain,", "RULE-SET,communication_domain,"],
    ["RULE-SET,Wise_domain,", "RULE-SET,finance_domain,"],
    ["RULE-SET,paypal_domain,", "RULE-SET,finance_domain,"],
    ["RULE-SET,amazon_commerce_domain,", "RULE-SET,ecommerce_domain,"],
    ["RULE-SET,communication_domain,", "RULE-SET,cn_ip,"],
    ["RULE-SET,cryptocurrency_domain,", "RULE-SET,cn_ip,"],
    ["RULE-SET,finance_domain,", "RULE-SET,cn_ip,"],
    ["RULE-SET,ecommerce_domain,", "RULE-SET,cn_ip,"],
    ["RULE-SET,steam_cn_domain,", "RULE-SET,steam_domain,"],
    ["RULE-SET,proxy_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,discord_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,steam_domain,", "RULE-SET,microsoft_domain,"],
    ["RULE-SET,porn_domain,", "RULE-SET,github_domain,"],
    ["RULE-SET,porn_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,google_asn_cn,", "RULE-SET,cn_ip,"],
    ["RULE-SET,twitter_ip,", "RULE-SET,cn_ip,"],
  ]
  ordering.each do |before, after|
    errors << "config: #{before} must precede #{after}" unless order.call(before) < order.call(after)
  end

  expected_fallback = ["RULE-SET,cn_ip,DIRECT", "MATCH,节点选择"]
  unless rules.last(2) == expected_fallback && rules.grep(/\ARULE-SET,cn_ip,/) == [expected_fallback.first]
    errors << "config: resolving cn_ip safety net must be followed directly by proxy MATCH"
  end

  stdout, stderr, status = Open3.capture3(MIHOMO_BIN, "-t", "-f", config_path)
  errors << "config: mihomo test failed: #{stderr.strip}\n#{stdout.strip}" unless status.success?
rescue StandardError => e
  errors << "config: #{e.message}"
end

dev_source_path = File.join(ROOT, "scripts/data/dev-download.list")
dev_yaml_path = File.join(ROOT, "rules/Domain/dev-download.yaml")
dev_builder_path = File.join(ROOT, "scripts/build/dev-download.sh")
begin
  source_entries = File.readlines(dev_source_path, chomp: true)
                       .map(&:strip)
                       .reject { |line| line.empty? || line.start_with?("#") }
  duplicate_source_entries = source_entries.tally.select { |_entry, count| count > 1 }.keys
  unless duplicate_source_entries.empty?
    errors << "scripts/data/dev-download.list: duplicate entries: #{duplicate_source_entries.join(', ')}"
  end

  generated_entries = YAML.load_file(dev_yaml_path).fetch("payload")
  expected_entries = source_entries.uniq.sort
  unless generated_entries == expected_entries
    missing = (expected_entries - generated_entries).first(3)
    extra = (generated_entries - expected_entries).first(3)
    errors << "rules/Domain/dev-download.yaml: source/generated mismatch missing=#{missing.inspect} extra=#{extra.inspect}"
  end
rescue StandardError => e
  errors << "dev-download source/generated validation: #{e.message}"
end
errors << "scripts/build/dev-download.sh: builder must be executable" unless File.executable?(dev_builder_path)

begin
  local_domain_sources = {
    "direct" => File.join(ROOT, "rules", "Domain", "direct.list"),
    "proxy" => File.join(ROOT, "rules", "Domain", "Proxymini.list"),
  }
  local_domain_payloads = local_domain_sources.to_h do |name, source_path|
    generated_path = File.join(ROOT, "rules", "Domain", "#{name}.yaml")
    expected = domain_payload_from_classical_source(source_path)
    generated = yaml_payloads.fetch(generated_path)
    unless generated == expected
      missing = (expected - generated).first(3)
      extra = (generated - expected).first(3)
      errors << "#{generated_path.delete_prefix("#{ROOT}/")}: source/generated mismatch " \
                "missing=#{missing.inspect} extra=#{extra.inspect}"
    end
    [name, generated]
  end

  direct_proxy_conflicts = local_domain_payloads.fetch("direct").product(local_domain_payloads.fetch("proxy"))
                                                .select { |direct, proxy| domain_rules_intersect?(direct, proxy) }
  unless direct_proxy_conflicts.empty?
    samples = direct_proxy_conflicts.first(3).map { |direct, proxy| "#{direct} <-> #{proxy}" }
    errors << "rules/Domain: direct/proxy domain conflicts: #{samples.join(', ')}"
  end
rescue StandardError => e
  errors << "direct/proxy source/generated validation: #{e.message}"
end

critical_rules = {
  "rules/Domain/tvb.yaml" => {
    forbidden: ["+.content.jwplatform.com", "+.videos-f.jwpsrv.com", "edge.api.brightcove.com",
                "bcbolt446c5271-a.akamaihd.net", "+.youboranqs01.com"],
    required: ["infinity-c15.youboranqs01.com"],
  },
  "rules/Domain/Talkatone-domain.yaml" => {
    forbidden: ["+.agkn.com", "+.cohere.com", "+.crashlytics.com", "+.inmobi.com"],
    required: ["+.talkatone.com", "+.tktn.at", "+.tktn.be"],
  },
  "rules/IP/Talkatone-ip.yaml" => {
    forbidden: ["50.117.27.0/24", "216.172.154.0/24"],
    required: ["50.117.27.96/29"],
  },
  "rules/Telegram/TelegramEU.yaml" => {
    forbidden: ["5.28.192.0/18"],
    required: ["95.161.64.0/20", "109.239.140.0/24"],
  },
  "rules/Domain/fakeip-filter.yaml" => {
    forbidden: ["+.lan", "+.local", "+.qq.com", "+.tencent.com", "+.126.net"],
    required: ["+.music.126.net"],
  },
  "rules/Domain/amazon-commerce.yaml" => {
    forbidden: ["+.amazonaws.com", "+.cloudfront.net", "+.primevideo.com", "+.imdb.com", "+.kindle.com"],
    required: ["+.amazon.com", "+.amazon.co.jp", "+.amazon.co.uk"],
  },
  "rules/Domain/dev-download.yaml" => {
    forbidden: ["+.huggingface.co", "+.hf.co", "+.googlesource.com", "+.dl.google.com",
                "+.docker.com", "+.docker.io", "+.dockerstatic.com",
                "+.deno.com", "+.npmjs.com", "+.pypa.io", "+.pythonhosted.org",
                "+.dl.delivery.mp.microsoft.com", "+.download.visualstudio.microsoft.com",
                "+.download.windowsupdate.com", "+.officecdn.microsoft.com"],
    required: ["+.gitlab.com", "+.bitbucket.org", "+.deno.land", "+.jsr.io",
               "+.npmjs.org", "+.pypi.org", "+.files.pythonhosted.org", "+.crates.io",
               "+.maven.org", "+.nuget.org", "+.jsdelivr.net", "+.registry.k8s.io",
               "+.azurecr.io", "+.blob.core.windows.net", "+.data.azurecr.io",
               "+.gcr.io", "+.ghcr.io", "+.mcr.microsoft.com",
               "+.pkg-containers.githubusercontent.com", "+.pkg.dev", "+.quay.io",
               "+.archive.ubuntu.com", "+.cdimage.ubuntu.com", "+.conda.anaconda.org",
               "+.deb.debian.org", "+.dl-cdn.alpinelinux.org", "+.download.fedoraproject.org",
               "+.download.opensuse.org", "+.download.rockylinux.org", "+.ports.ubuntu.com",
               "+.prefix.dev", "+.releases.ubuntu.com", "+.repo.anaconda.com",
               "+.security.debian.org", "+.security.ubuntu.com", "+.packages.microsoft.com",
               "+.powershellgallery.com", "+.vsassets.io", "+.vscode-cdn.net",
               "+.cache-redirector.jetbrains.com",
               "+.dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com",
               "+.download-cdn.jetbrains.com",
               "+.download.jetbrains.com", "+.download.pytorch.org", "+.plugins.jetbrains.com",
               "+.registry.ollama.ai", "+.registry.ollama.com"],
  },
  "rules/Domain/streaming_hk.yaml" => {
    forbidden: ["+.bootstrapcdn.com", "+.jwpcdn.com", "+.jwplayer.com",
                "+.cognito-identity.us-east-1.amazonaws.com",
                "+.mobileanalytics.us-east-1.amazonaws.com",
                "+.d1k2us671qcoau.cloudfront.net"],
    required: ["+.viu.com", "d1k2us671qcoau.cloudfront.net",
               "infinity-c15.youboranqs01.com"],
  },
  "rules/Domain/streaming_sg.yaml" => {
    forbidden: ["+.tglmp03.akamaized.net"],
    required: ["+.mewatch.sg", "tglmp03.akamaized.net"],
  },
  "rules/Domain/streaming_tw.yaml" => {
    forbidden: ["+.app-measurement.com", "+.cwb.gov.tw", "+.hinet.net",
                "+.onead.com.tw", "+.polyfill.io", "+.pik.goog",
                "+.tw.yahoo.com", "+.amnet.tw", "+.lin.ee", "+.line.me",
                "+.line-apps.com", "+.line-cdn.net", "+.line-scdn.net",
                "+.line.naver.jp", "+.today.line.me",
                "d1k2us671qcoau.cloudfront.net", "d2anahhhmp1ffz.cloudfront.net",
                "dfp6rglgjqszk.cloudfront.net", "d151l6v8er5bdm.cloudfront.net",
                "d1v5ir2lpwr8os.cloudfront.net", "d22qjgkvxw22r6.cloudfront.net",
                "d25xi40x97liuc.cloudfront.net", "dmqdd6hw24ucf.cloudfront.net",
                "d349g9zuie06uo.cloudfront.net", "d5m9nd9n1srh4.cloudfront.net"],
    required: ["+.linetv.tw", "d3c7rimkq79yfu.cloudfront.net",
               "gamer-cds.cdn.hinet.net"],
  },
  "rules/Domain/streaming_uk.yaml" => {
    forbidden: ["+.yospace.com", "+.c.contentsquare.net"],
    required: ["+.bbc.co.uk", "+.itv.com", "+.channel4.com",
               "+.channel5.com", "+.my5.tv", "d349g9zuie06uo.cloudfront.net"],
  },
}
critical_rules.each do |relative, constraints|
  payload = yaml_payloads[File.join(ROOT, relative)] || []
  constraints[:forbidden].each { |rule| errors << "#{relative}: forbidden rule #{rule}" if payload.include?(rule) }
  constraints[:required].each { |rule| errors << "#{relative}: missing required rule #{rule}" unless payload.include?(rule) }
end

google_payload = yaml_payloads[File.join(ROOT, "rules/Domain/google.yaml")] || []
errors << "rules/Domain/google.yaml: concatenated domains detected" if google_payload.any? { |rule| rule.include?("comgoogle-") }

wechat_payload = yaml_payloads[File.join(ROOT, "rules/Domain/WeChat.yaml")] || []
if wechat_payload.include?("apd-pcdnwxlogin.teg.tencent-cloud.net")
  errors << "rules/Domain/WeChat.yaml: PCDN endpoint leaked into WeChat product rules"
end

core_classical = File.join(ROOT, "rules/Domain/banAd_core_classical.list")
if File.exist?(core_classical) && File.foreach(core_classical).any? { |line| line.start_with?("DOMAIN-KEYWORD,") }
  errors << "rules/Domain/banAd_core_classical.list: unbounded core keyword"
end

%w[
  BypassCNandLan BypassCNandLan_someip China-IP-only
  Skip-all-China-IP-mini-and-LAN WoW-EU
].each do |basename|
  errors << "rules/Game: excluded source was published: #{basename}" if File.exist?(File.join(ROOT, "rules/Game", "#{basename}.yaml"))
end

Dir.glob(File.join(ROOT, "scripts", "build", "*.sh")).sort.each do |script|
  _stdout, stderr, status = Open3.capture3("bash", "-n", script)
  errors << "#{script.delete_prefix("#{ROOT}/")}: bash syntax error: #{stderr.strip}" unless status.success?
end

if errors.empty?
  puts "Validated #{yaml_files.length} YAML and #{mrs_files.length} MRS files; config and ordering are consistent."
  exit 0
end

warn errors.map { |error| "ERROR: #{error}" }.join("\n")
exit 1
