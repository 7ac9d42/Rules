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

config_paths = if ENV["MIHOMO_TEST_CONFIG"]
                 [ENV.fetch("MIHOMO_TEST_CONFIG")]
               else
                 %w[configfull_new.yaml cinfigfull_new_4.yaml].map { |name| File.join(ROOT, name) }
               end
config_paths.each do |config_path|
  begin
    duplicate_mapping_keys(config_path).each { |error| errors << "config: #{error}" }
    stdout, stderr, status = Open3.capture3(
      "python3", File.join(ROOT, "scripts/test-config-design.py"), "--static", "--config", config_path
    )
    errors << "config: design checks failed: #{stderr.strip}\n#{stdout.strip}" unless status.success?
    Dir.mktmpdir("mihomo-config-validation-") do |directory|
      stdout, stderr, status = Open3.capture3(MIHOMO_BIN, "-t", "-d", directory, "-f", config_path)
      errors << "config: mihomo test failed: #{stderr.strip}\n#{stdout.strip}" unless status.success?
    end
  rescue StandardError => e
    errors << "config: #{e.message}"
  end
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
    "direct" => File.join(ROOT, "scripts", "data", "direct.list"),
    "proxy" => File.join(ROOT, "scripts", "data", "proxy.list"),
  }
  local_domain_payloads = local_domain_sources.to_h do |name, source_path|
    published_name = name == "direct" ? "direct.list" : "Proxymini.list"
    published_path = File.join(ROOT, "rules", "Domain", published_name)
    errors << "#{published_path}: published source differs from scripts/data" unless File.binread(source_path) == File.binread(published_path)
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
  "rules/Telegram/Telegram.yaml" => {
    forbidden: ["5.28.192.0/18"],
    required: ["91.108.8.0/21", "91.108.16.0/21", "95.161.64.0/20",
               "109.239.140.0/24", "149.154.160.0/20", "2001:b28:f23c::/47"],
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
