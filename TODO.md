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
[ ] Add tests for raw listing dedupe

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
[ ] Modify Sahibinden CDP import to save RawListing only
[ ] Modify Ouedkniss CDP import to save RawListing only
[ ] Remove snapshot recompute from raw import commands
[ ] Preserve full CDP row in raw_payload

Phase 4 — Parsers
[x] Add segment helper
[x] Add phone_parser_v2
[x] Add laptop_parser_v2
[x] Add candidate_builder
[x] Add parse_raw_listings command

Phase 5 — Migration from old data
[x] Add backfill_raw_from_market_listings command
[ ] Backfill old MarketListing rows into RawListing
[ ] Parse backfilled rows into candidates
[ ] Do not delete old data

Phase 6 — Review UI
[ ] Add /admin/import-lab/
[ ] Show raw listings
[ ] Show parsed candidate
[ ] Highlight detected segments
[ ] Allow manual correction
[ ] Allow approve/reject/export

Phase 7 — Export
[x] Add export_candidates command
[ ] Export approved phones to PhoneListing
[ ] Export approved laptops to LaptopListing
[ ] Keep FK to RawListing

Phase 8 — Opportunity rewrite later
[ ] Create phone opportunity snapshots
[ ] Create laptop opportunity snapshots
[ ] Move pages away from old MarketListing
