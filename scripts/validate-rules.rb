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

    errors << "config: proxy provider #{name} must use proxy 🟢 直连" unless provider["proxy"] == "🟢 直连"
  end

  duplicate_groups = group_names.tally.select { |_name, count| count > 1 }.keys
  errors << "config: duplicate proxy groups: #{duplicate_groups.join(', ')}" unless duplicate_groups.empty?

  rule_update_group = groups.find { |group| group["name"] == "规则更新" }
  expected_rule_update_proxies = ["机场名称3地区优先", "机场名称1地区优先", "机场名称4地区优先", "🟢 直连"]
  if rule_update_group
    errors << "config: 规则更新 must be a fallback group" unless rule_update_group["type"] == "fallback"
    errors << "config: 规则更新 must be hidden" unless rule_update_group["hidden"] == true
    unless rule_update_group["proxies"] == expected_rule_update_proxies
      errors << "config: 规则更新 proxies must be #{expected_rule_update_proxies.inspect}"
    end
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

  order = lambda do |prefix|
    rules.index { |rule| rule.start_with?(prefix) } || raise("missing ordered rule #{prefix}")
  end
  ordering = [
    ["RULE-SET,banAd_core_domain,", "RULE-SET,banAd_pcdn_domain,"],
    ["RULE-SET,banAd_pcdn_domain,", "RULE-SET,wechat_domain,"],
    ["RULE-SET,wechat_domain,", "RULE-SET,banAd_low_domain,"],
    ["RULE-SET,apple_update_domain,", "RULE-SET,apple_cn_domain,"],
    ["RULE-SET,apple_cn_domain,", "RULE-SET,apple_domain,"],
    ["RULE-SET,steam_cn_domain,", "RULE-SET,steam_domain,"],
    ["RULE-SET,proxy_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,discord_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,steam_domain,", "RULE-SET,microsoft_domain,"],
    ["RULE-SET,porn_domain,", "RULE-SET,github_domain,"],
    ["RULE-SET,porn_domain,", "RULE-SET,google_domain,"],
    ["RULE-SET,google_asn_cn,", "RULE-SET,cn_ip,"],
  ]
  ordering.each do |before, after|
    errors << "config: #{before} must precede #{after}" unless order.call(before) < order.call(after)
  end

  stdout, stderr, status = Open3.capture3(MIHOMO_BIN, "-t", "-f", config_path)
  errors << "config: mihomo test failed: #{stderr.strip}\n#{stdout.strip}" unless status.success?
rescue StandardError => e
  errors << "config: #{e.message}"
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
