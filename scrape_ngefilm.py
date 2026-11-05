#!/usr/bin/env python3
"""
Scraper katalog NGEFILM dengan kombinasi Scrapling & logika CloudX.

Fitur:
- Auto-resolve domain aktif via Website.json
- Bypass Cloudflare/LiteSpeed interstitial menggunakan Scrapling FetcherSession
- Parsing Title, Thumbnail (kualitas penuh), Deskripsi, Metadata
- Mendukung Film tunggal maupun TV Series (daftar episode)
- Ekstraksi iframe player URL (dari .gmr-embed-responsive iframe & tab multi-server /?player=N)

Penggunaan:
    python scrape_ngefilm.py --pages 1 --output data/ngefilm.jsonl
    python scrape_ngefilm.py --pages 1 --details --output data/ngefilm.jsonl
    python scrape_ngefilm.py --url https://new39.ngefilm.site/primetime-2026/ --output data/single.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from scrapling.fetchers import FetcherSession

CONFIG_JSON_URL = "https://raw.githubusercontent.com/Asm0d3usX/CloudX/builds/Website.json"
DEFAULT_BASE_URL = "https://new39.ngefilm.site"
UA_IMPERSONATE = "chrome"

FIELDS = [
    "title",
    "type",
    "year",
    "url",
    "thumbnail",
    "description",
    "player_iframe",
    "all_players",
    "episodes",
    "rating",
    "votes",
    "duration",
    "quality",
    "genres",
    "countries",
    "director",
    "cast",
    "trailer",
    "release_date",
    "scraped_at",
]

log = logging.getLogger("ngefilm")

CHALLENGE_MARKERS = (
    "just a moment",
    "one moment, please",
    "attention required",
    "access denied",
    "checking your browser",
)


def get_live_base_url() -> str:
    """Ambil domain aktif terbaru seperti pola pada CloudX."""
    try:
        req = urllib.request.Request(CONFIG_JSON_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            domains = data.get("ngefilm")
            if domains and isinstance(domains, list) and domains[0]:
                return domains[0].rstrip("/")
    except Exception as exc:
        log.warning("Gagal fetch domain dari Website.json (%s), fallback ke %s", exc, DEFAULT_BASE_URL)
    return DEFAULT_BASE_URL


def clean(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def first_text(scope, selector: str) -> str:
    el = scope.css(selector)
    if not el:
        return ""
    return clean(el[0].get_all_text(strip=True))


def first_attr(scope, selector: str, attr: str) -> str:
    return clean(scope.css(f"{selector}::attr({attr})").get())


def fix_image_quality(img_url: str) -> str:
    """Hapus resolusi (misal -152x228) agar mendapatkan gambar original (seperti di CloudX)."""
    if not img_url:
        return ""
    return re.sub(r"-\d+x\d+(?=\.\w+$)", "", img_url)


def extract_thumbnail(card) -> str:
    # 1. Dari card / figure detail
    img = card.css("figure.pull-left img") or card.css(".content-thumbnail img") or card.css("img")
    if img:
        raw = (
            img[0].attrib.get("data-src")
            or img[0].attrib.get("data-lazy-src")
            or img[0].attrib.get("srcset", "").split(" ")[0]
            or img[0].attrib.get("src", "")
        )
        if raw:
            return fix_image_quality(clean(raw))

    # 2. Dari meta tag og:image (pada halaman detail)
    og = card.css("meta[property='og:image']")
    if og and og[0].attrib.get("content"):
        return fix_image_quality(clean(og[0].attrib["content"]))

    return ""


def extract_iframe(page) -> str:
    """Ambil url iframe dari kontainer video player Muvipro."""
    iframes = page.css(".gmr-embed-responsive iframe") or page.css("#bannerplayer-wrap iframe")
    if not iframes:
        # Fallback ke iframe selain tracker Google
        for f in page.css("iframe"):
            src = f.attrib.get("src") or f.attrib.get("data-litespeed-src") or ""
            if src and "googletagmanager" not in src:
                return src
        return ""

    el = iframes[0]
    return el.attrib.get("data-litespeed-src") or el.attrib.get("src") or ""


def is_challenge(page) -> bool:
    title = (page.css("title::text").get() or "").lower()
    return any(marker in title for marker in CHALLENGE_MARKERS)


def fetch_with_retry(session, url: str, timeout: float = 30.0, attempts: int = 5):
    for attempt in range(1, attempts + 1):
        try:
            if hasattr(session, "get"):
                page = session.get(url)
            else:
                from scrapling.fetchers import Fetcher
                page = Fetcher.get(url, impersonate=UA_IMPERSONATE, stealthy_headers=True, timeout=timeout)
            if getattr(page, "status", None) == 200 and not is_challenge(page):
                return page
            log.warning("Challenge page / non-200 di %s (percobaan %d/%d)", url, attempt, attempts)
        except Exception as exc:
            log.warning("Fetch error %s: %s (percobaan %d/%d)", url, exc, attempt, attempts)
        if attempt < attempts:
            time.sleep(attempt * 4)
    raise RuntimeError(f"Gagal mengambil halaman valid dari {url}")


def parse_listing_item(card, base_url: str) -> dict:
    title = first_text(card, ".entry-title a") or first_text(card, "h2 a")
    rel_url = first_attr(card, ".entry-title a", "href") or first_attr(card, "a", "href")
    url = urljoin(base_url, rel_url)

    is_tv = "/tv/" in url or bool(card.css(".gmr-numbeps"))
    year_match = re.search(r"\((\d{4})\)", title)
    year = year_match.group(1) if year_match else ""

    return {
        "title": title,
        "type": "tv" if is_tv else "movie",
        "year": year,
        "url": url,
        "thumbnail": extract_thumbnail(card),
        "description": "",
        "player_iframe": "",
        "all_players": [],
        "episodes": [],
        "rating": first_text(card, ".gmr-rating-item"),
        "votes": "",
        "duration": first_text(card, ".gmr-duration-item"),
        "quality": first_text(card, ".gmr-quality-item a"),
        "genres": card.css(".gmr-movie-on a[rel*='category']::text").getall(),
        "countries": card.css(".gmr-movie-on [itemprop='contentLocation'] a::text").getall(),
        "director": first_text(card, "[itemprop='director'] [itemprop='name']"),
        "cast": [],
        "trailer": first_attr(card, ".gmr-trailer-popup", "href"),
        "release_date": first_attr(card, "time[itemprop='dateCreated']", "datetime"),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def parse_detail_page(session: FetcherSession, page, item: dict, base_url: str, fetch_all_servers: bool = False):
    """Lengkapi metadata, deskripsi, daftar episode, dan link iframe player."""
    desc = first_text(page, "div[itemprop='description'] > p") or first_text(page, ".entry-content-single > p:first-of-type")
    item["description"] = desc

    # Thumbnail (jika belum ada dari listing)
    if not item.get("thumbnail"):
        item["thumbnail"] = extract_thumbnail(page)
    rating = first_attr(page, "[itemprop='ratingValue']", "content") or first_text(page, "[itemprop='ratingValue']")
    votes = first_attr(page, "[itemprop='ratingCount']", "content") or first_text(page, "[itemprop='ratingCount']")
    if rating:
        item["rating"] = rating
    if votes:
        item["votes"] = votes

    # Aktor / Cast
    actors = page.css("span[itemprop='actors'] a::text").getall() or page.css("span[itemprop='actor'] a::text").getall()
    if actors:
        item["cast"] = actors

    # Trailer
    trailer = first_attr(page, "ul.gmr-player-nav li a.gmr-trailer-popup", "href")
    if trailer:
        item["trailer"] = trailer

    # Deteksi Episode jika serial TV
    ep_links = page.css("div.vid-episodes a, div.gmr-listseries a")
    episodes = []
    for ep in ep_links:
        href = ep.attrib.get("href")
        if not href or href == item["url"] or "/tv/" in href:
            continue
        ep_title = ep.attrib.get("title") or ep.get_all_text(strip=True)
        episodes.append({
            "title": clean(re.sub(r"(?i)Permalink ke\s*", "", ep_title)),
            "url": urljoin(base_url, href),
        })
    item["episodes"] = episodes

    # Ekstraksi Iframe Player
    main_iframe = extract_iframe(page)
    item["player_iframe"] = main_iframe

    servers = []
    if main_iframe:
        servers.append({"server": "Server 1", "url": main_iframe})

    # Cek tab server alternatif (?player=2, ?player=3, dll)
    tabs = page.css(".muvipro-player-tabs a")
    for tab in tabs:
        tab_href = tab.attrib.get("href", "")
        tab_name = clean(tab.get_all_text(strip=True)) or "Alt Server"
        if "?player=" in tab_href:
            server_page_url = urljoin(base_url, tab_href)
            if fetch_all_servers:
                try:
                    p_srv = fetch_with_retry(session, server_page_url, timeout=20.0, attempts=3)
                    srv_iframe = extract_iframe(p_srv)
                    if srv_iframe:
                        servers.append({"server": tab_name, "url": srv_iframe})
                except Exception as exc:
                    log.debug("Gagal fetch tab %s: %s", server_page_url, exc)
            else:
                servers.append({"server": tab_name, "page_url": server_page_url})

    item["all_players"] = servers
    return item


def normalize_row(item: dict) -> dict:
    row = {}
    for f in FIELDS:
        val = item.get(f, "")
        if isinstance(val, (list, dict)):
            row[f] = json.dumps(val, ensure_ascii=False)
        else:
            row[f] = clean(val)
    return row


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scraper Katalog & Player Iframe NGEFILM")
    p.add_argument("--url", default="", help="URL target spesifik atau listing awal (kosong = auto)")
    p.add_argument("--pages", type=int, default=1, help="Jumlah halaman (0 = semua)")
    p.add_argument("--details", action="store_true", default=True, help="Ambil halaman detail untuk player & sinopsis (default: True)")
    p.add_argument("--all-servers", action="store_true", help="Fetch setiap tab server alternatif (?player=2, dll)")
    p.add_argument("--limit", type=int, default=0, help="Batasi jumlah film")
    p.add_argument("--output", default="data/ngefilm.jsonl", help="Path file output (.jsonl atau .csv)")
    p.add_argument("--workers", type=int, default=2, help="Jumlah worker paralel untuk detail")
    p.add_argument("--delay", type=float, default=0.5, help="Delay antar request")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    base_url = get_live_base_url()
    log.info("Domain aktif: %s", base_url)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    is_csv = out_path.suffix.lower() == ".csv"

    items: list[dict] = []
    seen = set()

    with FetcherSession(impersonate=UA_IMPERSONATE, stealthy_headers=True, timeout=35.0) as session:
        # Jika user langsung memberikan link single film
        if args.url and not any(p in args.url for p in ["/page/", "?s="]) and args.url.rstrip("/") != base_url:
            log.info("Scraping single item: %s", args.url)
            p = fetch_with_retry(session, args.url)
            initial = {
                "title": first_text(p, "h1.entry-title"),
                "type": "tv" if "/tv/" in args.url else "movie",
                "year": "",
                "url": args.url,
                "thumbnail": "",
                "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            res = parse_detail_page(session, p, initial, base_url, fetch_all_servers=args.all_servers)
            items.append(res)
        else:
            start_url = args.url or f"{base_url}/"
            p = fetch_with_retry(session, start_url)

            # Cek total halaman
            nums = [int(clean(x)) for x in p.css("ul.page-numbers a.page-numbers::text").getall() if clean(x).isdigit()]
            last_page = max(nums) if nums else 1
            total_pages = last_page if args.pages == 0 else min(args.pages, last_page)

            log.info("Total halaman terdeteksi: %d; mengambil %d halaman", last_page, total_pages)

            for page_no in range(1, total_pages + 1):
                if page_no > 1:
                    page_url = f"{base_url}/page/{page_no}/"
                    p = fetch_with_retry(session, page_url)
                    time.sleep(args.delay)

                cards = p.css("article.item-infinite") or p.css("article.item")
                for c in cards:
                    parsed = parse_listing_item(c, base_url)
                    if parsed["url"] not in seen:
                        seen.add(parsed["url"])
                        items.append(parsed)
                        if args.limit and len(items) >= args.limit:
                            break
                log.info("Halaman %d/%d: %d total item ditemukan sejauh ini", page_no, total_pages, len(items))
                if args.limit and len(items) >= args.limit:
                    break

            if args.details and items:
                log.info("Mengambil detail & iframe player untuk %d item...", len(items))
                for idx, it in enumerate(items, start=1):
                    try:
                        p_detail = fetch_with_retry(session, it["url"])
                        parse_detail_page(session, p_detail, it, base_url, fetch_all_servers=args.all_servers)
                        log.info("[%d/%d] Selesai: %s -> Iframe: %s", idx, len(items), it["title"], it.get("player_iframe") or "(none)")
                    except Exception as exc:
                        log.warning("Gagal ambil detail %s: %s", it["url"], exc)
                    time.sleep(args.delay)

    # Simpan hasil
    with out_path.open("w", encoding="utf-8", newline="") as f:
        if is_csv:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for it in items:
                writer.writerow(normalize_row(it))
        else:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    log.info("Selesai! Disimpan ke: %s (%d item)", out_path, len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
