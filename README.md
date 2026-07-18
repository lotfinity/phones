# PriceBridge

PriceBridge is a data-first Django market-intelligence system for comparing electronics listings across Algeria and Türkiye. It is not an ecommerce store. The application collects raw marketplace evidence, parses it into reviewable candidates, exports approved clean listings, and computes buyer-facing opportunities only when identity and price quality are strong enough.

## Current architecture

The canonical pipeline is:

```text
RawListing
  -> ParsedListingCandidate
  -> PhoneListing / LaptopListing / ConsoleListing
  -> clean opportunity snapshots and v2 exports
```

Raw source evidence must remain unchanged. Parser guesses belong in `ParsedListingCandidate`, and only reviewed or safely qualified candidates should be exported to clean listing tables.

Legacy models such as `MarketListing`, `ProductModel`, `DeviceVariant`, `OpportunitySnapshot`, and `DealSnapshot` remain for migration and historical compatibility. They are not the preferred path for new phone, laptop, or portable-console opportunity work.

See:

- `docs/PIPELINE.md` for the canonical workflow and legacy boundaries
- `docs/DATA_MODEL.md` for model details
- `TODO.md` for completed phases and the next priority
- `CHANGELOG.md` for implementation history

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Useful routes:

- `/` — active API-driven Bagisto-style opportunity UI
- `/<category>/<id>/` — active Bagisto-style opportunity detail, for example `/phone/649/`
- `/listings/` — listing inspection
- `/opportunities/` — legacy clean opportunity overview/table
- `/estore/` — server-rendered Django clean estore table and API namespace
- `/estore/api/opportunities/` — JSON opportunity cards for alternate frontends
- `/estore/api/opportunities/<category>/<id>/` — JSON product/detail contract for alternate frontends
- `/deals/` — buyer-facing deal cards
- `/import-lab/` — staff review workflow
- `/admin/` — Django admin

## Current UI Ownership

The current public UI is not a Django template in `market/templates/estore/`. It is the preserved Bagisto frontend served through Django:

- Routes: `pricebridge/urls.py` serves `/` and `/<category>/<id>/` with `market.views_estore_bagisto`.
- Index capture: `estoreui/pages/smartphones-preview.html`.
- Detail capture: `estoreui/pages/products/speakers-preview.html`.
- Renderer/HTML rewriting: `market/bagisto_source.py`.
- Data/API contract: `market/views_estore.py`.
- Browser adapters: `estoreui/assets/js/pricebridge-opportunities.js`, `pricebridge-detail.js`, `pricebridge-shell.js`, and `pricebridge-plan.js`.
- Bridge CSS: `estoreui/assets/css/bagisto-django-bridge.css`; copied Bagisto styles remain under `estoreui/assets/css`.

Legacy `/new/` routes redirect to `/`. Use `/estore/` only for the server-rendered Django estore table and `/ui-preview/` only for old side-by-side review views.

## Canonical raw-first workflow

### 1. Import raw listings

Attach to an already-open Chrome CDP marketplace tab when using Sahibinden or Ouedkniss imports.

```bash
python manage.py import_sahibinden_from_cdp \
  --cdp http://127.0.0.1:9222 \
  --category laptops \
  --query "MacBook Pro M3 16GB 512GB" \
  --max-rows 300

python manage.py import_ouedkniss_from_cdp \
  --cdp http://127.0.0.1:9222 \
  --category laptops \
  --query "MacBook Pro M3" \
  --limit 100
```

Instagram collection can use Instaloader or the CDP fallback:

```bash
python manage.py crawl_instagram_profile username_or_url --days 60 --limit 300
python manage.py harvest_instagram_profile_page \
  https://www.instagram.com/profile/ \
  --limit 20 \
  --download-images
python manage.py process_ocr_queue --limit 100
```

### 2. Parse into reviewable candidates

```bash
python manage.py parse_raw_listings --category phones --reparse --limit 500
python manage.py parse_raw_listings --category laptops --reparse --limit 500
python manage.py parse_raw_listings --category consoles --reparse --limit 500
```

### 3. Review data quality

Use `/import-lab/`, Django admin, or a local HTML report:

```bash
python manage.py export_data_review --category laptop --limit 500
python manage.py export_data_review \
  --q macbook \
  --limit 300 \
  --output exports/review_macbook.html
python manage.py export_data_review \
  --category laptop \
  --problem not_export_eligible
```

AI-assisted review is available for flagged or filtered candidates:

```bash
python manage.py agent_review_candidates --flagged-only --limit 20
python manage.py agent_review_candidates \
  --bucket not_export_eligible \
  --categories laptop \
  --limit 20
```

### 4. Export approved clean listings

```bash
python manage.py export_candidates --category phones --status pending --limit 500
python manage.py export_candidates --category laptops --status pending --limit 500
python manage.py export_candidates --category consoles --status pending --limit 500
```

### 5. Recompute clean opportunities

```bash
python manage.py recompute_phone_opportunities_v2 --write-snapshots
python manage.py recompute_laptop_opportunities_v2 --write-snapshots
python manage.py recompute_console_opportunities_v1 --write-snapshots
```

Buyer-facing laptop opportunities require strong identity, such as model + RAM + storage, model + CPU + GPU, or an explicit high-confidence variant match. Generic model-only rows stay in review.

### 6. Fill missing market comparisons

```bash
python manage.py build_enrichment_queries --category phones --limit 20
python manage.py build_enrichment_queries --category laptops --limit 20
python manage.py build_enrichment_queries --category consoles --limit 20
```

## Exchange rates

Refresh public EUR/TRY and EUR/USD rates, derive USD/TRY, and store the configured Algeria black-market EUR/DZD benchmark:

```bash
python manage.py fetch_exchange_rates \
  --dzd-per-eur-black 295 \
  --recompute-opportunities
```

Set `DZD_PER_EUR_BLACK` or pass `--dzd-per-eur-black`; do not substitute the official DZD rate for Algeria buy-side opportunity calculations.

Relevant environment settings:

```text
DZD_PER_EUR_BLACK
EUR_TRY
USD_TRY
FX_RATE_ENDPOINT
FX_RATE_SOURCE
FX_RATE_MAX_AGE_DAYS
```

## Validation

Run before pushing changes:

```bash
python manage.py check
python manage.py test
```

For the FX command specifically:

```bash
python manage.py test market.test_exchange_rates
```

## Local integrations

- Sahibinden and Ouedkniss CDP imports attach to an existing Chrome remote-debugging endpoint, normally `http://127.0.0.1:9222`.
- OCR can use `tesseract`, optional EasyOCR/PaddleOCR backends, OCR.space, or NVIDIA NIM depending on environment configuration.
- NVIDIA credentials are read from `NVIDIA_API_KEY` or `NVIDIA_NIM_API_KEY`.
- Instagram sessions can be provided through `INSTAGRAM_SESSION_PATH` or `INSTAGRAM_COOKIE_FILE`.

## Public repository warning

This repository currently tracks `db.sqlite3` intentionally and has also contained historical SQLite backups. Treat all committed databases as public data. Do not store real cookies, API keys, active sessions, private contact details, customer/supplier records, or reusable credentials in tracked databases or raw payloads.

The next repository priority is to audit and sanitize tracked databases, then decide whether Git should retain a sanitized demo dataset or stop tracking live database files entirely. See `TODO.md`.
