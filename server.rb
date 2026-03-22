require "json"
require "net/http"
require "time"
require "uri"
require "webrick"

PORT = ENV.fetch("PORT", "4567").to_i
HOST = ENV.fetch("HOST", "0.0.0.0")

SELANGOR_HIGHWAYS = [
  { code: "NKV", name: "NKVE" },
  { code: "KSS", name: "KESAS" },
  { code: "ELT", name: "ELITE" },
  { code: "NPE", name: "NPE" },
  { code: "LDP", name: "LDP" },
  { code: "KSA", name: "LKSA" },
  { code: "SRT", name: "SPRINT" },
  { code: "LTR", name: "LATAR" },
  { code: "SKV", name: "SKVE" },
  { code: "EKVE", name: "EKVE" },
  { code: "NNKSB", name: "NNKSB" },
  { code: "DASH", name: "DASH" },
  { code: "GCE", name: "GCE" },
  { code: "WCE", name: "WCE" },
  { code: "SUKE", name: "SUKE" }
].freeze

class CameraFetcher
  SIGNATURE_ENDPOINT = "https://www.llm.gov.my/assets/ajax.get_sig.php".freeze
  FEED_ENDPOINT = "https://www.llm.gov.my/assets/ajax.vigroot.php".freeze
  IMAGE_PATTERN = /<img\b[^>]*src=['"](?<src>data:image\/[^'"]+|https?:\/\/[^'"]+)['"][^>]*>/i.freeze

  def fetch(limit: 20)
    feeds = []

    SELANGOR_HIGHWAYS.each do |highway|
      images = extract_images(fetch_feed_markup(highway[:code]))

      images.each_with_index do |src, index|
        feeds << {
          id: "#{highway[:code]}-#{index + 1}",
          highway_code: highway[:code],
          highway_name: highway[:name],
          camera_name: "#{highway[:name]} Camera #{index + 1}",
          image_src: src
        }

        return feeds.first(limit) if feeds.size >= limit
      end
    rescue StandardError => e
      feeds << {
        id: "#{highway[:code]}-error",
        highway_code: highway[:code],
        highway_name: highway[:name],
        error: e.message
      }
    end

    feeds.first(limit)
  end

  private

  def fetch_feed_markup(highway_code)
    signature = get_json(build_uri(SIGNATURE_ENDPOINT, h: highway_code))
    uri = build_uri(
      FEED_ENDPOINT,
      h: highway_code,
      t: signature.fetch("t"),
      sig: signature.fetch("sig")
    )

    get_text(uri)
  end

  def extract_images(markup)
    markup.scan(IMAGE_PATTERN).flatten.uniq
  end

  def build_uri(base, params)
    uri = URI(base)
    uri.query = URI.encode_www_form(params)
    uri
  end

  def get_json(uri)
    JSON.parse(get_text(uri))
  end

  def get_text(uri)
    response = Net::HTTP.start(
      uri.host,
      uri.port,
      use_ssl: uri.scheme == "https",
      open_timeout: 10,
      read_timeout: 20
    ) do |http|
      request = Net::HTTP::Get.new(uri)
      request["User-Agent"] = "SelangorHighwayCameras/1.0"
      http.request(request)
    end

    unless response.is_a?(Net::HTTPSuccess)
      raise "LLM request failed with #{response.code}"
    end

    response.body
  end
end

class AppServer
  def initialize(port:)
    @fetcher = CameraFetcher.new
    @server = WEBrick::HTTPServer.new(
      Port: port,
      BindAddress: HOST,
      AccessLog: [],
      Logger: WEBrick::Log.new($stderr, WEBrick::Log::WARN)
    )
    mount_routes
  end

  def start
    trap("INT") { @server.shutdown }
    trap("TERM") { @server.shutdown }
    @server.start
  end

  private

  def mount_routes
    @server.mount_proc("/") do |_req, res|
      res["Content-Type"] = "text/html; charset=utf-8"
      res.body = File.read(File.join(__dir__, "web", "index.html"))
    end

    @server.mount_proc("/api/feeds") do |_req, res|
      feeds = @fetcher.fetch(limit: 20)
      res["Content-Type"] = "application/json; charset=utf-8"
      res["Cache-Control"] = "no-store"
      res.body = JSON.pretty_generate(
        fetched_at: Time.now.utc.iso8601,
        source: "Lembaga Lebuhraya Malaysia public CCTV endpoints",
        highways: SELANGOR_HIGHWAYS,
        feeds: feeds
      )
    rescue StandardError => e
      res.status = 502
      res["Content-Type"] = "application/json; charset=utf-8"
      res.body = JSON.generate(error: e.message)
    end
  end
end

AppServer.new(port: PORT).start if $PROGRAM_NAME == __FILE__
