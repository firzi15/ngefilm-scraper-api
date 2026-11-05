# NGEFILM Scraper Bundle & REST API

Bundle scraper ini menyediakan library modul Python dan **REST API Service** yang bisa langsung dihubungi oleh aplikasi lain (Node.js, Go, Flutter, Android/iOS, dsb.) via HTTP JSON.

---

## 1. Menjalankan REST API Server

```bash
cd /root/chat/2026-11-05/session-9aece2c9-7ebe-4c4c-bf53-3bb16f6685d2/ngefilm-scraper

# Menggunakan virtualenv Scrapling
/root/venvs/scrapling/bin/python api_server.py --port 8000
```

Default bind: `http://0.0.0.0:8000` (CORS sudah aktif, bisa dipanggil dari browser/frontend web apa saja).

---

## 2. Dokumentasi Endpoint REST API

### A. Health & Status
* **URL:** `GET /health` atau `GET /`
* **Response:**
```json
{
  "status": "ok",
  "base_url": "https://new39.ngefilm.site",
  "endpoints": ["/api/home", "/api/search", "/api/detail"]
}
```

---

### B. List Film / Serial (Katalog Beranda)
* **URL:** `GET /api/home?page=1`
* **Query Params:**
  * `page` (opsional, default: `1`)
* **Response:**
```json
{
  "page": 1,
  "count": 20,
  "data": [
    {
      "title": "Primetime (2026)",
      "type": "movie",
      "year": "2026",
      "url": "https://new39.ngefilm.site/primetime-2026/",
      "thumbnail": "https://new39.ngefilm.site/wp-content/uploads/2026/11/lmrulvLbmaejTix1YaMxo1oGhH1.jpg",
      "rating": "6.8",
      "quality": "WEB-DL",
      "genres": ["Drama", "Thriller"]
    }
  ]
}
```

---

### C. Cari Film / Serial
* **URL:** `GET /api/search?q=avatar`
* **Query Params:**
  * `q` (wajib, kata kunci pencarian)
* **Response:**
```json
{
  "query": "avatar",
  "count": 5,
  "data": [ ... ]
}
```

---

### D. Detail Film & Link Player Iframe
* **URL:** `GET /api/detail?url=https://new39.ngefilm.site/primetime-2026/`
* **Query Params:**
  * `url` (wajib, link halaman film)
  * `all_servers` (opsional: `true` / `false`. Jika `true`, server akan menelusuri iframe dari semua tab alternatif `?player=2`, dsb.)
* **Response:**
```json
{
  "status": "success",
  "data": {
    "title": "Primetime (2026)",
    "type": "movie",
    "year": "2026",
    "url": "https://new39.ngefilm.site/primetime-2026/",
    "thumbnail": "https://new39.ngefilm.site/wp-content/uploads/2026/11/lmrulvLbmaejTix1YaMxo1oGhH1.jpg",
    "description": "Pada tahun 2006, pembawa acara To Catch a Predator...",
    "player_iframe": "https://hgcloud.to/e/16ctw6qvymon",
    "all_players": [
      { "server": "Server 1", "url": "https://hgcloud.to/e/16ctw6qvymon" },
      { "server": "Server 2", "page_url": "https://new39.ngefilm.site/primetime-2026/?player=2" }
    ],
    "episodes": [],
    "rating": "6.0",
    "votes": "277",
    "cast": ["Merritt Wever", "Robert Pattinson"],
    "trailer": "https://www.youtube.com/watch?v=SgYIVYAfzEM"
  }
}
```

---

## 3. Menjalankan Sebagai CLI Scraper
Jika ingin scrape langsung ke file JSONL/CSV tanpa REST API:
```bash
/root/venvs/scrapling/bin/python scrape_ngefilm.py --pages 1 --output data/hasil.jsonl
```
