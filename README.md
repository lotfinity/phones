# PriceBridge

PriceBridge is a data-first Django market-intelligence app for comparing electronics prices across Algeria and Türkiye. It starts with smartphones and keeps the schema generic for laptops, tablets, watches, and other electronics.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Admin is at `/admin/`. Minimal inspection pages are `/`, `/listings/`, and `/opportunities/`.

## Commands

```bash
python manage.py import_supplier_list --file path/to/list.txt
python manage.py crawl_instagram_profile username_or_url --days 60 --limit 300
python manage.py harvest_instagram_profile_page https://www.instagram.com/profile/ --limit 5 --offset 0 --download-images
python manage.py harvest_and_process_instagram_profile https://www.instagram.com/profile/ --limit 10 --offset 20
python manage.py process_ocr_queue --limit 100
python manage.py fetch_exchange_rates --dzd-per-eur-black 295 --recompute-opportunities
python manage.py run_opportunity_analysis
python manage.py inspect_recent_data
python manage.py import_sahibinden_from_cdp --cdp http://127.0.0.1:9222 --max-rows 300
python manage.py import_ouedkniss_from_cdp --cdp http://127.0.0.1:9222 --limit 50
```

`fetch_exchange_rates` stores fresh `CurrencyRate` rows for EUR/TRY, EUR/USD, derived USD/TRY, and the configured Algeria black-market EUR/DZD benchmark. Pass `--dzd-per-eur-black` or set `DZD_PER_EUR_BLACK` so Algeria opportunity math keeps using the realistic buy-side rate instead of official DZD.

Instagram collection uses Instaloader for public profiles. It does not bypass login challenges. If a session is needed, set `INSTAGRAM_SESSION_PATH` for an Instaloader session file or `INSTAGRAM_COOKIE_FILE` for a Netscape-format browser cookie export containing Instagram cookies.

OCR can use the local `tesseract` binary with `OCR_BACKEND=tesseract`. `OCR_BACKEND=easyocr` and `OCR_BACKEND=paddleocr` are prepared as optional stronger local backends; if the selected backend is missing, the app falls back to Tesseract instead of failing the whole queue. `OCR_BACKEND=ocrspace` uses OCR.space via `OCR_SPACE_API_KEY`, `OCR_SPACE_LANGUAGE`, and `OCR_SPACE_ENGINE`. `OCR_BACKEND=nvidia` uses NVIDIA NIM vision chat completions via `NVIDIA_API_KEY`, `NVIDIA_VISION_ENDPOINT`, and `NVIDIA_VISION_MODEL`.

`harvest_instagram_profile_page` is the browser/CDP fallback for saving visible profile-grid post or reel URLs into `InstagramPost` when Instaloader is blocked. Start Chrome with remote debugging first.

`harvest_and_process_instagram_profile` combines CDP harvesting with OCR queue processing and reports new URLs versus already-seen posts.

Sahibinden CDP import attaches to an already-open Chrome tab and imports visible search-result table rows into `MarketListing`. Start Chrome with remote debugging and open the prepared Sahibinden search page first.

Ouedkniss CDP import attaches to an already-open Ouedkniss search page and saves visible cards as Algeria `MarketListing` rows with `source_type=ouedkniss`. Instagram and Ouedkniss rows remain separate sources so later analysis can compare with either source or both.
