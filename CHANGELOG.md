# Changelog
## 2026-07-12

### Instagram reprocessing and duplicate handling

- Made manual Instagram image queueing idempotent by matching existing posts by media filename/shortcode before creating new `InstagramPost` rows.
- Added `--reprocess-existing` to safely rerun OCR for already imported manual images without creating duplicate posts.
- Extended `match_instagram_manual_links_from_markdown` with an explicit Markdown profile export import mode that upserts posts by shortcode, downloads linked images, and avoids duplicate rows on rerun.
- Changed `process_ocr_queue` to update the latest OCR result for a post instead of appending duplicate OCR rows during reprocessing.
- Reprocessed `brothers_phone___official_` manual images with a pre-run SQLite backup and collapsed duplicate OCR rows for that source.
- Imported the Brothers Phone Markdown profile export, downloaded 36 new post/reel images, and processed their OCR queue with duplicate post/OCR/listing checks clean.
- Updated `fetch_exchange_rates` to accept the current Frankfurter list-shaped response as well as the previous `rates` object response, then refreshed FX and opportunity snapshots.
- Added `run_instagram_markdown_pipeline` to run Markdown import/download, source OCR/classification, FX refresh, legacy opportunity analysis, clean opportunity snapshots, and a final summary from one command.
- Made `run_instagram_markdown_pipeline` refuse the dummy OCR backend by default so imports cannot be silently marked processed with empty OCR text; reset the RDphone Markdown import back to pending OCR after detecting the dummy run.
- Deprecated non-NVIDIA OCR backends for Instagram processing, made NVIDIA the default OCR backend, and updated the NVIDIA prompt to extract parser-friendly model/storage/SIM/battery/cycles/condition/color/price/warranty lines plus visible text.
- Added local `.env` loading in Django settings so NVIDIA credentials and OCR settings are read from the ignored project `.env` file.
- Processed the RDphone Markdown import through NVIDIA OCR, producing 52 nonempty OCR rows and 48 Instagram market listings, then refreshed FX, legacy opportunity/deal snapshots, and clean opportunity snapshots.
- Added listing-match recomputation to the Instagram Markdown pipeline before opportunity analysis so newly OCR-created listings can pass opportunity eligibility gates.
- Updated the server-rendered estore index to include Instagram-backed legacy `DealSnapshot` cards, so NVIDIA-OCR Instagram opportunities appear even before they are exported into clean phone snapshots.

### Bagisto storefront PriceBridge semantics

- Restored `/estore/` to the server-rendered Django opportunity templates so real opportunity cards render in the HTML response, while keeping the preserved Bagisto port available at `/estore/bagisto/`.
- Added server-rendered brand filters, purchase-plan payload injection, plan drawer assets, and plan add/reserve actions to the Django estore index/detail templates.
- Reworked the active `/estore/` Bagisto port so opportunity cards use exact Algeria acquisition listings for image, condition, battery, availability, source ID, and source URL when possible.
- Replaced numeric confidence copy with five-star PriceBridge data-confidence metadata, added centralized source freshness availability states, and disabled acquisition actions for stale/unverified listings.
- Converted the cart behavior into a browser-only acquisition plan with localStorage persistence, no quantities, six-phone capacity enforcement, and plan drawer remove/count behavior.
- Removed the bundle product-detail capture from active detail routes and repurposed detail evidence areas toward Türkiye comparable listings and plan summary semantics.
- Tightened supplier old-price/discount handling so supplier savings are only shown from real supplier-list values, with no Türkiye-average fake discounts.

## 2026-07-10

### Raw-first laptop matching cleanup

- Added shared laptop quality gates for garbage model names, generic family-only rows, and buyer-facing export identity requirements.
- Hardened MacBook repair so URL/title evidence can recover Apple/MacBook identity when grid/table text is garbage, without promoting unsupported M5-style names as Apple Silicon.
- Tightened laptop brand detection to avoid short-brand substring matches from payload noise.
- Blocked unsafe approved laptop candidates from `export_candidates`; they are returned to `needs_review` instead of creating clean model/listing rows.
- Tightened `recompute_laptop_opportunities_v2` so laptop opportunities require model + RAM + storage, model + CPU + GPU, or high-confidence exact variant identity.
- Enhanced `export_data_review` with problem filters for missing model, weak confidence, generic model, garbage model, candidate/final mismatch, and not-export-eligible rows.
- Fixed `parse_raw_listings --category laptops --reparse` so laptop-hinted rows are included along with possibly misclassified rows.
- Updated pipeline/data-model docs to mark the raw-first path as canonical and `MarketListing`/snapshot paths as legacy for v2 exports.
- Added regression tests for MacBook parsing repair, garbage model rejection, generic laptop review handling, duplicate merge behavior, laptop opportunity export gates, and phone pipeline continuity.
- Added `cleanup_laptop_listings` for dry-run-first cleanup of unsafe final laptop rows, with sqlite backup on apply and candidate-based repairs that keep repaired rows in review.
- Inspected non-phone/non-laptop rows and documented portable gaming consoles as a separate future final-listing path rather than laptop rows.
- Added `LaptopOpportunitySnapshot` and `recompute_laptop_opportunities_v2 --write-snapshots`.
- Ported the root opportunities page to clean phone/laptop snapshots.
- Ported the deals swiper/API/lazy-load flow to clean phone/laptop snapshots with legacy `DealSnapshot` fallback.
- Tightened clean deals so buyer-facing deal cards only use actionable clean snapshots: phone `buy`, laptop `buy`/`good_opportunity`; low-confidence/watch rows remain internal review/opportunity data.
- Made `merge_duplicate_laptop_models` refuse merges where normalization would drop extra identity text, then safely merged Apple casing-only duplicate model rows.
- Added raw-first `ParsedListingCandidate` admin audit buckets, raw URL links, and a bulk action to flag selected candidates for the existing AI audit workflow via `ai_notes`.
- Added `agent_review_candidates` to run the OpenCode AI audit against raw-first candidates, defaulting to phone/laptop only so accessories and unknown rows are skipped unless explicitly requested.
- Added a raw-first portable gaming console lane: `portable_console` candidates, `ConsoleModel`/`ConsoleVariant`/`ConsoleListing`, `ConsoleOpportunitySnapshot`, console parser/export support, and `recompute_console_opportunities_v1`.
- Reclassified current portable console rows into the console lane and exported 11 identity-complete Algeria console listings; console opportunities are currently zero until Türkiye comparison rows are enriched.
- Added `build_enrichment_queries` to generate prioritized Sahibinden search URLs for one-sided phone/laptop/console rows.
- Fixed `import_ouedkniss_from_cdp --query` so it builds an Ouedkniss `/s/1?keywords=...` search URL for tab selection/opening instead of only recording the query on the import run.
- Tightened Ouedkniss query tab matching so `/s/1?...` searches with different keywords do not reuse the wrong tab, and imported broader Algeria console searches for Legion Go, Steam Deck, Switch, and portable console inventory.
- Made console RAM parsing conservative so storage-only Nintendo Switch rows do not become fake `128GB RAM` variants while handheld PC RAM/storage pairs like ROG Ally X `24GB 1024GB` still parse.
- Fixed raw-first Turkish price parsing for Sahibinden console/laptop rows so `45.000 TL` is treated as 45,000 TRY and Turkish word endings like `Kutusunda` are not misread as DZD.
- Added console opportunity price sanity gates so implausible clean console prices below €100 or above €2,500 are excluded from buyer-facing snapshot math.
- Tightened laptop opportunity/enrichment eligibility so buyer-facing laptop math requires RAM+storage identity, standard storage/RAM buckets, plausible prices, and non-garbage/non-console model names.
- Removed integrated GPU noise from generated laptop enrichment queries while keeping dedicated GPUs in search terms.
- Ported the legacy buyer-offer/gain-split formula into a shared service and wired it into clean phone, laptop, and console opportunity JSON exports plus the clean deals swiper cards.

## 2026-07-09

### Fix: Ouedkniss Algeria laptop detection

- Added URL/title-based category detection in `candidate_builder.py` (`detect_category_from_signals`).
  - `/laptop-`, `/macbooks-`, `/computer-`, `/dizustu-notebook-`, `/bilgisayar-dizustu-` in URL force laptop classification.
  - `/keyboard-mouse-`, `/consoles-`, `/headphones-`, etc. in URL classify as accessory (not phone).
  - Title keywords (laptop, macbook, legion, thinkpad, etc.) override phone hint.
  - Laptop-only brands (Dell, MSI, Razer, Gigabyte) in title force laptop classification.
  - Title accessory keywords (souris, clavier, chargeur, etc.) classify as unknown.
- Updated `build_candidate` to use signal-based overrides before hint-based logic.
- Updated `parse_raw_listings` command: added `--country` filter, broadened `--reparse` to reclassify rows with wrong category hints, added diagnostic output (laptop created/updated, phone created/updated, accessory count, phone->laptop conversions).
- Bumped parser version to v2.2.
- Added 20 new tests for signal detection and candidate build overrides (all 192 tests pass).
- Fixes both Algeria/Ouedkniss and Turkiye/Sahibinden items with wrong `category_hint=phones`.

### Phase 3: Raw import commands

- Modified `import_sahibinden_from_cdp` to create `RawImportRun` and save rows to `RawListing` instead of `MarketListing`. Removed snapshot recomputation from the command. Added `--category` and `--query` options.
- Modified `import_ouedkniss_from_cdp` to create `RawImportRun` and save rows to `RawListing` instead of `MarketListing`. Removed snapshot recomputation from the command. Added `--category` and `--query` options.
- Added `save_raw_row()` functions to `sahibinden_cdp` and `ouedkniss_cdp` collectors for saving raw CDP rows into `RawListing` with full `raw_payload` preservation.
- Sahibinden `save_raw_row` preserves table cell data (processor, RAM, screen size) in `raw_payload`.
- Ouedkniss `save_raw_row` preserves card text, image, store, and price text in `raw_payload`.

### Phase 6: Import Lab review UI

- Added `/import-lab/` staff-only review page with raw listings table, parsed candidates table, import runs history, and filterable status/category/source dropdowns.
- Added `import_lab` view in `market/views.py` with stats summary and query filters for raw status, category, source type, candidate status, and candidate category.
- Added `/import-lab/candidate/<pk>/` detail page with highlighted segments, raw text, parsed fields, phone/laptop specs JSON, matched models info, and approve/reject/export buttons.
- Added batch action buttons (approve/reject/export) on candidates table with checkbox selection and JavaScript confirmation.
- Added `candidate_detail` view with segment color highlighting and raw payload inspection.

### Phase 1-2: Raw-first import pipeline and Phone/Laptop clean models

- Added `RawImportRun` model to track import/scrape sessions with source type, country, category hint, status, counters, and CDP endpoint metadata.
- Added `RawListing` model as the central raw marketplace row storage with content-hash deduplication, parse status tracking, full JSON payload, and unique constraint on source+URL.
- Added `ParsedListingCandidate` model for staging parsed data between raw imports and clean listings, with detected category, brand/model text, specs JSON, segments for UI highlighting, confidence scoring, and matched model/variant FKs.
- Added `PhoneModel`, `PhoneVariant`, `PhoneListing` for clean phone-specific listings with storage, RAM, SIM config, battery health, condition, and box status fields.
- Added `LaptopModel`, `LaptopVariant`, `LaptopListing` for clean laptop-specific listings with CPU, GPU, RAM, storage, screen size, resolution, refresh rate, and panel type fields.
- Added identity key builders: `build_phone_variant_identity()` and `build_laptop_variant_identity()` for deduplication.
- Registered all 9 new models in Django admin with list displays, filters, search, autocomplete, inline specs, and batch actions (approve/reject/reparse).
- Created `market/services/parsing/` package with segment helpers (`segments.py`), phone parser v2 (`phone_parser_v2.py`), laptop parser v2 (`laptop_parser_v2.py`), and candidate builder (`candidate_builder.py`).
- `phone_parser_v2` extracts brand, model, storage, RAM, SIM config, battery health, box status, condition, price, and currency from raw text with regex-based segment detection.
- `laptop_parser_v2` extracts brand, CPU, GPU, RAM, storage, screen size, resolution, refresh rate, panel type, condition, price, and currency from raw text.
- `candidate_builder` routes raw listings to the appropriate parser based on category hint, creates/updates `ParsedListingCandidate` with detected fields and confidence, and sets parse status.
- Created `parse_raw_listings` management command for batch parsing of raw listings with category/source-type filters and auto-approve threshold.
- Created `export_candidates` management command to export approved candidates into `PhoneListing` or `LaptopListing` with automatic model/variant creation and FK traceability back to `RawListing`.
- Created `backfill_raw_from_market_listings` management command to migrate existing `MarketListing` rows into `RawListing` with legacy ID preservation and `--dry-run` support.
- Added migration `0020_raw_pipeline_and_phone_laptop_models` with all new models, indexes, and constraints.
- Old `MarketListing`, `ProductModel`, `DeviceVariant`, and opportunity logic untouched.

### Phase 5: Migration from old data

- Backfilled 2795 existing `MarketListing` rows into `RawListing` with legacy ID preservation in `raw_payload`.
- Parsed 2611 backfilled rows into `ParsedListingCandidate` records; 1648 need review, 2 auto-qualified above 95% confidence.
- Fixed `candidate_builder` brand matching to avoid unsupported JSON `contains` lookup on SQLite.
- Fixed 61 oversized `price_original` values that exceeded `DecimalField(max_digits=12)` constraint.

### Phase 7: Export to clean models

- Exported 510 approved phone candidates into `PhoneListing` with automatic `PhoneModel`/`PhoneVariant` creation and FK traceability to `RawListing`.
- Exported 139 approved laptop candidates into `LaptopListing` with automatic `LaptopModel`/`LaptopVariant` creation and FK traceability to `RawListing`.

### Phase 1: Raw pipeline tests

- Added 67 tests covering RawListing content-hash dedup, unique constraints, phone/laptop parsers, candidate builder, identity keys, parse/export/backfill management commands, and segment helpers.

## 2026-07-08

- Added `ListingConditionAudit` model with condition_class, verdict, confidence, red_flags, vision fields, and admin registration.
- Added `classify_condition_class()` and `save_condition_audit()` to deal_sanity for automated condition classification.
- Added `--write` flag to audit_deals_with_llm to persist ListingConditionAudit records.
- Added `--require-clean-condition` flag to run_opportunity_analysis and recompute_deal_snapshots.
- Added condition badge (Turkish label) and filter pills to deals swiper UI.
- Optimized deal queries with select_related for condition_audit.


## 2026-07-07

- Added generic typed catalog/spec system for multi-device support: `ProductType`, `SpecDefinition`, `SpecOption`, `ProductVariantSpecValue`, `MarketListingSpecValue` models with admin registration and inlines.
- Added nullable `product_type` FK to `ProductModel` for linking models to device types.
- Added `market.services.catalog` module with helpers: `get_or_create_product_type`, `get_spec_definition`, `normalize_spec_value`, `upsert_variant_spec_value`, `upsert_listing_spec_value`, `build_variant_identity_from_specs`, batch upsert helpers, and spec value readers.
- Added `seed_product_types_and_specs` idempotent management command seeding phone, laptop, tablet, console, vr_headset, and camera product types with their spec definitions and common option values.
- Added `inspect_catalog_specs` management command to inspect catalog spec system state.
- Added 8 tests covering product type creation, spec definition creation, idempotent seeding, listing/variant spec value saving, laptop identity key building, existing phone variant behavior, opportunity analysis compatibility, and laptop listing storage without laptop-specific columns.
- Updated `docs/DATA_MODEL.md` and `docs/PIPELINE.md` with catalog spec system documentation.

### Phase 2: Pipeline Integration

- Added `market.services.spec_extraction` module with `detect_product_type()`, `extract_laptop_specs()`, `extract_phone_specs()`, `extract_specs_from_text()`, and `extract_specs_from_listing()` returning `ParsedListing`.
- Added `market.services.listing_matching` module with progressive matching, `MatchResult`, `match_listing_to_catalog()`, and `apply_match_to_listing()`.
- Hooked spec extraction into all collectors: `ouedkniss_cdp.py`, `sahibinden_cdp.py`, `import_sahibinden_laptops_from_cdp.py`, `process_ocr_queue.py`, and `listing_suggestions.py`.
- Added `backfill_product_types` management command to set `product_type` on existing models from category/name heuristic.
- Added `parse_listing_text` management command for manual extraction testing.
- Added 27 new tests covering product type detection, laptop spec extraction (RAM/SSD/GPU/CPU/refresh rate), MacBook M-series, incomplete listing confidence, listing matching (exact/high/low), conflicting specs blocking, phone backward compatibility, backfill idempotency, opportunity analysis compatibility, and spec extraction integration.

### Phase 3: Match Quality and Confidence Gates

- Added `match_level`, `match_confidence`, and `match_reason` fields to `MarketListing` for tracking match quality.
- Added confidence gate constants: `OPPORTUNITY_ELIGIBLE_MATCH_LEVELS`, `MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY`, `ALLOW_MODEL_ONLY_OPPORTUNITIES`.
- Updated `apply_match_to_listing()` to persist match level, confidence, and reason on each listing.
- Updated `run_analysis()` to filter listings by match level — phones always eligible, laptops must have eligible match level and sufficient confidence.
- Added `inspect_listing_matches` management command for reviewing match quality distribution and opportunity eligibility.
- Added `recompute_listing_matches` management command with `--dry-run` support for safe recomputation.
- Updated `MarketListingAdmin` with new columns (match level badge, eligibility badge, product type) and filters (match level, product type).
- Added 16 new tests covering match level fields, confidence gates, opportunity filtering (phone included, unmatched/exact/conflict/model-only laptop excluded), apply_match persistence, laptop title fixtures, recompute dry-run, and inspect output.
- Updated `docs/DATA_MODEL.md`, `docs/PIPELINE.md`, and `README.md` with Phase 3 documentation.

## 2026-07-09

- Added `fetch_exchange_rates`, a Django management command that saves fresh `CurrencyRate` rows for EUR/TRY, EUR/USD, derived USD/TRY, and a configured Algeria black-market EUR/DZD benchmark, with optional opportunity/deal snapshot recomputation.
- Added `FX_RATE_ENDPOINT`, `FX_RATE_SOURCE`, and `FX_RATE_MAX_AGE_DAYS` settings plus tests covering DB-backed currency helper usage.

## 2026-07-05

- Added `match_instagram_manual_links_from_markdown` and used it to replace exact suffix-matched manual Instagram image links with real post/reel URLs from the Markdown profile export.
- Pointed manual Instagram OCR listing links at their local `/media/` evidence images instead of synthetic Instagram `manual_image` URLs.
- Displayed the current effective FX rates used by calculations in the shared UI header, including EUR/TRY, USD/TRY, EUR/DZD, and TRY-derived EUR/USD.
- Added a supplier-list pricing rule: reserve a USD 100 buyer discount versus supplier, then split the remaining supplier-to-Algeria spread 50/50 between buyer gain and internal gain.
- Replaced direct EUR/USD FX usage with TRY-anchored EUR/TRY and USD/TRY conversion, recalculated supplier EUR prices, and regenerated deal-analysis JSON exports using raw supplier USD as the benchmark.
- Cleaned up opportunity detail listing cards with aligned price blocks and explicit original-listing links that open the source URL.
- Fixed OCR parsing to extract storage from full multi-line Instagram OCR text, then backfilled NVIDIA Instagram listings from `description_raw`.
- Opened opportunity details in an in-page modal from the opportunities list and broadened laptop detail matching so Turkey laptop listings appear for cross-spec laptop opportunities.
- Hid internal gain, buy-side pricing, supplier spread, and raw margin details from non-superuser buyer views while keeping superusers on the full internal opportunity view.
- Fixed the internal language switcher to persist Django's locale cookie, preserve filtered page query strings, and render the active HTML language.
- Added capital ROI and clearer buyer-gain percentage labels to opportunity list and detail screens without changing the current gain-split logic.
- Added an absolute gross-spread floor so opportunities with at least EUR 150 gross spread are treated as at least medium quality even when buyer gain percent is low.
- Fixed dashboard CSS serving by linking templates to the compiled Tailwind bundle and adding DEBUG-only static asset serving.
- Added optional Django Debug Toolbar integration, gated to DEBUG and authenticated superusers only.
- Added optional `OCR_BACKEND=nvidia` support for NVIDIA NIM vision chat completions using `NVIDIA_API_KEY`, `NVIDIA_VISION_ENDPOINT`, and `NVIDIA_VISION_MODEL`.
- Added `queue_instagram_image_folder` for manually downloaded Instagram image folders and a `process_ocr_queue --source-username` filter so OCR can be run against one Instagram source at a time.
- Added a computed opportunity gain split that suggests my gain, buyer price, buyer gain, buyer gain percent, DZD display values, and deal quality without adding new database tables or stored fields.
- Replaced the inline dashboard CSS with a Tailwind build, added responsive light/dark dashboard components, and refactored opportunities, listings, opportunity detail, data quality, sources, and inline edit toolbar templates for mobile-first review workflows.
- Added EUR, USD, TRY, and DZD converted price displays to listing review cards/tables and opportunity detail listing cards while preserving editable original prices.
- Included imported supplier text-file prices in the Listings review page as read-only provider rows with supplier filtering support.
- Normalized unknown-storage iPhone 16 family listing buckets to 128GB variants and rebuilt opportunity snapshots.
- Added a filtered Data Quality review queue for listings needing cleanup, with inline-edit-ready title, price, condition, status, product, and variant fields.
- Added normalized storage/SIM fields to listings, supplier prices, and opportunity snapshots; moved opportunity matching to product model plus storage/SIM buckets and stopped importers from creating new product model or variant rows during ingestion.
- Added collapsible bulk storage tools to the Data Quality review queue, including row selection, quick storage assignment, and bulk delete for staff users.
- Added a staff-reviewed listing suggestion workflow: `suggest_listing_fixes` proposes existing product models, storage, SIM, and condition fixes from stored listing text or matching user-opened CDP pages, Data Quality shows pending suggestions, and staff can bulk apply or reject them.
- Added `agent_review_listings`, a separate OpenCode-powered review mode that launches the local OpenCode agent per listing, asks it to inspect the URL or infer from similar priced database rows, validates the returned JSON decision, and directly applies model/storage/SIM/condition/status edits to the database.
- Cleared the listing review queue: ran the OpenCode bulk review pass, finalized remaining rows with explicit parsing and same-model price-band storage inference, rejected non-phone/no-price rows, and rebuilt opportunity snapshots.
- Refactored `/opportunities/` from a dashboard alias into a standalone filtered/sortable page with recommendation tab bar, min-confidence/min-margin sliders, and sort-by-gross/margin/confidence/date.
- Extracted `build_opportunity_rows()` helper shared between dashboard and opportunities views.
- Added `.opp-tab-row`, `.opp-tab`, `.opp-filter-grid` CSS components and migrated dashboard tab-bar to use the new class-based styling.
- Added per-source tab bar (All / Instagram / Ouedkniss / Supplier) to the opportunities page with on-the-fly margin recomputation for Algeria source-specific views.
- Added `_compute_source_rows()` helper that computes opportunity rows directly from MarketListing per Algeria source type, preserving the same row shape as snapshot-based rows.
- Made `/` the root opportunities page; `/listings/`, `/data-quality/`, `/sources/` now require `@staff_member_required` and redirect anonymous users to `/admin/login/`.
- Set `LOGIN_URL = /admin/login/` in settings.

## 2026-07-04

- Added the local Tailscale/LAN host `100.89.48.48` to the default Django `ALLOWED_HOSTS` and normalized comma-separated host configuration.
- Added `ProductAsset` model for storing external visual assets (logos, product images) separately from `ProductModel`, with Commons metadata, licensing, match scoring, and admin registration.
- Added `market.services.commons` module for Wikimedia Commons MediaWiki API integration: file search, imageinfo metadata, file download, candidate scoring, query generation, and series fallback logic.
- Added `sync_commons_assets` management command to automatically search Commons for model/series logos, rank candidates, download files, and produce a sync report. Supports `--dry-run`, `--min-score`, `--save-weak`, `--force`, `--brand`, `--model-id`, `--limit`, and `--verbose`.
- Created `docs/ASSETS.md` documenting asset fallback strategy, sync command usage, manual review workflow, and legal notes.
- Updated AGENTS.md with notes on ProductAsset storage, Commons API usage, and missing-logo handling.
- Added generic electronics market models, admin registration, parsers, collectors, OCR queue processing, supplier import, opportunity analysis, and minimal inspection pages.
- Added setup docs, pipeline docs, data model docs, environment example, and parser tests.
- Added Netscape-format Instagram cookie file support for Instaloader collection via `INSTAGRAM_COOKIE_FILE`.
- Reworked `scripts/imageye_download_images.py` into a CDP-based Instagram profile image downloader limited by `--limit`.
- Added `harvest_instagram_profile_page` to save visible Instagram profile-page reel/post URLs into `InstagramPost` records.
- Added an optional Tesseract OCR backend for processing saved Instagram thumbnails without PaddleOCR/EasyOCR.
- Improved OCR parsing for Instagram price boxes, phone-number avoidance, RAM/storage pairs, and reviewable non-device thumbnails.
- Added `--offset` support for CDP Instagram profile harvesting so later visible listings can be collected in batches.
- Added an optional EasyOCR backend path with Tesseract fallback when EasyOCR/PyTorch dependencies are unavailable.
- Added optional OCR.space backend using `OCR_SPACE_API_KEY`, `OCR_SPACE_LANGUAGE`, and `OCR_SPACE_ENGINE`.
- Added `harvest_and_process_instagram_profile` to collect offset batches via CDP and OCR only newly queued posts.
- Improved CDP profile harvesting with deeper scroll support for larger offset batches.
- Implemented Sahibinden CDP table import from a user-opened Chrome tab into Türkiye `MarketListing` rows.
- Added Ouedkniss source and 6 Algeria listings (S26 Ultra x2, S24 Ultra, Honor Magic 7 Pro, Google Pixel 7 Pro, Oneplus 15) with new brands Honor, Google, OnePlus.
- Downloaded missing-price Instagram reels with `yt-dlp`, extracted review frames, and filled 7 Algeria listing prices from OCR.space frame OCR.
- Improved OCR price parsing to prefer explicit `da/dzd` prices over barcode-like numbers such as `1000000`.
- Fixed Sahibinden TRY parsing for Turkish thousands/decimal formats, repaired 6 inflated prices, improved storage and condition parsing, marked suspicious Sahibinden rows for review, and backfilled raw listing titles.
- Added CDP detail-page enrichment for Sahibinden listings and used it to fill `Depolama Kapasitesi 256 GB` on listing 1325663091.
- Corrected opportunity analysis direction to buy from Algeria and sell in Türkiye using Sahibinden average EUR minus Algeria minimum EUR, then generated fresh snapshots.
- Added Ouedkniss as a separate source type with a Chrome CDP card importer, imported 12 visible Algeria Samsung listings, and documented that Algeria comparisons can include Instagram, Ouedkniss, or both.
- Imported 9 KABA STORE Ouedkniss mobile listings and improved Ouedkniss model cleanup for RAM/storage patterns like `12/256G`.
- Fixed Ouedkniss CDP collection to accumulate virtualized cards across scroll positions; KABA STORE now has 21 imported mobile listings.
- Imported 24 Moutcha Phone Ouedkniss listings and fixed Ouedkniss price fallback for rows where storage and price appear adjacent.
- Imported Moutcha Phone page 2 and Abdou Cabba Store Ouedkniss listings; improved Ouedkniss cleanup for reversed capacity pairs and inline RAM/storage tokens.
- Added a default 30-day freshness cutoff to Ouedkniss CDP imports, made duplicate Ouedkniss tab selection prefer the tab with the most visible cards, and imported 24 current Abdou Cabba listings.
- Imported Abdou Cabba Store Ouedkniss page 2 with the 30-day freshness cutoff, bringing Abdou Cabba to 48 stored listings.
- Imported Abdou Cabba Store Ouedkniss page 3 with the 30-day freshness cutoff, bringing Abdou Cabba to 72 stored listings.
- Replaced ad hoc brand guessing with an explicit electronics brand/alias list, backfilled existing product models, and cleaned Algeria brand grouping for Ouedkniss data.
- Imported 50 Xiaomi/Redmi/Poco Sahibinden Türkiye listings from the user-opened CDP tab.
- Imported/updated 100 more Xiaomi/Redmi/Poco Sahibinden Türkiye rows across 2 result pages.
- Reran opportunity analysis after the expanded Xiaomi Sahibinden import; latest batch produced 271 snapshots with 14 exact Algeria-to-Türkiye margin comparisons.
- Added explicit storage choices for variants and included 1024GB alongside 64GB, 128GB, 256GB, and 512GB.
- Normalized Samsung model names to remove Samsung/Samasung prefixes and compare opportunities by product model plus storage bucket instead of exact RAM/SIM variant.
- Updated the Ouedkniss CDP importer to print created, updated, and unchanged rows, including old/new field values for material updates.
- Reworked Ouedkniss search extraction to read all `v-col-sm-6 v-col-md-4 v-col-lg-3 v-col-12` containers, save only rows with DZD prices, and print dropped no-price rows.
- Cleaned Ouedkniss data by deleting no-price and blank-title listings, tightened Samsung canonical model cleanup, and reran opportunity analysis on the cleaned data.
- Improved Ouedkniss CDP import so `--target-url` can open missing pages, waits longer for hydration, retries empty extraction, suppresses CDP websocket origin issues, and uses the broader `v-col` card selector.
- Fixed Ouedkniss target matching to prefer exact URLs over broad substrings, then imported Abdou Cabba Store pages 1 and 2 with the improved extractor.
- Imported additional Ouedkniss stores: Moutcha Phone, KABA Store mobiles, FreeMobile, and Apple Store Mobile; logged dropped no-price rows and confirmed no Ouedkniss no-price rows remain.
- Tested raw `requests` against Ouedkniss and confirmed listings are not server-rendered; improved CDP extraction with adaptive scrolling and higher default scroll budget for lazy-loaded store pages.
- Installed BeautifulSoup, lxml, Playwright, Selenium, and Scrapy into the project environment for deeper Ouedkniss extraction experiments.
- Tested Playwright over the existing Chrome CDP session plus BeautifulSoup parsing of rendered Ouedkniss DOM; confirmed browser-rendered extraction sees priced rows while raw `requests` does not.
- Verified Abdou Cabba page 1 against a rendered clipping and imported the missing SOLANA Phone SAGA listing.
- Added normalized `DeviceVariant` identity keys, deduplicated equivalent variant rows while preserving listing/price/snapshot references, and enforced per-model variant uniqueness.
- Fixed `run_opportunity_analysis` so supplier rows and confidence scoring work when rebuilding Algeria-to-Türkiye opportunity snapshots.
- Changed opportunity analysis to atomically replace old snapshots so the database keeps only the newest comparison batch.
- Imported the 2026-07-04 Türkiye USD supplier list, improved supplier parsing for dotted USD thousands and `/1` SIM-like capacity suffixes, and made supplier imports idempotent.
- Ported the Web-Prototype dashboard shell into Django templates with live opportunities, listings review, data quality, and sources screens.
- Aggregated opportunity dashboard coverage badges by source with counts instead of rendering one badge per underlying listing.
- Repaired three stale Instagram OCR listings where bare `1000000` barcode artifacts were treated as DZD prices, moved them to review, and rebuilt opportunity snapshots.
- Added clickable opportunity rows that open a model/storage detail page with Algeria and Turkiye listings displayed side by side.
- Normalized `1sim` variants into empty/default SIM variants, merged duplicate variant rows, and rebuilt opportunity snapshots.
- Tightened Ouedkniss storage/SIM parsing with explicit approved storage buckets, `1000GB`/`1TB` normalization to `1024GB`, and direct parser coverage for `2SIM`, `duos`, and unsupported capacity typos.
- Re-imported KABA STORE mobiles from Ouedkniss with the tightened parser: 21 priced rows saved, including 13 new rows and 8 image URL updates, with storage/SIM columns verified.
- Tightened the Ouedkniss CDP command so it defaults to user-opened tabs, reports CDP failures as command errors, and normalizes Obsidian-extracted relative listing URLs before saving.
- Updated Obsidian Ouedkniss parsing to accept current search-result listing URLs ending in `-d...`, not only legacy `/annonce/` links.
- Made Obsidian Ouedkniss extraction fall back from clipped `content` to `fullHtml` when Web Clipper omits rendered listing cards from the cleaned content payload.
