# Pipeline

Supplier list:
`import_supplier_list` reads rough WhatsApp-style rows, stores raw text, extracts model/storage/RAM/USD price, creates or matches product records, and writes `SupplierPrice`.

Instagram:
`crawl_instagram_profile` uses Instaloader against public profiles, stores `InstagramPost`, captions, metadata, and media paths, then marks posts with media as needing OCR.

Browser fallback:
`harvest_instagram_profile_page` attaches to Chrome CDP, reads visible profile-grid post/reel URLs from the actual profile page, stores them as `InstagramPost`, and can download the visible thumbnails. This preserves the relationship needed later: device evidence -> reel/post URL.

Combined batch:
`harvest_and_process_instagram_profile` wraps the CDP harvest and OCR queue for offset/limit batches, avoiding already-processed posts by relying on `needs_ocr` and `ocr_processed`.

OCR:
`process_ocr_queue` runs the configured OCR backend. The default dummy backend returns empty text so the app still runs without OCR dependencies. Parsed caption plus OCR text creates `OCRResult` and, when enough data exists, a reviewable `MarketListing`.

Analysis:
`run_opportunity_analysis` compares Algeria buy-side `MarketListing` prices with Türkiye Sahibinden sell-side prices and writes `OpportunitySnapshot` records. Instagram and Ouedkniss both feed Algeria listings but keep separate `source_type` values so later comparison views can include Instagram only, Ouedkniss only, or both. Confidence is a simple heuristic based on listing count, Sahibinden count, supplier count, and variant specificity.

Sahibinden:
`import_sahibinden_from_cdp` attaches to a user-opened Chrome CDP session, reads Sahibinden search-result table rows, paginates by `pagingOffset`, and creates Türkiye `MarketListing` rows with model, title, TRY price, date/place metadata, thumbnail URL, and listing URL.

Ouedkniss:
`import_ouedkniss_from_cdp` attaches to a user-opened Ouedkniss search page through Chrome CDP, reads visible listing cards, and creates Algeria `MarketListing` rows with `source_type=ouedkniss`, DZD price, title, store metadata, image URL, and listing URL.

## Catalog Spec System

`seed_product_types_and_specs` idempotently seeds product types (phone, laptop, tablet, console, vr_headset, camera) and their spec definitions (storage, RAM, CPU, GPU, screen size, etc.).

`inspect_catalog_specs` prints product types, spec counts, sample definitions, and listing/variant spec value counts.

`backfill_product_types` sets `product_type` on existing `ProductModel` rows using category/name heuristic.

`parse_listing_text` manually tests extraction on arbitrary text.

Spec values are stored in `ProductVariantSpecValue` (canonical variant specs) and `MarketListingSpecValue` (observed listing specs). The `market.services.catalog` module provides helpers for normalizing, upserting, and querying spec values.

## Pipeline Integration

Spec extraction runs at listing creation in all collectors: `ouedkniss_cdp`, `sahibinden_cdp`, `import_sahibinden_laptops_from_cdp`, and `process_ocr_queue`. The flow is: raw text → `detect_product_type()` → `extract_specs_from_text()` → `upsert_listing_specs_from_dict()`.

`listing_matching.py` matches listings to product models using progressive matching with identity weights: gpu_model(10) > cpu_model(8) > ram_gb(6) > ssd_gb(5) > screen_inches(4) > refresh_hz(3). Confidence gates: exact≥20, high≥12, medium≥5. Conflicting specs block matching.

`apply_match_to_listing()` persists `match_level`, `match_confidence`, and `match_reason` on each listing.

## Match Quality and Opportunity Filtering

`run_opportunity_analysis` filters listings by match quality before creating snapshots:

1. **Phones and unknown types**: always eligible (backward compatible).
2. **Laptops and typed listings**: must have `match_level` in `OPPORTUNITY_ELIGIBLE_MATCH_LEVELS` (`exact_variant`, `strong_candidate`) and `match_confidence ≥ 0.70`.
3. **Excluded**: `unmatched`, `conflict`, and `model_only` (unless `ALLOW_MODEL_ONLY_OPPORTUNITIES=True`).

Use `inspect_listing_matches` to review match quality distribution. Use `recompute_listing_matches --dry-run` to preview recomputation without writing.
