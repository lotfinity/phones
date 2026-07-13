"""Build ParsedListingCandidate from a RawListing using phone/laptop parsers."""

import re
from decimal import Decimal, InvalidOperation

from market.models import (
    Brand,
    ParsedListingCandidate,
    RawListing,
)
from market.services.currency import convert_to_eur
from market.services.laptop_quality import (
    clean_model_key,
    is_garbage_laptop_model_name,
    is_generic_laptop_model_name,
    has_laptop_export_identity,
)
from market.services.parsing.phone_parser_v2 import parse_phone
from market.services.parsing.laptop_parser_v2 import parse_laptop
from market.services.parsing.console_parser_v2 import is_portable_console_text, parse_console

PARSER_VERSION = "v2.4"


# ── URL / title-based category detection ────────────────────────────────────
# Strong laptop URL signals (Ouedkniss slug patterns + Sahibinden Turkish paths).
_LAPTOP_URL_PATTERNS = re.compile(
    r"/laptop-|/macbooks-|/computer-|/dizustu-notebook-|/bilgisayar-dizustu-",
    re.IGNORECASE,
)

# Accessory / reject URL patterns.
_ACCESSORY_URL_PATTERNS = re.compile(
    r"/keyboard-mouse-|/screens-|/headphones-|/school-bag|/pockets-cases|"
    r"/charger|/chargers|/software|/consoles|/pens-|/accessories-|"
    r"/shockproof-cases|/other-",
    re.IGNORECASE,
)

# Strong laptop keywords in title/text.
_LAPTOP_TITLE_KEYWORDS = re.compile(
    r"\b(laptop|notebook|macbook|legion|thinkpad|ideapad|loq|"
    r"asus\s*tuf|\brog\b|victus|elitebook|probook|dell\s*latitude|"
    r"dell\s*xps|\bmsi\b|acer\s*nitro|predator|hp\s*omen)\b",
    re.IGNORECASE,
)

# Laptop-only brands: these are NEVER phone brands, so their presence in title
# strongly indicates a laptop listing even without other keywords.
_LAPTOP_ONLY_BRANDS = re.compile(
    r"\b(dell|msi|razer|gigabyte)\b",
    re.IGNORECASE,
)

# Accessory / reject keywords in title/text.
_ACCESSORY_TITLE_KEYWORDS = re.compile(
    r"\b(souris|clavier|casque|chargeur|housse|pochette|coque|sac|"
    r"cartable|\b(ecran|écran)\b|stylus|\bpen\b|office\s*365|"
    r"software|console|gaming\s*mouse|keyboard)\b",
    re.IGNORECASE,
)

# Laptop brand keywords that, combined with price/specs, indicate laptop.
_LAPTOP_BRAND_KEYWORDS = re.compile(
    r"\b(lenovo|asus|dell|hp|acer|msi|apple|razer|gigabyte|huawei|microsoft)\b",
    re.IGNORECASE,
)

# Detect MacBook family directly from raw URL/title text before noisy grid/table
# metadata can leak tokens like `gpu ram gb storage gb` into model_text.
_MACBOOK_MODEL_RE = re.compile(r"\bmac\s*book\b|\bmacbook\b", re.IGNORECASE)
_MACBOOK_FAMILY_RE = re.compile(
    r"\bmac\s*book\s*(air|pro)?(?:\s*(?:13|14|15|16)(?:\s*(?:inch|in|\"))?)?"
    r"(?:\s*(m[1-4])\s*(pro|max|ultra)?)?\b",
    re.IGNORECASE,
)


def detect_category_from_signals(url="", title=""):
    """Detect category from URL and title signals.

    Returns one of: 'laptop', 'portable_console', 'accessory', or '' (no strong signal).
    This is used to override category_hint when URL/title provide
    strong evidence that contradicts the hint.
    """
    url_lower = (url or "").lower()
    title_lower = (title or "").lower()
    combined = f"{url_lower} {title_lower}"

    # 1. Strong URL signals override almost everything.
    if is_portable_console_text(combined):
        return "portable_console"
    if _ACCESSORY_URL_PATTERNS.search(url_lower):
        return "accessory"
    if _LAPTOP_URL_PATTERNS.search(url_lower):
        # Even if title has accessory words, URL /laptop- is definitive.
        return "laptop"

    # 2. Title-based accessory detection.
    if _ACCESSORY_TITLE_KEYWORDS.search(title_lower):
        return "accessory"

    if is_portable_console_text(title_lower):
        return "portable_console"

    # 3. Title-based laptop detection.
    if _LAPTOP_TITLE_KEYWORDS.search(title_lower):
        return "laptop"

    # 4. Laptop-only brands (Dell, MSI, Razer, Gigabyte) are never phone brands.
    if _LAPTOP_ONLY_BRANDS.search(title_lower):
        return "laptop"

    return ""


def _legacy_price(payload):
    price = payload.get("legacy_price_original")
    currency = payload.get("legacy_currency") or payload.get("legacy_currency_original") or ""
    if price in (None, ""):
        return None, currency, None
    try:
        amount = Decimal(str(price))
    except (InvalidOperation, TypeError):
        return None, currency, None
    return amount, currency, convert_to_eur(amount, currency)


def _clean_model_key(value):
    return clean_model_key(value)


def _looks_like_garbage_model(model_text):
    return is_garbage_laptop_model_name(model_text)


def _extract_macbook_model_from_text(text):
    text = text or ""
    normalized = re.sub(r"\bmacbooks[-_/\s]+", "", text, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_/]+", " ", normalized)
    if not _MACBOOK_MODEL_RE.search(normalized):
        return ""
    matches = list(_MACBOOK_FAMILY_RE.finditer(normalized))
    if not matches:
        return "MacBook"
    match = max(
        matches,
        key=lambda m: (
            bool(m.group(1)),
            bool(m.group(2)),
            len(m.group(0)),
        ),
    )
    family = (match.group(1) or "").lower()
    chip = (match.group(2) or "").upper()
    chip_suffix = (match.group(3) or "").title()
    bits = ["MacBook"]
    if family:
        bits.append(family.title())
    if chip:
        bits.append(chip)
    if chip_suffix:
        bits.append(chip_suffix)
    return " ".join(bits).strip()


def _repair_laptop_result(result, raw_listing):
    """Repair obvious parser failures and lower confidence for weak laptop IDs."""
    if not result:
        return result

    raw_text = "\n".join(
        part for part in [
            raw_listing.title_raw or "",
            raw_listing.raw_text or "",
            raw_listing.listing_url or "",
        ]
        if part
    )
    brand = result.get("brand_text", "")
    model_text = result.get("model_text", "")
    series = result.get("series", "")
    macbook_model = _extract_macbook_model_from_text(raw_text)

    if macbook_model:
        brand = "Apple"
        result["brand_text"] = "Apple"
        model_text = macbook_model
        result["model_text"] = macbook_model
        # Apple Silicon is part of the commercial MacBook identity.
        if not result.get("cpu"):
            chip_match = re.search(r"\b(M[1-4])\s*(Pro|Max|Ultra)?\b", macbook_model, re.IGNORECASE)
            if chip_match:
                suffix = f" {chip_match.group(2).title()}" if chip_match.group(2) else ""
                result["cpu"] = f"Apple {chip_match.group(1).upper()}{suffix}"

    if _looks_like_garbage_model(model_text):
        model_text = series or ""
        result["model_text"] = model_text

    cleaned_model = _clean_model_key(result.get("model_text", ""))
    has_variant_specs = any(
        result.get(field)
        for field in ("cpu", "gpu", "ram_gb", "storage_gb")
    )
    if is_generic_laptop_model_name(cleaned_model) and not has_variant_specs:
        # Generic family-only rows are useful leads, not safe opportunity inputs.
        result["confidence"] = min(result.get("confidence", 0.0), 0.55)
    elif _looks_like_garbage_model(result.get("model_text", "")):
        result["confidence"] = min(result.get("confidence", 0.0), 0.45)

    return result


def build_candidate(raw_listing):
    """Parse a RawListing and create/update a ParsedListingCandidate."""
    payload = raw_listing.raw_payload or {}

    phone_result = None
    laptop_result = None
    console_result = None

    hint = raw_listing.category_hint

    # Signal-based override: URL/title can override category_hint.
    url = raw_listing.listing_url or ""
    title = raw_listing.title_raw or ""
    signal_category = detect_category_from_signals(url, title)

    if signal_category == "portable_console":
        console_result = parse_console(raw_listing.raw_text, raw_listing.title_raw, payload)
        result = console_result
        detected_category = ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE
    elif signal_category == "laptop":
        # Force laptop parsing regardless of hint.
        laptop_result = parse_laptop(raw_listing.raw_text, raw_listing.title_raw, payload)
        laptop_result = _repair_laptop_result(laptop_result, raw_listing)
        # Also run phone parser so we can compare confidence if needed.
        phone_result = parse_phone(raw_listing.raw_text, raw_listing.title_raw, payload)
        # If laptop has any meaningful confidence, prefer it.
        if laptop_result and (
            laptop_result["confidence"] >= 0.3
            or laptop_result.get("brand_text")
            or laptop_result.get("model_text")
        ):
            result = laptop_result
            detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
        elif phone_result and (not laptop_result or phone_result["confidence"] > laptop_result["confidence"]):
            result = phone_result
            detected_category = ParsedListingCandidate.DetectedCategory.PHONE
        else:
            result = laptop_result
            detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
    elif signal_category == "accessory":
        # Run both parsers but mark as UNKNOWN (not phone, not laptop).
        phone_result = parse_phone(raw_listing.raw_text, raw_listing.title_raw, payload)
        laptop_result = parse_laptop(raw_listing.raw_text, raw_listing.title_raw, payload)
        laptop_result = _repair_laptop_result(laptop_result, raw_listing)
        # Pick the higher confidence result for field extraction, but category stays UNKNOWN.
        if phone_result and laptop_result:
            result = phone_result if phone_result["confidence"] >= laptop_result["confidence"] else laptop_result
        elif phone_result:
            result = phone_result
        elif laptop_result:
            result = laptop_result
        else:
            result = None
        detected_category = ParsedListingCandidate.DetectedCategory.UNKNOWN
    else:
        # No strong signal — use original hint-based logic.
        if hint in (RawListing.CategoryHint.PHONES, RawListing.CategoryHint.UNKNOWN):
            phone_result = parse_phone(raw_listing.raw_text, raw_listing.title_raw, payload)

        if hint in (RawListing.CategoryHint.LAPTOPS, RawListing.CategoryHint.UNKNOWN):
            laptop_result = parse_laptop(raw_listing.raw_text, raw_listing.title_raw, payload)
            laptop_result = _repair_laptop_result(laptop_result, raw_listing)

        if hint in (
            RawListing.CategoryHint.CONSOLES,
            RawListing.CategoryHint.UNKNOWN,
            RawListing.CategoryHint.LAPTOPS,
        ):
            maybe_console = parse_console(raw_listing.raw_text, raw_listing.title_raw, payload)
            if maybe_console and (maybe_console.get("brand_text") or maybe_console.get("model_text")):
                console_result = maybe_console

        if hint == RawListing.CategoryHint.PHONES:
            result = phone_result
            detected_category = ParsedListingCandidate.DetectedCategory.PHONE
        elif hint == RawListing.CategoryHint.LAPTOPS:
            if console_result and console_result.get("confidence", 0) >= 0.5:
                result = console_result
                detected_category = ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE
            else:
                result = laptop_result
                detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
        elif hint == RawListing.CategoryHint.CONSOLES:
            if console_result:
                result = console_result
                detected_category = ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE
            else:
                result = None
                detected_category = ParsedListingCandidate.DetectedCategory.UNKNOWN
        else:
            choices = []
            if phone_result:
                choices.append((phone_result["confidence"], phone_result, ParsedListingCandidate.DetectedCategory.PHONE))
            if laptop_result:
                choices.append((laptop_result["confidence"], laptop_result, ParsedListingCandidate.DetectedCategory.LAPTOP))
            if console_result:
                choices.append((console_result["confidence"], console_result, ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE))
            if choices:
                _confidence, result, detected_category = max(choices, key=lambda item: item[0])
            elif phone_result:
                result = phone_result
                detected_category = ParsedListingCandidate.DetectedCategory.PHONE
            elif laptop_result:
                result = laptop_result
                detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
            else:
                result = None
                detected_category = ParsedListingCandidate.DetectedCategory.UNKNOWN

    if result is None:
        result = {
            "brand_text": "",
            "model_text": "",
            "condition": "unknown",
            "price_original": None,
            "currency_original": "",
            "price_eur": None,
            "segments": [],
            "confidence": 0.0,
        }

    legacy_price, legacy_currency, legacy_price_eur = _legacy_price(payload)
    if legacy_price is not None:
        # Backfilled MarketListing rows already have trusted normalized prices.
        # Prefer them over text parser guesses like `79.50 TRY` from `79.500 TL`.
        price_original = legacy_price
        currency_original = legacy_currency
        price_eur = legacy_price_eur
    else:
        price_original = result.get("price_original")
        currency_original = result.get("currency_original") or ""
        price_eur = result.get("price_eur")

    if price_eur is None and price_original is not None and currency_original:
        price_eur = convert_to_eur(price_original, currency_original)

    confidence = result.get("confidence", 0.0)
    brand_text = result.get("brand_text", "")
    model_text = result.get("model_text", "")

    if detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP and not has_laptop_export_identity(
        model_name=model_text,
        cpu=result.get("cpu", ""),
        gpu=result.get("gpu", ""),
        ram_gb=result.get("ram_gb"),
        storage_gb=result.get("storage_gb"),
        variant=None,
        confidence=confidence,
    ):
        status = ParsedListingCandidate.Status.NEEDS_REVIEW
    elif confidence < 0.65:
        status = ParsedListingCandidate.Status.NEEDS_REVIEW
    elif not brand_text or not model_text:
        status = ParsedListingCandidate.Status.NEEDS_REVIEW
    elif price_original is None:
        status = ParsedListingCandidate.Status.NEEDS_REVIEW
    elif confidence >= 0.90:
        status = ParsedListingCandidate.Status.PENDING
    else:
        status = ParsedListingCandidate.Status.PENDING

    matched_brand = None
    if brand_text:
        matched_brand = Brand.objects.filter(
            name__iexact=brand_text
        ).first()
        if not matched_brand:
            for b in Brand.objects.exclude(aliases=[]).iterator():
                if brand_text.lower() in [a.lower() for a in (b.aliases or [])]:
                    matched_brand = b
                    break

    phone_specs = {}
    laptop_specs = {}
    console_specs = {}

    if detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
        phone_specs = {
            "storage_gb": result.get("storage_gb"),
            "ram_gb": result.get("ram_gb"),
            "sim_config": result.get("sim_config", ""),
            "battery_health": result.get("battery_health"),
            "battery_cycles": result.get("battery_cycles"),
            "box_status": result.get("box_status", ""),
            "store_warranty": result.get("store_warranty", ""),
            "color": result.get("color", ""),
        }
    elif detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
        laptop_specs = {
            "cpu": result.get("cpu", ""),
            "gpu": result.get("gpu", ""),
            "ram_gb": result.get("ram_gb"),
            "storage_gb": result.get("storage_gb"),
            "screen_size": result.get("screen_size"),
            "resolution": result.get("resolution", ""),
            "refresh_rate_hz": result.get("refresh_rate_hz"),
            "panel_type": result.get("panel_type", ""),
            "series": result.get("series", ""),
        }
    elif detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
        console_specs = {
            "chipset": result.get("chipset", ""),
            "ram_gb": result.get("ram_gb"),
            "storage_gb": result.get("storage_gb"),
            "screen_size": result.get("screen_size"),
            "refresh_rate_hz": result.get("refresh_rate_hz"),
            "connectivity": result.get("connectivity", ""),
            "color": result.get("color", ""),
        }

    candidate, created = ParsedListingCandidate.objects.update_or_create(
        raw_listing=raw_listing,
        defaults={
            "detected_category": detected_category,
            "brand_text": brand_text,
            "model_text": model_text,
            "variant_text": result.get("variant_text", ""),
            "price_original": price_original,
            "currency_original": currency_original,
            "price_eur": price_eur,
            "condition": result.get("condition", "unknown"),
            "phone_specs_json": phone_specs,
            "laptop_specs_json": laptop_specs,
            "console_specs_json": console_specs,
            "detected_segments_json": result.get("segments", []),
            "confidence": confidence,
            "parser_version": PARSER_VERSION,
            "matched_brand": matched_brand,
            "status": status,
        },
    )

    raw_listing.parse_status = (
        RawListing.ParseStatus.NEEDS_REVIEW
        if status == ParsedListingCandidate.Status.NEEDS_REVIEW
        else RawListing.ParseStatus.PARSED
    )
    raw_listing.save(update_fields=["parse_status"])

    return candidate, created
