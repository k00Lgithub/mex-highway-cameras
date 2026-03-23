import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, send_file


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
                feeds.append(
                    {
                        "id": f'{highway["code"]}-error',
                        "highway_code": highway["code"],
                        "highway_name": highway["name"],
                        "error": str(exc),
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


@app.get("/")
def index():
    return send_file(Path(__file__).with_name("web").joinpath("index.html"))


@app.get("/api/feeds")
def feeds():
    try:
        return jsonify(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "Lembaga Lebuhraya Malaysia public CCTV endpoints",
                "highways": TARGET_HIGHWAYS,
                "feeds": FETCHER.fetch(),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
