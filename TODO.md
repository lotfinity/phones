Phase 0 — Preparation
[x] Add architecture note to AGENTS.md
[x] Add TODO.md and CHANGELOG.md
[x] Confirm old pages still work before model refactor

Phase 1 — Raw pipeline models
[x] Add RawImportRun
[x] Add RawListing
[x] Add ParsedListingCandidate
[x] Add migrations
[x] Register models in admin
[x] Add tests for raw listing dedupe

Phase 2 — Phone/Laptop clean models
[x] Add PhoneModel
[x] Add PhoneVariant
[x] Add PhoneListing
[x] Add LaptopModel
[x] Add LaptopVariant
[x] Add LaptopListing
[x] Add migrations
[x] Register models in admin

Phase 3 — Raw import commands
[x] Modify Sahibinden CDP import to save RawListing only
[x] Modify Ouedkniss CDP import to save RawListing only
[x] Remove snapshot recompute from raw import commands
[x] Preserve full CDP row in raw_payload

Phase 4 — Parsers
[x] Add segment helper
[x] Add phone_parser_v2
[x] Add laptop_parser_v2
[x] Add candidate_builder
[x] Add parse_raw_listings command

Phase 5 — Migration from old data
[x] Add backfill_raw_from_market_listings command
[x] Backfill old MarketListing rows into RawListing
[x] Parse backfilled rows into candidates
[x] Do not delete old data

Phase 6 — Review UI
[x] Add /import-lab/
[x] Show raw listings
[x] Show parsed candidate
[x] Highlight detected segments
[x] Allow manual correction (via candidate detail)
[x] Allow approve/reject/export (batch + single)

Phase 7 — Export
[x] Add export_candidates command
[x] Export approved phones to PhoneListing
[x] Export approved laptops to LaptopListing
[x] Keep FK to RawListing

Phase 8 — Opportunity rewrite later
[ ] Create phone opportunity snapshots
[ ] Create laptop opportunity snapshots
[ ] Move pages away from old MarketListing
