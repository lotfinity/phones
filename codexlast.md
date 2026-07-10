
        counts = {
            "rows": len(rows),
            "needs_review": sum(1 for c in rows if c.status == ParsedListingCandidate.Status.NEEDS_REVIEW),
            "laptops": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP),
            "phones": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.PHONE),
            "missing_model": sum(1 for c in rows if not c.model_text),
        }

        body_rows = []
        for c in rows:
            raw = c.raw_listing
            phone = getattr(raw, "phone_listing", None)
            laptop = getattr(raw, "laptop_listing", None)
            final_listing = laptop or phone
            final_model = ""
            final_specs = ""
            final_status = ""
            if laptop:
                final_model = laptop.laptop_model.canonical_name if laptop.laptop_model else ""
                final_specs = " / ".join(
                    part for part in [
                        laptop.cpu,
                        laptop.gpu,
                        f"{laptop.ram_gb}GB RAM" if laptop.ram_gb else "",
                        f"{laptop.storage_gb}GB" if laptop.storage_gb else "",
                    ]
                    if part
                )
                final_status = f"LaptopListing {laptop.review_status} conf={laptop.parsed_confidence:.2f}"
            elif phone:
                final_model = phone.phone_model.canonical_name if phone.phone_model else ""
                final_specs = " / ".join(
                    part for part in [
                        f"{phone.ram_gb}GB RAM" if phone.ram_gb else "",
                        f"{phone.storage_gb}GB" if phone.storage_gb else "",
                        phone.sim_config,
                    ]
                    if part
                )
                final_status = f"PhoneListing {phone.review_status} conf={phone.parsed_confidence:.2f}"

            problem_bits = []
            problem_keys = self._problem_keys(c)
            if c.status == ParsedListingCandidate.Status.NEEDS_REVIEW:
                problem_bits.append(badge("needs review", "warn"))
            if "missing_model" in problem_keys:
                problem_bits.append(badge("missing model", "bad"))
            if "weak_confidence" in problem_keys:
                problem_bits.append(badge("weak candidate", "bad"))
            if "generic_model" in problem_keys:
                problem_bits.append(badge("generic model", "warn"))
            if "garbage_model" in problem_keys:
                problem_bits.append(badge("garbage model", "bad"))
            if c.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP and laptop and not any([laptop.cpu, laptop.gpu, laptop.ram_gb, laptop.storage_gb]):
                problem_bits.append(badge("no laptop specs", "bad"))
            if "candidate_final_mismatch" in problem_keys:
                problem_bits.append(badge("candidate/final mismatch", "warn"))
            if "not_export_eligible" in problem_keys:
                problem_bits.append(badge("not export eligible", "bad"))

            url = raw.listing_url or ""
            link = f'<a href="{esc(url)}" target="_blank">open</a>' if url else ""
            body_rows.append(
                "<tr>"
                f"<td>{raw.pk}<br><span class='small'>{esc(raw.source_type)} / {esc(raw.country)}</span></td>"
                f"<td class='raw'><b>{esc(raw.title_raw)}</b><br>{link}<br><span class='small'>{esc(url)}</span></td>"
                f"<td>{badge(c.detected_category)} {badge(c.status)}<br>{confidence_badge(c.confidence)}<br>{''.join(problem_bits)}</td>"
                f"<td><b>{esc(c.brand_text)} {esc(c.model_text)}</b><br><span class='small'>{esc(c.variant_text)}</span></td>"
                f"<td>{json_block(c.laptop_specs_json or c.phone_specs_json)}</td>"
                f"<td><b>{esc(final_model)}</b><br><span class='small'>{esc(final_specs)}</span><br>{badge(final_status, 'ok' if final_listing and final_listing.review_status == 'auto' else 'warn' if final_listing else 'bad')}</td>"
                f"<td>{money(c.price_original, c.currency_original)}<br><span class='small'>€ {esc(c.price_eur)}</span></td>"
                f"<td class='raw'><pre>{esc((raw.raw_text or '')[:900])}</pre></td>"
                "</tr>"
            )

        html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PriceBridge Data Review</title>
<style>{STYLE}</style>
</head>
<body>
<header>
  <h1>PriceBridge Data Review</h1>
  <div class="meta">Filters: category={esc(options.get('category') or 'all')} country={esc(options.get('country') or 'all')} source={esc(options.get('source_type') or 'all')} q={esc(options.get('q') or '')}</div>
</header>
<main>
  <section class="grid">
    <div class="card"><b>{counts['rows']}</b><span>Rows shown</span></div>
    <div class="card"><b>{counts['needs_review']}</b><span>Needs review</span></div>
    <div class="card"><b>{counts['laptops']} / {counts['phones']}</b><span>Laptops / Phones</span></div>
    <div class="card"><b>{counts['missing_model']}</b><span>Missing model</span></div>
  </section>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Raw Listing</th><th>Candidate State</th><th>Candidate Model</th><th>Extracted Specs</th><th>Final Listing</th><th>Price</th><th>Raw Text</th>
      </tr>
    </thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
</main>
</body>
</html>"""

        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html_doc, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} rows to {output}"))

    def _problem_keys(self, candidate):
        raw = candidate.raw_listing
        laptop = getattr(raw, "laptop_listing", None)
        model_text = candidate.model_text or ""
        final_model = laptop.laptop_model.canonical_name if laptop and laptop.laptop_model else ""
        problems = set()

        if not model_text:
            problems.add("missing_model")
        if candidate.confidence < 0.65:
            problems.add("weak_confidence")
        if candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
            if is_generic_laptop_model_name(model_text) or is_generic_laptop_model_name(final_model):
                problems.add("generic_model")
            if is_garbage_laptop_model_name(model_text) or is_garbage_laptop_model_name(final_model):
                problems.add("garbage_model")
            if laptop and final_model.lower() != model_text.lower():
                problems.add("candidate_final_mismatch")
            candidate_ok = candidate_has_laptop_export_identity(candidate)
            listing_ok = listing_has_laptop_export_identity(laptop) if laptop else False
            if not (candidate_ok or listing_ok):
                problems.add("not_export_eligible")
        return problems
✓ • 112ms

The HTML review command is laptop/phone-centric. I’m extending it just enough to filter/count/show portable consoles without changing the whole report.

• Edited market/management/commands/export_data_review.py (+21 -4)
     95          parser.add_argument("--limit", type=int, default=500)
     96 -        parser.add_argument("--category", choices=["phone", "laptop", "unknown", "accessory"])
     96 +        parser.add_argument("--category", choices=["phone", "laptop", "portable_console", "unknown", "accessory"])
     97          parser.add_argument("--country")
        ⋮
    123              "matched_laptop_variant",
    124 +            "matched_console_model",
    125 +            "matched_console_variant",
    126              "raw_listing__phone_listing__phone_model",
        ⋮
    129              "raw_listing__laptop_listing__variant",
    130 +            "raw_listing__console_listing__console_model",
    131 +            "raw_listing__console_listing__variant",
    132          ).order_by("-created_at")
        ⋮
    173              "phones": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.PHONE),
    174 +            "consoles": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE),
    175              "missing_model": sum(1 for c in rows if not c.model_text),
        ⋮
    182              laptop = getattr(raw, "laptop_listing", None)
    178 -            final_listing = laptop or phone
    183 +            console = getattr(raw, "console_listing", None)
    184 +            final_listing = laptop or phone or console
    185              final_model = ""
        ⋮
    210                  final_status = f"PhoneListing {phone.review_status} conf={phone.parsed_confidence:.2f}"
    211 +            elif console:
    212 +                final_model = console.console_model.canonical_name if console.console_model else ""
    213 +                final_specs = " / ".join(
    214 +                    part for part in [
    215 +                        console.chipset,
    216 +                        f"{console.ram_gb}GB RAM" if console.ram_gb else "",
    217 +                        f"{console.storage_gb}GB" if console.storage_gb else "",
    218 +                    ]
    219 +                    if part
    220 +                )
    221 +                final_status = f"ConsoleListing {console.review_status} conf={console.parsed_confidence:.2f}"
    222  
        ⋮
    249                  f"<td><b>{esc(c.brand_text)} {esc(c.model_text)}</b><br><span class='small'>{esc(c.variant_text)}</span></td>"
    233 -                f"<td>{json_block(c.laptop_specs_json or c.phone_specs_json)}</td>"
    250 +                f"<td>{json_block(c.laptop_specs_json or c.phone_specs_json or c.console_specs_json)}</td>"
    251                  f"<td><b>{esc(final_model)}</b><br><span class='small'>{esc(final_specs)}</span><br>{badge(final_status, 'ok' if final_listing and final_listing.review_status == 'auto' else 'warn' if final_listing else 'bad')}</td>"
        ⋮
    273      <div class="card"><b>{counts['needs_review']}</b><span>Needs review</span></div>
    257 -    <div class="card"><b>{counts['laptops']} / {counts['phones']}</b><span>Laptops / Phones</span></div>
    274 +    <div class="card"><b>{counts['laptops']} / {counts['phones']} / {counts['consoles']}</b><span>Laptops / Phones / Consoles</span></div>
    275      <div class="card"><b>{counts['missing_model']}</b><span>Missing model</span></div>

Review export now shows console candidates/finals. I’m running the focused parser/export tests and system checks.

$ python manage.py check && python manage.py makemigrations --check --dry-run
System check identified no issues (0 silenced).
No changes detected
✓ • 4.08s

$ python manage.py test market.tests_laptop_pipeline_v2.DetectCategoryFromSignalsTests market.tests_laptop_pipeline_v2.BuildCandidateSignalOverrideTests market.tests_raw_pipeline.ExportCandidatesCommandTests market.tests_raw_pipeline.AgentReviewCandidatesTests
Creating test database for alias 'default'...
.E...E.............F.............
======================================================================
ERROR: test_ouedkniss_console_url_becomes_portable_console (market.tests_laptop_pipeline_v2.BuildCandidateSignalOverrideTests.test_ouedkniss_console_url_becomes_portable_console)
Portable console URL should not be classified as laptop.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/lofa/DEV/phones/market/tests_laptop_pipeline_v2.py", line 1196, in test_ouedkniss_console_url_becomes_portable_console
    candidate, created = build_candidate(raw)
                         ~~~~~~~~~~~~~~~^^^^^
  File "/home/lofa/DEV/phones/market/services/parsing/candidate_builder.py", line 231, in build_candidate
    console_result = parse_console(raw_listing.raw_text, raw_listing.title_raw, payload)
  File "/home/lofa/DEV/phones/market/services/parsing/console_parser_v2.py", line 90, in parse_console
    price_original, currency_original = detect_price(text)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TypeError: cannot unpack non-iterable NoneType object

======================================================================
ERROR: test_export_console_creates_console_listing (market.tests_raw_pipeline.ExportCandidatesCommandTests.test_export_console_creates_console_listing)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/lofa/DEV/phones/market/tests_raw_pipeline.py", line 492, in test_export_console_creates_console_listing
    self._make_approved_candidate("console")
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/home/lofa/DEV/phones/market/tests_raw_pipeline.py", line 444, in _make_approved_candidate
    candidate, _ = build_candidate(raw)
                   ~~~~~~~~~~~~~~~^^^^^
  File "/home/lofa/DEV/phones/market/services/parsing/candidate_builder.py", line 231, in build_candidate
    console_result = parse_console(raw_listing.raw_text, raw_listing.title_raw, payload)
  File "/home/lofa/DEV/phones/market/services/parsing/console_parser_v2.py", line 90, in parse_console
    price_original, currency_original = detect_price(text)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TypeError: cannot unpack non-iterable decimal.Decimal object

======================================================================
FAIL: test_ouedkniss_consoles_url (market.tests_laptop_pipeline_v2.DetectCategoryFromSignalsTests.test_ouedkniss_consoles_url)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/lofa/DEV/phones/market/tests_laptop_pipeline_v2.py", line 1070, in test_ouedkniss_consoles_url
    self.assertEqual(detect_category_from_signals(url=url), "portable_console")
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: 'accessory' != 'portable_console'
- accessory
+ portable_console


----------------------------------------------------------------------
Ran 33 tests in 0.496s

FAILED (failures=1, errors=2)
Destroying test database for alias 'default'...
Found 33 test(s).
System check identified no issues (0 silenced).
✗ (1) • 7.03s

Focused tests exposed two implementation bugs: console URL matching missed hyphenated `legion-go`, and the shared price helper returns a single value in some cases. I’m fixing both.

$ rg -n "def detect_price" -A80 market/services/parsing/laptop_parser_v2.py
482:def detect_price(text):
483-    for m in _PRICE_PATTERN.finditer(text):
484-        raw = m.group(1) or m.group(2)
485-        if not raw:
486-            continue
487-        cleaned = re.sub(r"[^\d.,]", "", raw).strip()
488-        if not cleaned:
489-            continue
490-        cleaned = cleaned.replace(" ", "")
491-        if "," in cleaned and "." in cleaned:
492-            cleaned = cleaned.replace(",", "")
493-        elif "," in cleaned:
494-            parts = cleaned.split(",")
495-            if len(parts[-1]) == 3:
496-                cleaned = "".join(parts)
497-            else:
498-                cleaned = cleaned.replace(",", ".")
499-        try:
500-            return Decimal(cleaned)
501-        except InvalidOperation:
502-            continue
503-    return None
504-
505-
506-def detect_currency(text):
507-    m = re.search(r"(DA|DZD|TL|TRY|₺|\$|USD|€|EUR)", text, re.IGNORECASE)
508-    if m:
509-        return _CURRENCY_MAP.get(m.group().upper(), "DZD")
510-    return "DZD"
511-
512-
513-def detect_condition(text):
514-    text_lower = text.lower()
515-    for condition, keywords in _CONDITION_KEYWORDS.items():
516-        for kw in keywords:
517-            if kw in text_lower:
518-                return condition
519-    return "unknown"
520-
521-
522-def _identity_text(raw_text="", title_raw=""):
523-    """Prefer human listing text over serialized collector metadata for identity."""
524-    text = raw_text or title_raw or ""
525-    if "{\"source\"" in text:
526-        text = text.split("{\"source\"", 1)[0]
527-    if '"source" "sahibinden_cdp"' in text:
528-        text = text.split('"source" "sahibinden_cdp"', 1)[0]
529-    text = text.strip()
530-    if title_raw and (not text or len(text) > len(title_raw) * 2):
531-        return title_raw
532-    return text or title_raw or raw_text or ""
533-
534-
535-def _extract_model_text(text, brand):
536-    """Extract model family from text after removing spec tokens and garbage.
537-
538-    Strategy:
539-    1. Find brand position in text.
540-    2. Take text after brand, up to first known spec keyword.
541-    3. Clean up: remove specs, garbage words, repeated tokens.
542-    4. Keep meaningful model family tokens.
543-    """
544-    if not brand:
545-        return ""
546-
547-    # Find brand position
548-    brand_match = re.search(re.escape(brand), text, re.IGNORECASE)
549-    if not brand_match:
550-        return ""
551-
552-    after_brand = text[brand_match.end():]
553-
554-    # Cut at first spec keyword
555-    spec_cutoff = re.search(
556-        r"\b(?:i[3579]|i[3579]-\d|Ryzen|RTX|GTX|MX\d|Iris|UHD|Radeon|Intel|AMD|NVIDIA|"
557-        r"\d+\s*(?:GB|TB|Go|RAM|SSD|HDD|NVMe|Hz|inch|cm)|"
558-        r"FHD|QHD|4K|UHD|\d{3,4}x\d{3,4})",
559-        after_brand,
560-        re.IGNORECASE,
561-    )
562-    if spec_cutoff:
✓ • 0ms

The laptop price detector returns just the amount and a separate currency detector exists. I’m using that correctly and normalizing hyphenated URL text before console identity matching.

• Edited market/services/parsing/console_parser_v2.py (+6 -2)
     7      detect_condition,
     8 +    detect_currency,
     9      detect_price,
       ⋮
    43  def is_portable_console_text(text):
    43 -    text = text or ""
    44 +    text = re.sub(r"[-_/]+", " ", text or "")
    45      return any(pattern.search(text) for pattern, _brand, _model in _CONSOLE_PATTERNS)
       ⋮
    48  def detect_console_identity(text):
    49 +    text = re.sub(r"[-_/]+", " ", text or "")
    50      for pattern, brand, model in _CONSOLE_PATTERNS:
       ⋮
    56  def detect_chipset(text):
    57 +    text = re.sub(r"[-_/]+", " ", text or "")
    58      for pattern, chipset in _CHIPSET_PATTERNS:
       ⋮
    92      brand, model = detect_console_identity(text)
    90 -    price_original, currency_original = detect_price(text)
    93 +    price_original = detect_price(text)
    94 +    currency_original = detect_currency(text) if price_original is not None else ""
    95      price_eur = convert_to_eur(price_original, currency_original) if price_original and currency_original else None

Those parser bugs are fixed. I’m rerunning the focused tests.

$ python manage.py test market.tests_laptop_pipeline_v2.DetectCategoryFromSignalsTests market.tests_laptop_pipeline_v2.BuildCandidateSignalOverrideTests market.tests_raw_pipeline.ExportCandidatesCommandTests market.tests_raw_pipeline.AgentReviewCandidatesTests
Creating test database for alias 'default'...
.................................
----------------------------------------------------------------------
Ran 33 tests in 0.397s

OK
Destroying test database for alias 'default'...
Found 33 test(s).
System check identified no issues (0 silenced).
✓ • 7.28s

Focused tests pass. I’m going to reparse the current dataset for console signals now, then inspect how many portable console candidates we actually have and whether they have enough identity to export into review-only clean console rows.

$ python manage.py parse_raw_listings --category consoles --reparse --limit 1000
Done. Parsed: 1000, Needs review: 789, High confidence (>= 95%): 6, Errors: 0
  Laptop: +0 created, 632 updated | Phone: +0 created, 314 updated | Console: +0 created, 18 updated | Accessory/unknown: 36 | Converted phone->laptop: 0 | Repaired corrupt decimals: 0
✓ • 26.77s

The reparse found 18 portable console candidates in the current data. I’m inspecting those rows next and then I’ll export the ones with enough identity into `ConsoleListing` review rows.

$ python manage.py shell -c "from market.models import ParsedListingCandidate; qs=ParsedListingCandidate.objects.filter(detected_category='portable_console').select_related('raw_listing'); print('console candidates', qs.count());
    for c in qs.order_by('-confidence')[:30]: print(c.id, c.status, c.confidence, c.brand_text, c.model_text, c.console_specs_json, c.raw_listing.title_raw[:100], c.raw_listing.listing_url)"
42 objects imported automatically (use -v 2 for details).

console candidates 18
899 pending 0.9999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally X 24gb 1tb https://www.ouedkniss.com/consoles-asus-rog-ally-x-24gb-1tb-oran-algeria-d50901751
898 pending 0.9999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally RC71L amd Z1 Extreme 16Go RAM 512Go SSD https://www.ouedkniss.com/consoles-asus-rog-ally-rc71l-amd-z1-extreme-16go-ram-512go-ssd-mostaganem-algeria-d56443156
897 pending 0.9999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus rog ally x 1TB /24Gb avec système de refroidissement https://www.ouedkniss.com/consoles-asus-rog-ally-x-1tb-24gb-avec-systeme-de-refroidissement-bab-ezzouar-alger-algeria-d54319691
893 pending 0.9999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ASUS ROG Ally | Ryzen Z1 Extreme | 16GB | 512GB SSD https://www.ouedkniss.com/laptop-asus-rog-ally-ryzen-z1-extreme-16gb-512gb-ssd-bab-ezzouar-alger-algeria-d56232406
892 pending 0.9999999999999999 Microsoft Xbox Ally {'chipset': '', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY AMD RYZEN Z2A 16GB 512GB NVME 7 FHD 120Hz https://www.ouedkniss.com/other-asus-rog-xbox-ally-amd-ryzen-z2a-16gb-512gb-nvme-7-fhd-120hz-birkhadem-alger-algeria-d35340259
8 pending 0.9999999999999999 Lenovo Legion Go {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} LENOVO LEGION GO | Ryzen Z1 Extreme | 16GB | 512GB SSD https://www.ouedkniss.com/laptop-lenovo-legion-go-ryzen-z1-extreme-16gb-512gb-ssd-bab-ezzouar-alger-algeria-d56176264
907 pending 0.8999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': 1024, 'screen_size': 8.0, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ROG ALLY X 1 TB https://www.ouedkniss.com/consoles-rog-ally-x-1-tb-tiaret-algeria-d56292232
906 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE -... https://www.ouedkniss.com/other-asus-rog-xbox-ally-x-amd-ryzen-ai-z2-extreme-24gb-1tb-7-120hz-tactile-wifi-6e-bt-52-win11-original-scellee-kouba-alger-algeria-d55068697
905 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE -... https://www.ouedkniss.com/other-asus-rog-xbox-ally-x-amd-ryzen-ai-z2-extreme-24gb-1tb-7-120hz-tactile-wifi-6e-bt-52-win11-original-scellee-tipaza-algeria-d55393378
901 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE... https://www.ouedkniss.com/consoles-asus-rog-xbox-ally-x-amd-ryzen-ai-z2-extreme-24gb-1tb-7-120hz-tactile-wifi-6e-bt-52-win11-original-scellee-hussein-dey-alger-algeria-d55066459
896 pending 0.8999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Rog ally z1 extreme (comme neuf) https://www.ouedkniss.com/consoles-rog-ally-z1-extreme-comme-neuf-bordj-el-kiffan-alger-algeria-d56236168
894 pending 0.8999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE - WIFI... https://www.ouedkniss.com/consoles-asus-rog-ally-x-amd-ryzen-ai-z2-extreme-24gb-1tb-7-120hz-tactile-wifi-6e-bt-52-win11-original-scellee-kouba-alger-algeria-d55066837
904 pending 0.7999999999999999 ASUS ROG Ally {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Xbox rog ally https://www.ouedkniss.com/laptop-xbox-rog-ally-hussein-dey-alger-algeria-d55834843
903 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally X https://www.ouedkniss.com/consoles-asus-rog-ally-x-zeralda-alger-algeria-d56125555
902 pending 0.7999999999999999 ASUS ROG Ally {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog ally Z1 extrême https://www.ouedkniss.com/consoles-asus-rog-ally-z1-extreme-bab-ezzouar-alger-algeria-d55575283
900 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ROG ALLY X https://www.ouedkniss.com/consoles-rog-ally-x-relizane-algeria-d55943395
895 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': 7.0, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog ally x Black https://www.ouedkniss.com/consoles-asus-rog-ally-x-black-chetouane-tlemcen-algeria-d56298694
991 needs_review 0.0   {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': 7.0, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} TP-Link UH700 Hub USB 3.0 - 7 Ports Multiprise USB - Sortie 5 V/1.5 A - Indicate... https://www.ouedkniss.com/cables-adapters-tp-link-uh700-hub-usb-30-7-ports-multiprise-sortie-5-v15-a-indicateur-led-switch-compatible-avec-macbook-pro-imac-surface-xps-pc-ordinateur-portable-cle-birkhadem-alger-algeria-d55760617
✓ • 5.30s

$ python manage.py export_data_review --category portable_console --limit 100 --output exports/review_consoles.html
Exported 18 rows to exports/review_consoles.html
✓ • 5.90s

The console pass found 18 candidates, but one is a false positive: a TP-Link USB hub with the word “switch”. I’m tightening Switch detection so generic “switch compatible” accessories do not become consoles, then I’ll reparse and export the real console rows.

• Edited market/services/parsing/console_parser_v2.py (+3 -3)
    23      (re.compile(r"\b(?:msi\s+)?claw\b", re.IGNORECASE), "MSI", "Claw"),
    24 -    (re.compile(r"\b(?:nintendo\s+)?switch\s+oled\b", re.IGNORECASE), "Nintendo", "Switch OLED"),
    25 -    (re.compile(r"\b(?:nintendo\s+)?switch\s+lite\b", re.IGNORECASE), "Nintendo", "Switch Lite"),
    26 -    (re.compile(r"\b(?:nintendo\s+)?switch\b", re.IGNORECASE), "Nintendo", "Switch"),
    24 +    (re.compile(r"\bnintendo\s+switch\s+oled\b|\bswitch\s+oled\b", re.IGNORECASE), "Nintendo", "Switch OLED"),
    25 +    (re.compile(r"\bnintendo\s+switch\s+lite\b|\bswitch\s+lite\b", re.IGNORECASE), "Nintendo", "Switch Lite"),
    26 +    (re.compile(r"\bnintendo\s+switch\b", re.IGNORECASE), "Nintendo", "Switch"),
    27      (re.compile(r"\b(?:playstation|ps)\s*portal\b", re.IGNORECASE), "Sony", "PlayStation Portal"),

Switch matching is tightened. I’m rerunning the console reparse and then checking the candidate list again before exporting.

The reparse is still running because it is processing the broad candidate set. I’m waiting for the command to finish rather than starting another mutation in parallel.

$ python manage.py parse_raw_listings --category consoles --reparse --limit 1000 && python manage.py shell -c "from market.models import ParsedListingCandidate; qs=ParsedListingCandidate.objects.filter(detected_category='portable_console').select_related('raw_listing'); print('console candidates', qs.count());
    for c in qs.order_by('-confidence')[:25]: print(c.id, c.status, c.confidence, c.brand_text, c.model_text, c.console_specs_json, c.raw_listing.title_raw[:80])"
Done. Parsed: 1000, Needs review: 789, High confidence (>= 95%): 6, Errors: 0
  Laptop: +0 created, 632 updated | Phone: +0 created, 315 updated | Console: +0 created, 17 updated | Accessory/unknown: 36 | Converted phone->laptop: 0 | Repaired corrupt decimals: 0
42 objects imported automatically (use -v 2 for details).

console candidates 17
899 pending 0.9999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally X 24gb 1tb
898 pending 0.9999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally RC71L amd Z1 Extreme 16Go RAM 512Go SSD
897 pending 0.9999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus rog ally x 1TB /24Gb avec système de refroidissement
893 pending 0.9999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ASUS ROG Ally | Ryzen Z1 Extreme | 16GB | 512GB SSD
892 pending 0.9999999999999999 Microsoft Xbox Ally {'chipset': '', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY AMD RYZEN Z2A 16GB 512GB NVME 7 FHD 120Hz
8 pending 0.9999999999999999 Lenovo Legion Go {'chipset': 'AMD Z1 Extreme', 'ram_gb': 16, 'storage_gb': 512, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} LENOVO LEGION GO | Ryzen Z1 Extreme | 16GB | 512GB SSD
907 pending 0.8999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': 1024, 'screen_size': 8.0, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ROG ALLY X 1 TB
906 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE -
905 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE -
901 pending 0.8999999999999999 Microsoft Xbox Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG XBOX ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE..
896 pending 0.8999999999999999 ASUS ROG Ally {'chipset': 'AMD Z1 Extreme', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Rog ally z1 extreme (comme neuf)
894 pending 0.8999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': 24, 'storage_gb': 1024, 'screen_size': 7.0, 'refresh_rate_hz': 120, 'connectivity': '', 'color': ''} ASUS ROG ALLY X - AMD RYZEN AI Z2 EXTREME - 24GB - 1TB - 7" 120HZ TACTILE - WIFI
904 pending 0.7999999999999999 ASUS ROG Ally {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Xbox rog ally
903 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog Ally X
902 pending 0.7999999999999999 ASUS ROG Ally {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog ally Z1 extrême
900 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': None, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} ROG ALLY X
895 pending 0.7999999999999999 ASUS ROG Ally X {'chipset': '', 'ram_gb': None, 'storage_gb': None, 'screen_size': 7.0, 'refresh_rate_hz': None, 'connectivity': '', 'color': ''} Asus Rog ally x Black
✓ • 40.72s

The false positive is gone; current data has 17 real portable console candidates. I’m exporting the identity-complete pending console candidates into clean `ConsoleListing` rows now; incomplete ones will remain review-only.

$ python manage.py export_candidates --category=consoles --status=pending --limit=100 && python manage.py shell -c "from market.models import ConsoleListing,ParsedListingCandidate; print('console listings', ConsoleListing.objects.count()); print('remaining console candidates', ParsedListingCandidate.objects.filter(detected_category='portable_console').count()); print('needs_review', ParsedListingCandidate.objects.filter(detected_category='portable_console', status='needs_review').count());
    for l in ConsoleListing.objects.select_related('console_model','console_model__brand').order_by('-parsed_confidence')[:20]: print(l.id, l.review_status, l.console_model.brand.name if l.console_model and l.console_model.brand else '', l.console_model.canonical_name if l.console_model else '', l.ram_gb, l.storage_gb, l.price_eur, l.title[:80])"
Exported 11 consoles candidates.
Skipped 6 unsafe candidates to needs_review.
42 objects imported automatically (use -v 2 for details).

console listings 11
remaining console candidates 17
needs_review 6
5 needs_review ASUS ROG Ally X 24 1024 669.49 ASUS ROG Ally X
6 needs_review ASUS ROG Ally 16 512 307.60 ASUS ROG Ally
7 needs_review ASUS ROG Ally X 24 1024 611.59 ASUS ROG Ally X
9 needs_review ASUS ROG Ally 16 512 340.17 ASUS ROG Ally
10 needs_review Microsoft Xbox Ally 16 512 463.21 Microsoft Xbox Ally
11 needs_review Lenovo Legion Go 16 512 517.50 Lenovo Legion Go
1 needs_review ASUS ROG Ally X None 1024 430.64 ASUS ROG Ally X
2 needs_review Microsoft Xbox Ally X 24 1024 705.68 Microsoft Xbox Ally X
3 needs_review Microsoft Xbox Ally X 24 1024 694.82 Microsoft Xbox Ally X
4 needs_review Microsoft Xbox Ally X 24 1024 705.68 Microsoft Xbox Ally X
8 needs_review ASUS ROG Ally X 24 1024 705.68 ASUS ROG Ally X
✓ • 5.06s

Eleven console candidates are now clean final rows, but marked `needs_review` because they came from parser confidence, not human/AI approval. I’m computing console opportunities now; likely it will be zero until we enrich Türkiye matching data.

$ python manage.py recompute_console_opportunities_v1 --write-snapshots --export-json exports/console_opportunities_v1.json
Wrote 0 clean console opportunity snapshots; replaced 0 old rows.
Exported 0 rows to exports/console_opportunities_v1.json
Clean console opportunity rows: 0
Brand | Model | Chipset | RAM | Storage | DZ min € | TR avg € | Margin € | Margin % | Counts
------------------------------------------------------------------------------------------------------------------------
✓ • 3.21s

Console opportunities are zero because we now have Algeria console supply but no Türkiye console comparison rows. That is exactly the enrichment phase input. I’m adding a small command to generate prioritized Sahibinden search URLs from one-sided clean listings/snapshots so you can open CDP tabs and import targeted missing matches fast.

• Added market/management/commands/build_enrichment_queries.py (+153 -0)
      1 +"""Build targeted marketplace search queries for missing comparison data."""
      2 +
      3 +from decimal import Decimal
      4 +from urllib.parse import quote_plus
      5 +
      6 +from django.core.management.base import BaseCommand
      7 +from django.db.models import Count, Min
      8 +
      9 +from market.models import ConsoleListing, Country, LaptopListing, PhoneListing
     10 +
     11 +
     12 +SAHIBINDEN_BASE = "https://www.sahibinden.com/arama?query_text={query}"
     13 +
     14 +
     15 +def sahibinden_url(query):
     16 +    return SAHIBINDEN_BASE.format(query=quote_plus(query))
     17 +
     18 +
     19 +class Command(BaseCommand):
     20 +    help = "Print prioritized search queries for enriching one-sided clean listing data."
     21 +
     22 +    def add_arguments(self, parser):
     23 +        parser.add_argument("--category", choices=["phones", "laptops", "consoles", "all"], default="all")
     24 +        parser.add_argument("--country-missing", choices=["turkiye"], default="turkiye")
     25 +        parser.add_argument("--limit", type=int, default=30)
     26 +        parser.add_argument("--min-algeria-count", type=int, default=1)
     27 +        parser.add_argument("--format", choices=["table", "urls"], default="table")
     28 +
     29 +    def handle(self, *args, **options):
     30 +        rows = []
     31 +        category = options["category"]
     32 +        if category in ("phones", "all"):
     33 +            rows.extend(self._phone_rows(options["min_algeria_count"]))
     34 +        if category in ("laptops", "all"):
     35 +            rows.extend(self._laptop_rows(options["min_algeria_count"]))
     36 +        if category in ("consoles", "all"):
     37 +            rows.extend(self._console_rows(options["min_algeria_count"]))
     38 +        rows.sort(key=lambda row: (row["algeria_min_eur"] or Decimal("0"), row["algeria_count"]), reverse=True)
     39 +        rows = rows[: options["limit"]]
     40 +
     41 +        if options["format"] == "urls":
     42 +            for row in rows:
     43 +                self.stdout.write(row["url"])
     44 +            return
     45 +
     46 +        self.stdout.write("Type | Query | DZ count | DZ min EUR | Sahibinden URL")
     47 +        self.stdout.write("-" * 140)
     48 +        for row in rows:
     49 +            self.stdout.write(
     50 +                f"{row['type']} | {row['query']} | {row['algeria_count']} | "
     51 +                f"{row['algeria_min_eur'] or '-'} | {row['url']}"
     52 +            )
     53 +
     54 +    def _phone_rows(self, min_count):
     55 +        dz = (
     56 +            PhoneListing.objects.filter(country=Country.ALGERIA, phone_model__isnull=False, price_eur__isnull=False)
     57 +            .values("phone_model_id", "phone_model__brand__name", "phone_model__canonical_name", "storage_gb")
     58 +            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
     59 +            .filter(algeria_count__gte=min_count)
     60 +        )
     61 +        rows = []
     62 +        for item in dz:
     63 +            tr_exists = PhoneListing.objects.filter(
     64 +                country=Country.TURKIYE,
     65 +                phone_model_id=item["phone_model_id"],
     66 +                storage_gb=item["storage_gb"],
     67 +                price_eur__isnull=False,
     68 +            ).exists()
     69 +            if tr_exists:
     70 +                continue
     71 +            query = " ".join(
     72 +                part for part in [
     73 +                    item["phone_model__brand__name"],
     74 +                    item["phone_model__canonical_name"],
     75 +                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
     76 +                ]
     77 +                if part
     78 +            )
     79 +            rows.append(self._row("phone", query, item))
     80 +        return rows
     81 +
     82 +    def _laptop_rows(self, min_count):
     83 +        dz = (
     84 +            LaptopListing.objects.filter(country=Country.ALGERIA, laptop_model__isnull=False, price_eur__isnull=False)
     85 +            .values("laptop_model_id", "laptop_model__brand__name", "laptop_model__canonical_name", "cpu", "gpu", "ram_gb", "storage_gb")
     86 +            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
     87 +            .filter(algeria_count__gte=min_count)
     88 +        )
     89 +        rows = []
     90 +        for item in dz:
     91 +            tr_filter = {
     92 +                "country": Country.TURKIYE,
     93 +                "laptop_model_id": item["laptop_model_id"],
     94 +                "price_eur__isnull": False,
     95 +            }
     96 +            if item["ram_gb"]:
     97 +                tr_filter["ram_gb"] = item["ram_gb"]
     98 +            if item["storage_gb"]:
     99 +                tr_filter["storage_gb"] = item["storage_gb"]
    100 +            if LaptopListing.objects.filter(**tr_filter).exists():
    101 +                continue
    102 +            query = " ".join(
    103 +                part for part in [
    104 +                    item["laptop_model__brand__name"],
    105 +                    item["laptop_model__canonical_name"],
    106 +                    item["cpu"],
    107 +                    item["gpu"],
    108 +                    f"{item['ram_gb']}GB" if item["ram_gb"] else "",
    109 +                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
    110 +                ]
    111 +                if part
    112 +            )
    113 +            rows.append(self._row("laptop", query, item))
    114 +        return rows
    115 +
    116 +    def _console_rows(self, min_count):
    117 +        dz = (
    118 +            ConsoleListing.objects.filter(country=Country.ALGERIA, console_model__isnull=False, price_eur__isnull=False)
    119 +            .values("console_model_id", "console_model__brand__name", "console_model__canonical_name", "chipset", "ram_gb", "storage_gb")
    120 +            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
    121 +            .filter(algeria_count__gte=min_count)
    122 +        )
    123 +        rows = []
    124 +        for item in dz:
    125 +            tr_exists = ConsoleListing.objects.filter(
    126 +                country=Country.TURKIYE,
    127 +                console_model_id=item["console_model_id"],
    128 +                storage_gb=item["storage_gb"],
    129 +                price_eur__isnull=False,
    130 +            ).exists()
    131 +            if tr_exists:
    132 +                continue
    133 +            query = " ".join(
    134 +                part for part in [
    135 +                    item["console_model__brand__name"],
    136 +                    item["console_model__canonical_name"],
    137 +                    item["chipset"],
    138 +                    f"{item['ram_gb']}GB" if item["ram_gb"] else "",
    139 +                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
    140 +                ]
    141 +                if part
    142 +            )
    143 +            rows.append(self._row("console", query, item))
    144 +        return rows
    145 +
    146 +    def _row(self, row_type, query, item):
    147 +        return {
    148 +            "type": row_type,
    149 +            "query": query,
    150 +            "algeria_count": item["algeria_count"],
    151 +            "algeria_min_eur": item["algeria_min_eur"],
    152 +            "url": sahibinden_url(query),
    153 +        }

The enrichment query generator is in. I’m running it for consoles now to produce the next CDP targets.

$ python manage.py build_enrichment_queries --category consoles --limit 20
Type | Query | DZ count | DZ min EUR | Sahibinden URL
--------------------------------------------------------------------------------------------------------------------------------------------
console | Microsoft Xbox Ally X 24GB 1024GB | 3 | 694.820000000000 | https://www.sahibinden.com/arama?query_text=Microsoft+Xbox+Ally+X+24GB+1024GB
console | ASUS ROG Ally X 24GB 1024GB | 3 | 611.590000000000 | https://www.sahibinden.com/arama?query_text=ASUS+ROG+Ally+X+24GB+1024GB
console | Lenovo Legion Go AMD Z1 Extreme 16GB 512GB | 1 | 517.5 | https://www.sahibinden.com/arama?query_text=Lenovo+Legion+Go+AMD+Z1+Extreme+16GB+512GB
console | Microsoft Xbox Ally 16GB 512GB | 1 | 463.210000000000 | https://www.sahibinden.com/arama?query_text=Microsoft+Xbox+Ally+16GB+512GB
console | ASUS ROG Ally X 1024GB | 1 | 430.640000000000 | https://www.sahibinden.com/arama?query_text=ASUS+ROG+Ally+X+1024GB
console | ASUS ROG Ally AMD Z1 Extreme 16GB 512GB | 2 | 307.600000000000 | https://www.sahibinden.com/arama?query_text=ASUS+ROG+Ally+AMD+Z1+Extreme+16GB+512GB
✓ • 5.68s

$ python manage.py test market.tests_laptop_pipeline_v2.DetectCategoryFromSignalsTests market.tests_laptop_pipeline_v2.BuildCandidateSignalOverrideTests market.tests_raw_pipeline.ExportCandidatesCommandTests market.tests_raw_pipeline.AgentReviewCandidatesTests
Creating test database for alias 'default'...
.................................
----------------------------------------------------------------------
Ran 33 tests in 1.219s

OK
Destroying test database for alias 'default'...
Found 33 test(s).
System check identified no issues (0 silenced).
✓ • 15.86s

We now have concrete enrichment targets. I’m updating docs/changelog, then I’ll run the full suite and a route smoke test.

• Edited 2 files (+28 -23)
  └ CHANGELOG.md (+3 -0)
    23  - Added `agent_review_candidates` to run the OpenCode AI audit against raw-first candidates, defaulting to phone/laptop only so accessories and unknown rows are skipped unless explicitly requested.
    24 +- Added a raw-first portable gaming console lane: `portable_console` candidates, `ConsoleModel`/`ConsoleVariant`/`ConsoleListing`, `ConsoleOpportunitySnapshot`, console parser/export support, and `recompute_console_opportunities_v1`.
    25 +- Reclassified current portable console rows into the console lane and exported 11 identity-complete Algeria console listings; console opportunities are currently zero until Türkiye comparison rows are enriched.
    26 +- Added `build_enrichment_queries` to generate prioritized Sahibinden search URLs for one-sided phone/laptop/console rows.
    27  

  └ docs/PIPELINE.md (+25 -23)
      5  
      6 -`RawListing -> ParsedListingCandidate -> PhoneListing/LaptopListing -> v2 exports`
      6 +`RawListing -> ParsedListingCandidate -> PhoneListing/LaptopListing/ConsoleListing -> v2 exports`
      7  
        ⋮
     38  
     39 -`PhoneListing` and `LaptopListing` are the normalized final listing tables for
     40 -the raw-first pipeline. They preserve source URL and raw FK traceability.
     39 +`PhoneListing`, `LaptopListing`, and `ConsoleListing` are the normalized final
     40 +listing tables for the raw-first pipeline. They preserve source URL and raw FK
     41 +traceability.
     42  
        ⋮
     44  `LaptopModel` / `LaptopVariant` are clean laptop catalog rows.
     45 +`ConsoleModel` / `ConsoleVariant` are clean portable gaming console catalog rows.
     46  
        ⋮
     69    `LaptopOpportunitySnapshot` with `--write-snapshots`.
     70 +- `recompute_console_opportunities_v1` computes portable console opportunities
     71 +  from `ConsoleListing`.
     72 +- `build_enrichment_queries` prints targeted Sahibinden search URLs for
     73 +  one-sided phone/laptop/console rows that need Türkiye comparison data.
     74  - The root opportunities page reads clean phone/laptop opportunity snapshots.
        ⋮
    137  Rows such as ASUS ROG Ally, Lenovo Legion Go, Steam Deck, MSI Claw, Nintendo
    132 -Switch, and PlayStation Portal should not be forced into `LaptopListing`.
    133 -They share some specs with laptops (CPU, RAM, storage, screen, refresh rate),
    134 -but the market comparison should treat them as a separate device family.
    138 +Switch, Xbox Ally, and PlayStation Portal must not be forced into
    139 +`LaptopListing`. They now use:
    140 +
    141 +`RawListing -> ParsedListingCandidate(portable_console) -> ConsoleListing -> ConsoleOpportunitySnapshot`
    142  
    136 -Recommended path:
    143 +Console exports require model plus storage, or model plus chipset/RAM, or an
    144 +explicit high-confidence variant match. Accessories such as cases, chargers,
    145 +docks, keyboards, mice, bags, and replacement screens stay out of opportunity
    146 +exports unless a separate accessory resale workflow is explicitly added.
    147  
    138 -1. Add a `portable_console` detected category.
    139 -2. Add clean final tables such as `ConsoleModel`, `ConsoleVariant`, and
    140 -   `ConsoleListing`, or one generic `DeviceListing` table keyed by
    141 -   `ProductType` if tablets/consoles/cameras will all follow soon.
    142 -3. Parse identity fields:
    143 -   model family, chipset/APU, RAM, storage, screen size, refresh rate, condition,
    144 -   and included accessories.
    145 -4. Export opportunities only when both sides match a specific console variant,
    146 -   usually model + storage, and for PC handhelds optionally model + chipset +
    147 -   RAM + storage.
    148 -5. Keep accessories such as cases, chargers, docks, keyboards, mice, bags, and
    149 -   replacement screens out of opportunity exports unless a separate accessory
    150 -   resale workflow is explicitly added.
    148 +Use enrichment queries to fill missing Türkiye comparisons:
    149  
    152 -For the current data, portable consoles are present in the unknown/review bucket
    153 -and should be promoted through a dedicated parser/final listing path, not by
    154 -loosening laptop gates.
    150 +```bash
    151 +python manage.py build_enrichment_queries --category consoles --limit 20
    152 +python manage.py import_sahibinden_from_cdp --category consoles --query "ASUS ROG Ally X 24GB 1024GB"
    153 +python manage.py parse_raw_listings --category consoles --country turkiye --reparse --limit 500
    154 +python manage.py export_candidates --category consoles --status pending --limit 500
    155 +python manage.py recompute_console_opportunities_v1 --write-snapshots
    156 +```

Docs/changelog are updated. I’m running full tests and a smoke test for the clean opportunities/deals routes with the new console models loaded.

$ python manage.py shell -c "from django.test import Client; from django.urls import reverse; c=Client();
    for path,name in [('/', 'root'), (reverse('deals_swiper'),'deals'), (reverse('deals_more')+'?brand=ALL&offset=0&limit=10','more')]:
     r=c.get(path); print(name, r.status_code);
     if name=='more': print(r.json().get('ok'), r.json().get('count'), r.json().get('total'))"
[deals_more] brand=ALL offset=0 limit=10
[deals_more] total=11 returned=10
42 objects imported automatically (use -v 2 for details).

root 200
deals 200
more 200
True 10 11
✓ • 6.03s

$ python manage.py check && python manage.py makemigrations --check --dry-run
System check identified no issues (0 silenced).
No changes detected
✓ • 10.85s

The smoke tests and Django checks passed. The full test run is still going; I’m waiting for completion before summarizing.

$ python manage.py test
Creating test database for alias 'default'...
..................[deals_more] brand=ALL offset=0 limit=10
[deals_more] total=1 returned=1
.[deals_more] brand=ALL offset=0 limit=30
[deals_more] total=1 returned=1
.[deals_more] brand=ALL offset=0 limit=10
[deals_more] total=1 returned=1
...........................................................................................................................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 335 tests in 28.387s

OK
Destroying test database for alias 'default'...
Found 335 test(s).
System check identified no issues (0 silenced).
✓ • 45.28s

Full tests passed. I’m collecting the final counts and file list now so I can give you a direct “where we are / what’s next” answer.

$ git diff --stat -- . ':(exclude)**/__pycache__/**' && git status --short -- . ':(exclude)**/__pycache__/**'
 CHANGELOG.md                                       |  26 ++
 db.sqlite3                                         | Bin 15081472 -> 16498688 bytes
 docs/DATA_MODEL.md                                 |  22 +-
 docs/PIPELINE.md                                   | 179 +++++++++---
 exports/laptop_opportunities_v2.json               | 211 +++++++++++---
 market/admin.py                                    | 212 +++++++++++++-
 market/apps.py                                     |  36 ++-
 market/clean_models.py                             | 139 ++++++++++
 market/management/commands/export_candidates.py    | 140 +++++++++-
 market/management/commands/export_data_review.py   |  94 ++++++-
 .../commands/merge_duplicate_laptop_models.py      |  23 ++
 market/management/commands/parse_raw_listings.py   |  60 +++-
 .../commands/recompute_laptop_opportunities_v2.py  | 108 +++++++-
 market/models.py                                   | 166 +++++++++++
 market/services/laptop_model_canonicalization.py   |  24 ++
 market/services/parsing/candidate_builder.py       | 138 ++++++----
 market/services/parsing/laptop_parser_v2.py        |  28 +-
 market/services/parsing/phone_parser_v2.py         |   9 +-
 market/tests.py                                    |  91 ++++++
 market/tests_catalog_transition.py                 |   2 +
 market/tests_laptop_macbook_regressions.py         |  18 ++
 market/tests_laptop_pipeline_v2.py                 | 217 ++++++++++++++-
 market/tests_raw_pipeline.py                       | 173 +++++++++++-
 market/views.py                                    | 306 ++++++++++++++++++---
 pricebridge/urls.py                                |   3 +-
 25 files changed, 2219 insertions(+), 206 deletions(-)
 M CHANGELOG.md
 M db.sqlite3
 M docs/DATA_MODEL.md
 M docs/PIPELINE.md
 M exports/laptop_opportunities_v2.json
 M market/admin.py
 M market/apps.py
 M market/clean_models.py
 M market/management/commands/export_candidates.py
 M market/management/commands/export_data_review.py
 M market/management/commands/merge_duplicate_laptop_models.py
 M market/management/commands/parse_raw_listings.py
 M market/management/commands/recompute_laptop_opportunities_v2.py
 M market/models.py
 M market/services/laptop_model_canonicalization.py
 M market/services/parsing/candidate_builder.py
 M market/services/parsing/laptop_parser_v2.py
 M market/services/parsing/phone_parser_v2.py
 M market/tests.py
 M market/tests_catalog_transition.py
 M market/tests_laptop_macbook_regressions.py
 M market/tests_laptop_pipeline_v2.py
 M market/tests_raw_pipeline.py
 M market/views.py
 M pricebridge/urls.py
?? backups/db.before-laptop-clean-pipeline.20260709-134144.sqlite3
?? backups/db.before-laptop-listing-cleanup-20260709-235451.sqlite3
?? backups/db.before-laptop-listing-cleanup-20260710-004643.sqlite3
?? backups/db.before-laptop-listing-cleanup-20260710-005506.sqlite3
?? backups/db.before-phone-model-merge.2026-07-09-115215.sqlite3
?? backups/db.before-phone-model-merge.2026-07-09-115320.sqlite3
?? backups/db.before-phone-model-merge.2026-07-09-115331.sqlite3
?? backups/db.before-raw-laptop-gates-20260710-022200.sqlite3
?? backups/db.before-safe-apple-laptop-model-merge-20260710-035042.sqlite3
?? backups/db.before-stash-inspect.sqlite3
?? backups/db.current.2026-07-09-111620.sqlite3
?? backups/db.from-stash.sqlite3
?? exports/console_opportunities_v1.json
?? exports/data_review.html
?? exports/laptop_opportunities_v2_strict_approved.json
?? exports/review_consoles.html
?? exports/review_macbook.html
?? market/management/commands/agent_review_candidates.py
?? market/management/commands/build_enrichment_queries.py
?? market/management/commands/cleanup_laptop_listings.py
?? market/management/commands/recompute_console_opportunities_v1.py
?? market/migrations/0022_laptopopportunitysnapshot.py
?? market/migrations/0023_parsedlistingcandidate_console_specs_json_and_more.py
?? market/services/laptop_quality.py
?? market/services/parsing/console_parser_v2.py
?? market/templates/market/clean_opportunities.html
?? market/views_clean.py
✓ • 1.29s

$ python manage.py shell -c "from market.models import ParsedListingCandidate,ConsoleListing,LaptopListing,PhoneListing; from market.clean_models import PhoneOpportunitySnapshot,LaptopOpportunitySnapshot,ConsoleOpportunitySnapshot; print('candidates portable_console', ParsedListingCandidate.objects.filter(detected_category='portable_console').count()); print('console listings', ConsoleListing.objects.count()); print('console candidate needs_review', ParsedListingCandidate.objects.filter(detected_category='portable_console', status='needs_review').count()); print('phone listings', PhoneListing.objects.count()); print('laptop listings', LaptopListing.objects.count()); print('snapshots phone/laptop/console', PhoneOpportunitySnapshot.objects.count(), LaptopOpportunitySnapshot.objects.count(), ConsoleOpportunitySnapshot.objects.count())"
42 objects imported automatically (use -v 2 for details).

candidates portable_console 17
console listings 11
console candidate needs_review 6
phone listings 1040
laptop listings 925
snapshots phone/laptop/console 36 8 0
✓ • 4.42s

We are not “done-done”, but we are past the blocking cleanup phase and into enrichment.

Current state:
- MacBooks/laptops: gated and usable. Bad/generic laptop rows no longer become buyer-facing deals.
- Opportunities/deals: ported to clean phone/laptop snapshots, with legacy fallback.
- Portable gaming consoles: now have their own lane, not mixed into laptops.

What I just added for consoles:
- `portable_console` candidate category.
- `ConsoleModel`, `ConsoleVariant`, `ConsoleListing`.
- `ConsoleOpportunitySnapshot`.
- Console parser for ROG Ally, Legion Go, Steam Deck, MSI Claw, Switch, Xbox Ally, Portal.
- `export_candidates --category consoles`.
- `recompute_console_opportunities_v1`.
- `build_enrichment_queries`.

Current dataset after reparse:
- Portable console candidates: 17
- Exported clean `ConsoleListing` rows: 11
- Remaining console candidates needing review: 6
- Console opportunities: 0, because we have Algeria console rows but no Türkiye comparison rows yet.
- Phone snapshots: 36
- Laptop snapshots: 8
- Console snapshots: 0

Next enrichment targets generated:

```text
Microsoft Xbox Ally X 24GB 1024GB
ASUS ROG Ally X 24GB 1024GB
Lenovo Legion Go AMD Z1 Extreme 16GB 512GB
Microsoft Xbox Ally 16GB 512GB
ASUS ROG Ally X 1024GB
ASUS ROG Ally AMD Z1 Extreme 16GB 512GB
```

Use these with your CDP flow:
```bash
python manage.py build_enrichment_queries --category consoles --limit 20
python manage.py import_sahibinden_from_cdp --category consoles --query "ASUS ROG Ally X 24GB 1024GB"
python manage.py parse_raw_listings --category consoles --country turkiye --reparse --limit 500
python manage.py export_candidates --category consoles --status pending --limit 500
python manage.py recompute_console_opportunities_v1 --write-snapshots
```

Validation:
- `python manage.py test` passed: 335 tests.
- `python manage.py check` passed.
- `makemigrations --check --dry-run` passed.
- Root opportunities/deals routes return 200.

So the answer to “when can we move to enrichment?” is: now. The blocker is no longer pipeline structure; it is missing Türkiye comparison rows for consoles and still-sparse approved laptop matches.

Worked for 13m 26s

/status

╭─────────────────────────────────────────────────────────────────────────────────╮
│  >_ OpenAI Codex (v0.142.4)                                                     │
│                                                                                 │
│ Visit https://chatgpt.com/codex/settings/usage for up-to-date                   │
│ information on rate limits and credits                                          │
│                                                                                 │
│  Model:                gpt-5.5 (reasoning medium, summaries auto)               │
│  Directory:            ~/DEV/phones                                             │
│  Permissions:          Full Access                                              │
│  Agents.md:            AGENTS.md                                                │
│  Account:              whatsynaptic@gmail.com (Plus)                            │
│  Collaboration mode:   Default                                                  │
│  Session:              019f4922-a139-71a1-a402-d27f17e7de6d                     │
│                                                                                 │
│  Context window:       24% left (200K used / 258K)                              │
│  5h limit:             [░░░░░░░░░░░░░░░░░░░░] 0% left (resets 07:15)            │
│  Weekly limit:         [████████████████░░░░] 82% left (resets 02:15 on 17 Jul) │
╰─────────────────────────────────────────────────────────────────────────────────╯

• Raw output mode on: transcript text is shown for clean terminal selection.

• Raw output mode off: rich transcript rendering restored.

• Raw output mode on: transcript text is shown for clean terminal selection.
 
 
› Explain this codebase
