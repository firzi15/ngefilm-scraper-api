#!/usr/bin/env python3
"""
Lightweight REST API Server untuk Scraper NGEFILM.
Menggunakan library bawaan Python (http.server) & modul Scrapling.
Cocok di-bundle dan diakses oleh aplikasi/framework lain.

Endpoint:
  GET /health
  GET /api/home?page=1
  GET /api/search?q=avatar
  GET /api/detail?url=https://new39.ngefilm.site/primetime-2026/
"""

import json
import logging
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote_plus
from scrapling.fetchers import Fetcher

from scrape_ngefilm import (
    get_live_base_url,
    parse_listing_item,
    parse_detail_page,
    clean,
    UA_IMPERSONATE,
    CHALLENGE_MARKERS,
)

log = logging.getLogger("ngefilm-api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

base_url = get_live_base_url()


def api_fetch(url: str, timeout: float = 30.0, attempts: int = 5):
    for attempt in range(1, attempts + 1):
        try:
            page = Fetcher.get(url, impersonate=UA_IMPERSONATE, stealthy_headers=True, timeout=timeout)
            title = (page.css("title::text").get() or "").lower()
            if getattr(page, "status", None) == 200 and not any(m in title for m in CHALLENGE_MARKERS):
                return page
            log.warning("Challenge page di %s (percobaan %d/%d)", url, attempt, attempts)
        except Exception as exc:
            log.warning("Fetch error %s: %s (percobaan %d/%d)", url, exc, attempt, attempts)
        if attempt < attempts:
            time.sleep(attempt * 3)
    raise RuntimeError(f"Gagal mengambil halaman valid dari {url}")


class APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path in ("/", "/health"):
                return self._send_json(200, {
                    "status": "ok",
                    "base_url": base_url,
                    "endpoints": ["/api/home", "/api/search", "/api/detail"]
                })

            elif path == "/api/home":
                page = int(params.get("page", ["1"])[0])
                target_url = f"{base_url}/" if page == 1 else f"{base_url}/page/{page}/"
                p = api_fetch(target_url)

                cards = p.css("article.item-infinite") or p.css("article.item")
                results = [parse_listing_item(c, base_url) for c in cards]
                return self._send_json(200, {
                    "page": page,
                    "count": len(results),
                    "data": results
                })

            elif path == "/api/search":
                q = params.get("q", [""])[0]
                if not q:
                    return self._send_json(400, {"error": "Parameter 'q' query pencarian wajib diisi"})
                target_url = f"{base_url}/?s={quote_plus(q)}&post_type[]=post&post_type[]=tv"
                p = api_fetch(target_url)

                cards = p.css("article.item-infinite") or p.css("article.item")
                results = [parse_listing_item(c, base_url) for c in cards]
                return self._send_json(200, {
                    "query": q,
                    "count": len(results),
                    "data": results
                })

            elif path == "/api/detail":
                url = params.get("url", [""])[0]
                if not url:
                    return self._send_json(400, {"error": "Parameter 'url' wajib diisi"})
                all_servers = params.get("all_servers", ["false"])[0].lower() in ("1", "true")

                p = api_fetch(url)
                initial = {
                    "title": clean(p.css("h1.entry-title::text").get()),
                    "type": "tv" if "/tv/" in url else "movie",
                    "url": url,
                    "thumbnail": "",
                }
                detail = parse_detail_page(None, p, initial, base_url, fetch_all_servers=all_servers)
                return self._send_json(200, {"status": "success", "data": detail})

            else:
                return self._send_json(404, {"error": f"Endpoint {path} tidak ditemukan"})

        except Exception as exc:
            log.exception("Error request %s: %s", self.path, exc)
            return self._send_json(500, {"error": str(exc)})


def run_server(port: int = 8000, host: str = "0.0.0.0"):
    addr = (host, port)
    httpd = HTTPServer(addr, APIHandler)
    log.info("Server API NGEFILM aktif di http://%s:%d", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Server dihentikan.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="REST API Server Scraper Ngefilm")
    parser.add_argument("--port", type=int, default=8000, help="Port HTTP (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host binding (default: 0.0.0.0)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
