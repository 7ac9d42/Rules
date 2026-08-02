#!/usr/bin/env ruby
# frozen_string_literal: true

require "ipaddr"
require "open3"
require "set"
require "tmpdir"
require "yaml"

ROOT = File.expand_path("..", __dir__)
errors = []

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
    payload = payload_for(path)
    unless payload.is_a?(Array) && !payload.empty? && payload.all? { |item| item.is_a?(String) && !item.empty? }
      errors << "#{relative}: payload must be a non-empty string array"
      next
    end

    duplicates = payload.tally.select { |_item, count| count > 1 }.keys
    errors << "#{relative}: duplicate entries: #{duplicates.first(3).join(', ')}" unless duplicates.empty?
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
      "mihomo", "convert-ruleset", behavior, "yaml", yaml_path, rebuilt_mrs
    )
    unless status.success?
      detail = stderr.strip.empty? ? stdout.strip : stderr.strip
      errors << "#{yaml_path.delete_prefix("#{ROOT}/")}: cannot rebuild MRS: #{detail}"
      next
    end

    [[rebuilt_mrs, expected_path], [mrs_path, actual_path]].each do |source, output|
      stdout, stderr, status = Open3.capture3(
        "mihomo", "convert-ruleset", behavior, "mrs", source, output
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
  config = YAML.load_file(config_path, aliases: true)
  groups = config.fetch("proxy-groups")
  group_names = groups.map { |group| group.fetch("name") }
  proxy_names = Array(config["proxies"]).map { |proxy| proxy.fetch("name") }
  provider_names = config.fetch("rule-providers").keys.to_set
  proxy_provider_names = config.fetch("proxy-providers").keys.to_set
  known_targets = (group_names + proxy_names + %w[DIRECT REJECT REJECT-DROP PASS COMPATIBLE]).to_set

  duplicate_groups = group_names.tally.select { |_name, count| count > 1 }.keys
  errors << "config: duplicate proxy groups: #{duplicate_groups.join(', ')}" unless duplicate_groups.empty?

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

  Array(config.dig("dns", "fake-ip-filter")).each do |rule|
    fields = rule.split(",")
    next unless fields.first == "RULE-SET"
    referenced_providers << fields[1]
    errors << "config: fake-ip-filter references missing provider #{fields[1]}" unless provider_names.include?(fields[1])
  end
  (config.dig("dns", "nameserver-policy") || {}).each_key do |key|
    next unless key.start_with?("rule-set:")
    provider = key.delete_prefix("rule-set:")
    referenced_providers << provider
    errors << "config: nameserver-policy references missing provider #{provider}" unless provider_names.include?(provider)
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
  errors << "config: MATCH must be the final rule" unless rules.last.start_with?("MATCH,")

  stdout, stderr, status = Open3.capture3("mihomo", "-t", "-f", config_path)
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
