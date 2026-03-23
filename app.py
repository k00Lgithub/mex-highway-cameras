import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_file


PORT = int(os.environ.get("PORT", "4567"))
HOST = os.environ.get("HOST", "0.0.0.0")

TARGET_HIGHWAYS = [
    # Official LLM CCTV selector uses KLP for E20 KL-Putrajaya (MEX).
    {"code": "KLP", "name": "MEX Highway"},
]

SIGNATURE_ENDPOINT = "https://www.llm.gov.my/assets/ajax.get_sig.php"
FEED_ENDPOINT = "https://www.llm.gov.my/assets/ajax.vigroot.php"
IMAGE_PATTERN = re.compile(
    r"""<img\b(?=[^>]*src=['"](?P<src>data:image/[^'"]+|https?://[^'"]+)['"])(?=[^>]*title=['"](?P<title>[^'"]+)['"])[^>]*>""",
    re.IGNORECASE,
)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

CACHE_TTL_SECONDS = int(os.environ.get("FEED_CACHE_TTL_SECONDS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "30"))


class CameraFetcher:
    def fetch(self, limit=None):
        feeds = []

        for highway in TARGET_HIGHWAYS:
            try:
                cameras = self.extract_cameras(self.fetch_feed_markup(highway["code"]))

                for index, camera in enumerate(cameras, start=1):
                    feeds.append(
                        {
                            "id": f'{highway["code"]}-{index}',
                            "highway_code": highway["code"],
                            "highway_name": highway["name"],
                            "camera_name": self.format_camera_name(camera["title"], highway["name"], index),
                            "image_src": camera["src"],
                        }
                    )

                    if limit is not None and len(feeds) >= limit:
                        return feeds[:limit]
            except Exception as exc:
                app.logger.warning(
                    "Failed to load feeds for %s: %s",
                    highway["code"],
                    exc,
                )
                feeds.append(
                    {
                        "id": f'{highway["code"]}-error',
                        "highway_code": highway["code"],
                        "highway_name": highway["name"],
                        "error": "Feed temporarily unavailable.",
                    }
                )

        return feeds[:limit]

    def fetch_feed_markup(self, highway_code):
        signature = self.get_json(self.build_url(SIGNATURE_ENDPOINT, {"h": highway_code}))
        return self.get_text(
            self.build_url(
                FEED_ENDPOINT,
                {
                    "h": highway_code,
                    "t": signature["t"],
                    "sig": signature["sig"],
                },
            )
        )

    def extract_cameras(self, markup):
        cameras = []
        seen = set()

        for match in IMAGE_PATTERN.finditer(markup):
            src = match.group("src")

            if src in seen:
                continue

            seen.add(src)
            cameras.append({"src": src, "title": match.group("title")})

        return cameras

    @staticmethod
    def format_camera_name(raw_title, highway_name, index):
        if not raw_title:
            return f"{highway_name} Camera {index}"

        name = raw_title

        if name.upper().startswith("KLP-CCTV-"):
            parts = name.split("-", 3)
            if len(parts) == 4:
                name = parts[3]

        name = name.replace("-", " ").strip()

        if not name:
            return f"{highway_name} Camera {index}"

        parts = []

        for part in name.split():
            upper = part.upper()

            if upper in {"RSA", "SKI"} or upper.startswith("KM"):
                parts.append(part.upper())
            else:
                parts.append(part.capitalize())

        return " ".join(parts)

    @staticmethod
    def build_url(base, params):
        return f"{base}?{urlencode(params)}"

    @staticmethod
    def get_json(url):
        return json.loads(CameraFetcher.get_text(url))

    @staticmethod
    def get_text(url):
        request = Request(url, headers={"User-Agent": "SelangorHighwayCameras/1.0"})
        try:
            with urlopen(request, timeout=20) as response:
                status = getattr(response, "status", response.getcode())
                if status < 200 or status >= 300:
                    raise RuntimeError(f"LLM request failed with {status}")
                return response.read().decode("utf-8", "replace")
        except HTTPError as exc:
            raise RuntimeError(f"LLM request failed with {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc


FETCHER = CameraFetcher()


class FeedCache:
    def __init__(self, ttl_seconds):
        self.ttl_seconds = ttl_seconds
        self.lock = threading.Lock()
        self.cached_payload = None
        self.cached_at = 0.0

    def get_payload(self):
        now = time.time()

        with self.lock:
            if self.cached_payload is not None and now - self.cached_at < self.ttl_seconds:
                return self.cached_payload

            payload = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "Lembaga Lebuhraya Malaysia public CCTV endpoints",
                "highways": TARGET_HIGHWAYS,
                "feeds": FETCHER.fetch(),
            }
            self.cached_payload = payload
            self.cached_at = now
            return payload


FEED_CACHE = FeedCache(CACHE_TTL_SECONDS)


class RateLimiter:
    def __init__(self, window_seconds, max_requests):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.lock = threading.Lock()
        self.requests_by_ip = {}

    def allow(self, client_ip):
        now = time.time()

        with self.lock:
            request_times = self.requests_by_ip.get(client_ip, [])
            request_times = [timestamp for timestamp in request_times if now - timestamp < self.window_seconds]

            if len(request_times) >= self.max_requests:
                self.requests_by_ip[client_ip] = request_times
                return False

            request_times.append(now)
            self.requests_by_ip[client_ip] = request_times
            return True


RATE_LIMITER = RateLimiter(RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX_REQUESTS)


@app.before_request
def enforce_rate_limit():
    if request.path != "/api/feeds":
        return None

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

    if RATE_LIMITER.allow(client_ip):
        return None

    app.logger.warning("Rate limit exceeded for %s", client_ip)
    return jsonify({"error": "Too many requests. Please try again shortly."}), 429


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    return response


@app.get("/")
def index():
    return send_file(Path(__file__).with_name("web").joinpath("index.html"))


@app.get("/api/feeds")
def feeds():
    try:
        return jsonify(FEED_CACHE.get_payload())
    except Exception as exc:
        app.logger.exception("Failed to load feeds: %s", exc)
        return jsonify({"error": "Unable to load feeds right now."}), 502


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
