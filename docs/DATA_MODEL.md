# Data Model

`Category`, `Brand`, `ProductModel`, and `DeviceVariant` describe the legacy generic electronics catalog. They remain in the database for historical data and old dashboards.

The canonical raw-first phone/laptop path now uses:

- `RawListing` for source evidence.
- `ParsedListingCandidate` for parser output and review state.
- `PhoneModel` / `PhoneVariant` / `PhoneListing` for normalized phone rows.
- `LaptopModel` / `LaptopVariant` / `LaptopListing` for normalized laptop rows.

`MarketListing`, `OpportunitySnapshot`, and `DealSnapshot` are legacy for the v2 phone/laptop opportunity pipeline. Do not write new buyer-facing laptop exports from them.

Laptop opportunity exports must only use specific identities: model + RAM + storage, model + CPU + GPU, or an explicit high-confidence variant match. Garbage/spec-fragment model names and generic family-only rows stay review data.

Clean opportunity snapshots:

- `PhoneOpportunitySnapshot` stores `PhoneListing`-based opportunity rows.
- `LaptopOpportunitySnapshot` stores `LaptopListing`-based opportunity rows.
- The root opportunities page reads these clean snapshots.
- The deals swiper reads clean snapshots first and falls back to legacy `DealSnapshot` only when clean snapshots are empty.
- Clean deal cards are buyer-facing and therefore filter snapshots to actionable
  recommendations only: phone `buy`, laptop `buy` or `good_opportunity`.

`ProductModel` has a nullable `product_type` FK linking it to a `ProductType` (phone, laptop, tablet, console, vr_headset, camera).

## Generic Spec System

A typed spec system supports different device types without adding one-off columns to `MarketListing`.

`ProductType` defines a device category (phone, laptop, tablet, console, vr_headset, camera).

`SpecDefinition` defines allowed specs per product type. Each spec has a key, label, value type (text/integer/decimal/boolean/option/multi_option), unit, and flags: `is_variant_identity`, `is_listing_level`, `is_filterable`, `is_comparable`.

`SpecOption` provides normalized dropdown choices for option-type specs (e.g., "RTX 4060", "Intel Core i7-13700H").

`ProductVariantSpecValue` stores canonical specs on a `DeviceVariant`. Used for identity matching and filtering.

`MarketListingSpecValue` stores observed/extracted specs on a `MarketListing`. Supports confidence scores for OCR-extracted values.

Existing phone fields (`storage_gb`, `sim_config`, `battery_health`, etc.) remain on `DeviceVariant` and `MarketListing` for backward compatibility. New device types use the spec system exclusively.

## Data Collection

`Source` identifies where data came from: Instagram, supplier lists, Sahibinden, or manual entry.

`InstagramPost` stores collected public post metadata, captions, and local media paths. `OCRResult` stores extracted image text and review fields.

`SupplierPrice` stores raw supplier rows plus parsed model, variant, USD price, optional EUR price, confidence, and active state.

## Market Data

`MarketListing` is the generic observed market listing table. It stores Algeria Instagram listings and Türkiye Sahibinden/Ouedkniss listings.

Each listing tracks match quality via:
- `match_level` -- one of: `exact_variant`, `strong_candidate`, `model_only`, `unmatched`, `conflict`
- `match_confidence` -- float 0.0–1.0, how confident the matching service is
- `match_reason` -- human-readable explanation of why this level was assigned

`CurrencyRate` is available for manually recording observed FX rates.

## Analysis

`OpportunitySnapshot` records point-in-time analysis using Algeria prices, supplier prices, optional future Sahibinden averages, simple margins, confidence, and recommendation.

`DealSnapshot` caches deal data for fast swiper page loads.

### Confidence Gates

Opportunity analysis filters listings by match quality. Only listings with eligible match levels and sufficient confidence are used:

- `exact_variant` + confidence ≥ 0.70 → eligible
- `strong_candidate` + confidence ≥ 0.70 → eligible
- `model_only` → excluded by default (configurable via `ALLOW_MODEL_ONLY_OPPORTUNITIES`)
- `unmatched` → excluded
- `conflict` → excluded

Phone listings and listings without a product type are always eligible (backward compatible).

## Commands

- `seed_product_types_and_specs` -- idempotent seeding of product types and spec definitions
- `inspect_catalog_specs` -- prints catalog spec system state
- `backfill_product_types` -- sets `product_type` on existing models from category/name heuristic
- `parse_listing_text` -- manual extraction testing command
- `inspect_listing_matches` -- inspect listing match quality and opportunity eligibility
- `recompute_listing_matches` -- re-run extraction/matching for selected listings (supports `--dry-run`)

## Services

- `market.services.catalog` -- helpers for `ProductType`, `SpecDefinition`, `SpecOption`, `ProductVariantSpecValue`, `MarketListingSpecValue` CRUD and batch operations
- `market.services.spec_extraction` -- product type detection, spec extraction from text, `ParsedListing` interface
- `market.services.listing_matching` -- progressive matching with laptop identity weights and conflict detection
