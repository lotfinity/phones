# PriceBridge Agent Notes

PriceBridge is a Django market-intelligence app, not ecommerce. Keep the first version data-first and admin-first.

Architecture:
- `market.models` stores generic electronics taxonomy, sources, Instagram posts, OCR results, supplier prices, listings, currency rates, opportunity snapshots, and product visual assets.
- `market.parsers` contains rough text parsers for supplier lists, Instagram captions, and OCR text.
- `market.collectors.instagram` uses Instaloader for public profile collection.
- Instagram collection can use `INSTAGRAM_SESSION_PATH` or `INSTAGRAM_COOKIE_FILE`; never print cookie values.
- `market.collectors.sahibinden_cdp` imports a user-opened Sahibinden search-result table through Chrome CDP.
- `market.collectors.ouedkniss_cdp` imports visible Ouedkniss listing cards from a user-opened Chrome CDP tab.
- `market.services.currency` contains editable local FX constants. No live-rate fetching yet.
- `market.services.opportunity` creates simple explainable opportunity snapshots.
- `market.services.commons` searches Wikimedia Commons via MediaWiki API for model/series logos and downloads assets into local storage.

Rules:
- Do not overbuild UI. Use Django admin and minimal internal tables.
- Do not create microservices.
- Do not hard-code secrets.
- Do not require paid APIs.
- Do not make optional OCR or Playwright dependencies mandatory.
- Only import Sahibinden from a user-opened Chrome CDP tab; do not bypass challenges or build anonymous scraping.
- Only import Ouedkniss from a user-opened Chrome CDP tab; keep Ouedkniss rows as `source_type=ouedkniss`.
- Ouedkniss CDP imports default to a 30-day freshness window. Do not import listings visibly older than one month unless the user explicitly changes the cutoff.
- Keep Instagram and Ouedkniss Algeria listings separate. Later comparison can use Instagram only, Ouedkniss only, or both.
- Do not invent fake user-facing data or use placeholder-looking market records.
- Product visual assets are stored separately in `ProductAsset`, not on `ProductModel`.
- Commons syncing uses MediaWiki API, not browser scraping.
- Missing logos are normal and should not block analysis or the dashboard.
- Always store license/attribution/restrictions metadata from Commons.
- Prefer SVG logos over PNG/JPG when available.
- Update `CHANGELOG.md` after meaningful work.

Useful commands:
- `python manage.py import_supplier_list --file path/to/list.txt`
- `python manage.py crawl_instagram_profile username_or_url --days 60 --limit 300`
- `python manage.py harvest_instagram_profile_page https://www.instagram.com/profile/ --limit 5 --download-images`
- `python manage.py harvest_and_process_instagram_profile https://www.instagram.com/profile/ --limit 10 --offset 20`
- `python manage.py process_ocr_queue --limit 100`
- `python manage.py import_sahibinden_from_cdp --cdp http://127.0.0.1:9222 --max-rows 300`
- `python manage.py import_ouedkniss_from_cdp --cdp http://127.0.0.1:9222 --limit 50 --max-age-days 30`
- `python manage.py run_opportunity_analysis`
- `python manage.py recompute_deal_snapshots`
- `python manage.py inspect_recent_data`
- `python manage.py sync_commons_assets --dry-run --model-id 1`
- `python manage.py sync_commons_assets --brand Samsung --min-score 60`
- `python manage.py seed_product_types_and_specs`
- `python manage.py inspect_catalog_specs`
- `python manage.py check`
- `python manage.py test`

Continuation point:
The app is ready to request the first Instagram profile username or URL and date range. Do not begin real Instagram crawling until the user provides that profile.
