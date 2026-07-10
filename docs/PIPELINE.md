# PriceBridge Pipeline

PriceBridge is a market-intelligence and matching system. It is not an
ecommerce store. The current migration target is a raw-first pipeline:

`RawListing -> ParsedListingCandidate -> PhoneListing/LaptopListing/ConsoleListing -> v2 exports`

## Canonical Raw-First Path

### 1. Raw Listing

`RawListing` stores the source truth from public/profile collection, user-opened
Chrome CDP marketplace tabs, supplier imports, or legacy backfills. Keep raw
title, URL, price text, source/country/category hint, and full `raw_payload`.

Do not overwrite raw evidence with parser guesses.

### 2. Parsed Listing Candidate

`ParsedListingCandidate` stores parser output and review state. It links one-to-one
to `RawListing` and carries:

- detected category: phone, laptop, accessory, or unknown
- parsed brand/model/variant text
- normalized price fields
- `phone_specs_json` or `laptop_specs_json`
- parser confidence, status, review notes, and matched clean model/variant FKs

Laptop candidates must stay `needs_review` when the identity is incomplete or
unsafe. In particular, garbage model names such as `gpu ram gb storage gb`,
`ram gb storage`, `cell ram`, and `price currency` are not export-safe.

Generic laptop family names such as `Legion`, `ThinkPad`, `Latitude`, `TUF`,
`ROG`, `MacBook Air`, or `MacBook Pro` are review-only unless the row has enough
variant identity.

### 3. Clean Final Listings

`PhoneListing`, `LaptopListing`, and `ConsoleListing` are the normalized final
listing tables for the raw-first pipeline. They preserve source URL and raw FK
traceability.

`PhoneModel` / `PhoneVariant` are clean phone catalog rows.
`LaptopModel` / `LaptopVariant` are clean laptop catalog rows.
`ConsoleModel` / `ConsoleVariant` are clean portable gaming console catalog rows.

Laptop buyer-facing exports require one of:

- model + RAM + storage
- model + CPU + GPU
- an explicit high-confidence exact variant match

Loose model-only laptop matches should remain low-confidence review data and
must not be promoted into buyer-facing opportunity exports.

## Current Commands

- `parse_raw_listings` parses `RawListing` into `ParsedListingCandidate`.
- `export_candidates` exports approved safe candidates into `PhoneListing` or
  `LaptopListing`.
- `export_data_review` creates a local HTML review report for raw, candidate,
  and final rows.
- `merge_duplicate_phone_models` and `merge_duplicate_laptop_models` safely
  merge obvious duplicate clean model rows, dry-run by default.
- `recompute_phone_opportunities_v2` computes phone opportunities from
  `PhoneListing`.
- `recompute_laptop_opportunities_v2` computes laptop opportunities from
  `LaptopListing`, applies strict laptop identity gates, and can write
  `LaptopOpportunitySnapshot` with `--write-snapshots`.
- `recompute_console_opportunities_v1` computes portable console opportunities
  from `ConsoleListing`.
- `build_enrichment_queries` prints targeted Sahibinden search URLs for
  one-sided phone/laptop/console rows that need Türkiye comparison data.
- The root opportunities page reads clean phone/laptop opportunity snapshots.
- The deals swiper reads clean phone/laptop snapshots first and falls back to
  legacy `DealSnapshot` only when no clean snapshots exist.
- Buyer-facing deal cards are stricter than the internal opportunities table:
  phone snapshots must be `buy`, and laptop snapshots must be `buy` or
  `good_opportunity`. Low-confidence/watch/marginal rows stay internal.

## Legacy / Deprecated Path

`MarketListing`, `ProductModel`, `DeviceVariant`, `MarketListingSpecValue`,
`OpportunitySnapshot`, and `DealSnapshot` are legacy/generic pipeline tables.
They still contain useful historical data. `DealSnapshot` remains as a fallback
for the deals swiper only when clean snapshots have not been generated, but it
is not the canonical path for raw-first phone/laptop exports.

Treat these commands as deprecated for the v2 laptop pipeline unless explicitly
doing old-data migration or historical analysis:

- `run_opportunity_analysis`
- `recompute_deal_snapshots`
- `finalize_review_queue`
- `recompute_listing_matches`
- commands that write new rows directly to `MarketListing`

Do not delete legacy data blindly. Retire usage by removing these tables from
new exports first, then migrate or archive only after tests and usage search
prove a path is unused.

## Review Workflow

Use `export_data_review` to inspect raw/candidate/final mismatches:

```bash
python manage.py export_data_review --category laptop --limit 500
python manage.py export_data_review --q macbook --limit 300 --output exports/review_macbook.html
python manage.py export_data_review --category laptop --problem garbage_model
python manage.py export_data_review --category laptop --problem not_export_eligible
```

The report includes raw title, URL, raw text, candidate fields, extracted specs,
final listing fields, mismatch badges, and source/country/category filters.

Review-only rows should be triaged in Django admin, not deleted or ignored.
`ParsedListingCandidate` admin now exposes AI audit buckets for missing model,
weak confidence, generic laptop family, garbage model, not-export-eligible
laptop rows, and non-phone/non-laptop rows. Use the bulk action to flag selected
candidates for AI audit; the marker is stored in `ai_notes` and the raw evidence
remains linked through `RawListing`.

Run AI audit on the flagged raw-first queue with:

```bash
python manage.py agent_review_candidates --flagged-only --limit 20
python manage.py agent_review_candidates --bucket not_export_eligible --categories laptop --limit 20
python manage.py agent_review_candidates --bucket missing_model --categories phone,laptop --limit 20
```

By default `agent_review_candidates` only considers phone/laptop candidates.
Accessories and unknown rows are skipped unless `--categories all` or
`--bucket non_phone_laptop` is passed explicitly.

## Portable Gaming Consoles

Rows such as ASUS ROG Ally, Lenovo Legion Go, Steam Deck, MSI Claw, Nintendo
Switch, Xbox Ally, and PlayStation Portal must not be forced into
`LaptopListing`. They now use:

`RawListing -> ParsedListingCandidate(portable_console) -> ConsoleListing -> ConsoleOpportunitySnapshot`

Console exports require model plus storage, or model plus chipset/RAM, or an
explicit high-confidence variant match. Accessories such as cases, chargers,
docks, keyboards, mice, bags, and replacement screens stay out of opportunity
exports unless a separate accessory resale workflow is explicitly added.

Use enrichment queries to fill missing Türkiye comparisons:

```bash
python manage.py build_enrichment_queries --category consoles --limit 20
python manage.py import_sahibinden_from_cdp --category consoles --query "ASUS ROG Ally X 24GB 1024GB"
python manage.py parse_raw_listings --category consoles --country turkiye --reparse --limit 500
python manage.py export_candidates --category consoles --status pending --limit 500
python manage.py recompute_console_opportunities_v1 --write-snapshots
```
