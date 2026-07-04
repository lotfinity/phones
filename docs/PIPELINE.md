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
