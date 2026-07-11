# PriceBridge TODO

## Completed foundation

### Phase 0 — Preparation
- [x] Add architecture notes to `AGENTS.md`
- [x] Add `TODO.md` and `CHANGELOG.md`
- [x] Confirm legacy pages still work before model refactor

### Phase 1 — Raw pipeline models
- [x] Add `RawImportRun`
- [x] Add `RawListing`
- [x] Add `ParsedListingCandidate`
- [x] Add migrations, admin registration, and raw-listing dedupe tests

### Phase 2 — Clean phone/laptop models
- [x] Add `PhoneModel`, `PhoneVariant`, and `PhoneListing`
- [x] Add `LaptopModel`, `LaptopVariant`, and `LaptopListing`
- [x] Add migrations and admin registration

### Phase 3 — Raw import commands
- [x] Save Sahibinden and Ouedkniss imports to `RawListing`
- [x] Preserve full source payloads
- [x] Remove automatic snapshot recomputation from raw import commands

### Phase 4 — Parsing and review
- [x] Add phone, laptop, and console parsers
- [x] Add `candidate_builder`
- [x] Add `parse_raw_listings`
- [x] Add `/import-lab/` and candidate detail/review actions
- [x] Add AI-audit queues and `agent_review_candidates`

### Phase 5 — Migration and clean export
- [x] Backfill legacy `MarketListing` rows into `RawListing`
- [x] Parse backfilled rows into candidates
- [x] Export approved candidates to clean phone/laptop/console listings
- [x] Keep raw evidence and legacy data intact

### Phase 6 — Matching and data quality
- [x] Add strict phone/laptop/console identity gates
- [x] Reject garbage and unsafe generic laptop models
- [x] Add MacBook parsing regressions and duplicate merge tools
- [x] Add local HTML review exports and problem filters
- [x] Add laptop cleanup and catalog transition audits

### Phase 7 — Clean opportunities and frontend migration
- [x] Add phone opportunity snapshots
- [x] Add laptop opportunity snapshots
- [x] Add portable-console opportunity snapshots
- [x] Move root opportunity pages to clean snapshots
- [x] Move the deals swiper to clean snapshots with legacy fallback
- [x] Add buyer gain-split fields and ranked buyer-deal exports
- [x] Add enrichment-query generation for missing Türkiye comparisons

### Phase 8 — FX refresh
- [x] Add `fetch_exchange_rates`
- [x] Store EUR/TRY, EUR/USD, derived USD/TRY, and manual black-market EUR/DZD
- [x] Add command tests and documentation

## Next priority — Public repository data safety

The repository is public and intentionally tracks `db.sqlite3` plus historical SQLite backups. Before adding more features, verify that no private or reusable credentials are present.

- [ ] Inventory every tracked SQLite database and backup
- [ ] Check Django auth/session tables for real users, emails, password hashes, and active sessions
- [ ] Check raw payloads and imported data for cookies, API keys, tokens, private contact details, supplier/customer records, or other non-public data
- [ ] Produce a local audit report that records table names and counts without printing sensitive values
- [ ] Decide whether Git should retain a sanitized demo database or stop tracking live databases entirely
- [ ] Add ignore rules for future database backups and local generated artifacts
- [ ] Rewrite Git history only if secrets or sensitive personal data are actually found

## After the data audit

### CI and repository hygiene
- [ ] Add GitHub Actions for `python manage.py check` and the Django test suite
- [ ] Remove accidentally tracked caches, generated binaries, and duplicate scripts
- [ ] Decide which generated exports belong in Git and which should be reproducible artifacts

### Deployment safety
- [ ] Make `DEBUG` environment-controlled
- [ ] Replace `ALLOWED_HOSTS = ["*"]` with environment-configured hosts
- [ ] Require a production `DJANGO_SECRET_KEY`
- [ ] Add a deployment checklist and production settings guidance

### Product/data work
- [ ] Enrich Türkiye console inventory and generate console opportunities
- [ ] Continue candidate review for incomplete laptop and phone identities
- [ ] Validate buyer-facing ranked deals against source URLs before sharing externally
