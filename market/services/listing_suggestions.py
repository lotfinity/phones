import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from market.models import Condition, DeviceVariant, MarketListing, ProductModel, normalize_sim_config
from market.services.listing_parser import (
    extract_model_text,
    is_accessory_title,
    is_dirty_model_name,
    listing_review_status,
    parse_condition,
    parse_sim_config,
    parse_storage_ram,
)
from market.services.matching import SUPPORTED_STORAGE_GB, find_existing_variant
from market.services.normalization import canonical_model_name, normalize_text


@dataclass
class ModelMatch:
    product_model: ProductModel | None
    confidence: float
    reason: str
    detected_text: str


@dataclass
class ListingFixSuggestion:
    product_model: ProductModel | None
    storage_gb: int | None
    sim_config: str
    condition: str
    confidence: float
    reason: str
    evidence: dict


def _compact(value):
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value).lower())


def _model_candidates():
    rows = []
    for model in ProductModel.objects.select_related("brand").order_by("canonical_name"):
        if is_dirty_model_name(model.canonical_name):
            continue
        if not model.brand or model.brand.name == "Unknown":
            continue
        names = [model.canonical_name, *(model.aliases or [])]
        brand = model.brand.name if model.brand else ""
        for name in names:
            if not name:
                continue
            rows.append((model, name, canonical_model_name(name), _compact(name), brand))
            if brand and not normalize_text(name).lower().startswith(normalize_text(brand).lower()):
                branded = f"{brand} {name}"
                rows.append((model, branded, canonical_model_name(branded), _compact(branded), brand))
    return rows


def match_existing_model(text):
    detected = extract_model_text(text)
    if not detected:
        return ModelMatch(None, 0, "No model text detected.", "")

    detected_canonical = canonical_model_name(detected)
    detected_compact = _compact(detected_canonical)
    if not detected_compact:
        return ModelMatch(None, 0, "No usable model text detected.", detected)

    best = None
    for model, candidate, candidate_canonical, candidate_compact, _brand in _model_candidates():
        if not candidate_compact:
            continue
        if detected_compact == candidate_compact:
            return ModelMatch(model, 0.96, f"Exact model match on '{candidate}'.", detected)
        if detected_compact in candidate_compact or candidate_compact in detected_compact:
            score = 0.9 if min(len(detected_compact), len(candidate_compact)) >= 6 else 0.72
        else:
            score = SequenceMatcher(None, detected_compact, candidate_compact).ratio()
        if best is None or score > best[0]:
            best = (score, model, candidate_canonical)

    if best and best[0] >= 0.84:
        return ModelMatch(best[1], round(best[0], 2), f"Fuzzy model match on '{best[2]}'.", detected)

    return ModelMatch(None, round(best[0], 2) if best else 0, "No existing model matched confidently.", detected)


def build_listing_suggestion(listing, extra_text=""):
    text_parts = [
        listing.title_raw or "",
        listing.description_raw or "",
        extra_text or "",
    ]
    text = "\n".join(part for part in text_parts if part).strip()
    if not text:
        return ListingFixSuggestion(None, None, "", "", 0, "Listing has no text to inspect.", {"text": ""})

    if is_accessory_title(text):
        return ListingFixSuggestion(
            listing.product_model,
            listing.storage_gb,
            listing.sim_config,
            listing.condition,
            0.1,
            "Looks like an accessory, not a phone listing.",
            {"text": text[:1200]},
        )

    model_match = match_existing_model(text)
    existing_model_is_clean = (
        listing.product_model
        and not is_dirty_model_name(listing.product_model.canonical_name)
        and listing.product_model.brand
        and listing.product_model.brand.name != "Unknown"
    )
    product_model = model_match.product_model or (listing.product_model if existing_model_is_clean else None)
    parsed_storage, parsed_ram = parse_storage_ram(text)
    storage_gb = parsed_storage if parsed_storage in SUPPORTED_STORAGE_GB else listing.storage_gb
    sim_config = normalize_sim_config(parse_sim_config(text) or listing.sim_config)
    condition = parse_condition(text)
    if condition == Condition.UNKNOWN and listing.condition:
        condition = listing.condition

    evidence = {
        "detected_model_text": model_match.detected_text,
        "model_match_reason": model_match.reason,
        "parsed_storage_gb": parsed_storage,
        "parsed_ram_gb": parsed_ram,
        "parsed_sim_config": sim_config,
        "parsed_condition": condition,
        "text_excerpt": text[:1200],
        "extra_text_used": bool(extra_text),
    }

    score_parts = []
    if product_model:
        score_parts.append(model_match.confidence if model_match.product_model else 0.55)
    if storage_gb:
        score_parts.append(0.92)
    if sim_config:
        score_parts.append(0.72)
    if condition and condition != Condition.UNKNOWN:
        score_parts.append(0.7)
    confidence = sum(score_parts) / len(score_parts) if score_parts else 0

    reason_bits = [model_match.reason]
    if storage_gb:
        reason_bits.append(f"Storage parsed as {storage_gb}GB.")
    else:
        reason_bits.append("Storage still unknown.")
    if sim_config:
        reason_bits.append(f"SIM parsed as {sim_config}.")
    if condition and condition != Condition.UNKNOWN:
        reason_bits.append(f"Condition parsed as {Condition(condition).label}.")
    if listing_review_status(listing.price_original, product_model, storage_gb) == MarketListing.ReviewStatus.AUTO:
        reason_bits.append("Would become usable for opportunity analysis after approval.")

    return ListingFixSuggestion(
        product_model=product_model,
        storage_gb=storage_gb,
        sim_config=sim_config,
        condition=condition,
        confidence=round(confidence, 2),
        reason=" ".join(reason_bits),
        evidence=evidence,
    )


def apply_listing_suggestion(suggestion):
    listing = suggestion.listing
    if suggestion.suggested_product_model_id:
        listing.product_model = suggestion.suggested_product_model
    if suggestion.suggested_storage_gb:
        listing.storage_gb = suggestion.suggested_storage_gb
    if suggestion.suggested_sim_config:
        listing.sim_config = suggestion.suggested_sim_config
    if suggestion.suggested_condition:
        listing.condition = suggestion.suggested_condition
    listing.variant = find_existing_variant(
        listing.product_model,
        storage_gb=listing.storage_gb,
        sim_config=listing.sim_config,
    )
    listing.review_status = (
        MarketListing.ReviewStatus.APPROVED
        if listing.price_original and listing.product_model_id and listing.storage_gb
        else MarketListing.ReviewStatus.NEEDS_REVIEW
    )
    listing.parsed_confidence = max(listing.parsed_confidence or 0, suggestion.confidence)
    listing.save()
    suggestion.status = suggestion.Status.APPLIED
    suggestion.save(update_fields=["status", "updated_at"])
    return listing
