"""Build ParsedListingCandidate from a RawListing using phone/laptop parsers."""

from decimal import Decimal

from market.models import (
    Brand,
    ParsedListingCandidate,
    RawListing,
)
from market.services.parsing.phone_parser_v2 import parse_phone
from market.services.parsing.laptop_parser_v2 import parse_laptop

PARSER_VERSION = "v2.0"


def build_candidate(raw_listing):
    """Parse a RawListing and create/update a ParsedListingCandidate."""
    text = raw_listing.raw_text or raw_listing.title_raw or ""
    payload = raw_listing.raw_payload or {}

    phone_result = None
    laptop_result = None

    hint = raw_listing.category_hint

    if hint in (RawListing.CategoryHint.PHONES, RawListing.CategoryHint.UNKNOWN):
        phone_result = parse_phone(raw_listing.raw_text, raw_listing.title_raw, payload)

    if hint in (RawListing.CategoryHint.LAPTOPS, RawListing.CategoryHint.UNKNOWN):
        laptop_result = parse_laptop(raw_listing.raw_text, raw_listing.title_raw, payload)

    if hint == RawListing.CategoryHint.PHONES:
        result = phone_result
        detected_category = ParsedListingCandidate.DetectedCategory.PHONE
    elif hint == RawListing.CategoryHint.LAPTOPS:
        result = laptop_result
        detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
    else:
        if phone_result and laptop_result:
            if phone_result["confidence"] >= laptop_result["confidence"]:
                result = phone_result
                detected_category = ParsedListingCandidate.DetectedCategory.PHONE
            else:
                result = laptop_result
                detected_category = ParsedListingCandidate.DetectedCategory.LAPTOP
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
            "segments": [],
            "confidence": 0.0,
        }

    confidence = result.get("confidence", 0.0)
    brand_text = result.get("brand_text", "")
    model_text = result.get("model_text", "")
    price_original = result.get("price_original")

    if confidence < 0.65:
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

    if detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
        phone_specs = {
            "storage_gb": result.get("storage_gb"),
            "ram_gb": result.get("ram_gb"),
            "sim_config": result.get("sim_config", ""),
            "battery_health": result.get("battery_health"),
            "battery_cycles": result.get("battery_cycles"),
            "box_status": result.get("box_status", ""),
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
        }

    candidate, created = ParsedListingCandidate.objects.update_or_create(
        raw_listing=raw_listing,
        defaults={
            "detected_category": detected_category,
            "brand_text": brand_text,
            "model_text": model_text,
            "variant_text": result.get("variant_text", ""),
            "price_original": price_original,
            "currency_original": result.get("currency_original", ""),
            "condition": result.get("condition", "unknown"),
            "phone_specs_json": phone_specs,
            "laptop_specs_json": laptop_specs,
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
