"""Progressive matching for listings against product catalog.

Provides tiered matching that handles:
- High confidence: brand + model + strong identity specs = exact variant
- Medium confidence: brand + model + partial specs = candidate variant
- Low confidence: brand + model only = product_model only, variant null
- No match: unknown brand/model = save raw listing only

Matching rules:
- Missing specs never block saving or matching
- Conflicting specs prevent exact variant match
- Laptop identity weights: gpu_model > cpu_model > ram_gb > ssd_gb > screen > refresh
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from market.models import (
    DeviceVariant,
    MarketListing,
    ProductModel,
    ProductType,
)
from market.services.catalog import (
    build_variant_identity_from_specs,
    get_or_create_product_type,
    get_spec_definition,
    upsert_listing_specs_from_dict,
)
from market.services.listing_parser import is_dirty_model_name

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of progressive matching."""
    product_model: ProductModel | None = None
    variant: DeviceVariant | None = None
    confidence: str = "none"  # "exact", "high", "medium", "low", "none"
    confidence_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    specs_saved: int = 0


# Laptop identity weight tiers (higher = more important for matching)
LAPTOP_IDENTITY_WEIGHTS = {
    "gpu_model": 10,
    "cpu_model": 8,
    "ram_gb": 6,
    "ssd_gb": 5,
    "screen_inches": 4,
    "refresh_hz": 3,
}

# Minimum identity spec score for "exact" match
EXACT_MATCH_THRESHOLD = 20
HIGH_MATCH_THRESHOLD = 12
MEDIUM_MATCH_THRESHOLD = 5


def _compute_laptop_identity_score(specs: dict[str, Any]) -> int:
    """Compute a weighted score for laptop identity specs."""
    score = 0
    for key, weight in LAPTOP_IDENTITY_WEIGHTS.items():
        val = specs.get(key)
        if val is not None and val != "" and val != False:
            score += weight
    return score


def _has_conflicting_specs(
    variant: DeviceVariant,
    specs: dict[str, Any],
) -> bool:
    """Check if extracted specs conflict with existing variant specs."""
    if not variant or not variant.product_model or not variant.product_model.product_type:
        return False

    product_type = variant.product_model.product_type
    for key, value in specs.items():
        if value is None or value == "" or value == False:
            continue
        spec_def = get_spec_definition(product_type, key)
        if not spec_def or not spec_def.is_variant_identity:
            continue

        # Read existing value
        from market.services.catalog import get_variant_spec_value
        existing = get_variant_spec_value(variant, key)
        if existing is not None and str(existing).lower() != str(value).lower():
            return True
    return False


def _find_or_create_variant(
    product_model: ProductModel,
    specs: dict[str, Any],
    product_type: ProductType | None = None,
) -> DeviceVariant | None:
    """Find or create a variant based on spec values.

    For phones: uses existing storage_gb/sim_config logic.
    For laptops: builds identity from spec definitions.
    """
    if not product_type and product_model:
        product_type = product_model.product_type

    if not product_type:
        return None

    # For phones, use the existing storage/sim-based variant logic
    if product_type.slug == "phone":
        storage_gb = specs.get("storage_gb")
        sim_config = specs.get("sim_config", "")
        from market.services.matching import get_or_create_variant
        return get_or_create_variant(product_model, storage_gb=storage_gb, sim_config=sim_config)

    # For laptops and other device types, use spec-based identity
    identity_key = build_variant_identity_from_specs(product_type, specs)
    if not identity_key or identity_key == "|".join(
        f"{k}=" for k in sorted(
            [s.key for s in product_type.spec_definitions.filter(is_variant_identity=True)],
        )
    ):
        # All empty identity - no variant match possible
        return None

    # Try to find existing variant
    variant = DeviceVariant.objects.filter(
        product_model=product_model,
        identity_key=identity_key,
    ).first()

    if variant:
        return variant

    # Build canonical label from specs
    label_parts = [product_model.canonical_name]
    for key in ["gpu_model", "cpu_model", "ram_gb", "ssd_gb"]:
        val = specs.get(key)
        if val:
            label_parts.append(str(val))
    label = " ".join(label_parts)[:220]

    variant = DeviceVariant.objects.create(
        product_model=product_model,
        canonical_label=label,
        identity_key=identity_key,
        storage_gb=specs.get("ssd_gb") or specs.get("storage_gb"),
        sim_config="",
    )
    return variant


def match_listing_to_catalog(
    title: str,
    description: str = "",
    product_type_slug: str | None = None,
    brand_name: str | None = None,
    model_text: str | None = None,
    specs: dict[str, Any] | None = None,
) -> MatchResult:
    """Progressive matching of a listing against the product catalog.

    Args:
        title: Listing title.
        description: Listing description.
        product_type_slug: Detected product type or None.
        brand_name: Detected brand or None.
        model_text: Extracted model text or None.
        specs: Extracted specs dict or None.

    Returns:
        MatchResult with product_model, variant, confidence, and reasons.
    """
    from market.services.matching import find_existing_model
    from market.services.normalization import canonical_model_name, likely_brand

    result = MatchResult()
    specs = specs or {}

    # Auto-detect if not provided
    if not brand_name and model_text:
        brand_name = likely_brand(model_text)
    if not brand_name and title:
        brand_name = likely_brand(title)

    if not model_text and title:
        if product_type_slug == "phone":
            from market.services.listing_parser import extract_model_text
            model_text = extract_model_text(title, description)
        elif product_type_slug == "laptop":
            from market.services.spec_extraction import _extract_laptop_model_text
            model_text = _extract_laptop_model_text(title)

    if not product_type_slug:
        from market.services.spec_extraction import detect_product_type
        product_type_slug = detect_product_type(title, description)

    # Step 1: Find or create product model
    if model_text:
        # Check for dirty model names
        if is_dirty_model_name(model_text):
            result.reasons.append(f"Model name is dirty: {model_text}")
            result.confidence = "low"
            result.confidence_score = 0.2
            return result

        # Try to find existing model
        product_model = find_existing_model(model_text)
        if product_model:
            result.product_model = product_model
            result.reasons.append(f"Found existing model: {product_model.canonical_name}")
        else:
            # Create new model if brand is known
            if brand_name:
                from market.services.matching import get_or_create_model
                product_model = get_or_create_model(model_text, category_name="Laptops" if product_type_slug == "laptop" else "Phones")
                result.product_model = product_model
                result.reasons.append(f"Created new model: {product_model.canonical_name}")

                # Set product type if not already set
                if product_type_slug and not product_model.product_type:
                    try:
                        pt = get_or_create_product_type(product_type_slug)
                        product_model.product_type = pt
                        product_model.save(update_fields=["product_type"])
                    except Exception:
                        pass
            else:
                result.reasons.append("No brand detected, cannot create model")
                result.confidence = "low"
                result.confidence_score = 0.15
                return result
    else:
        result.reasons.append("No model text detected")
        result.confidence = "low"
        result.confidence_score = 0.1
        return result

    # Step 2: Find or create variant
    if result.product_model and specs:
        product_type = result.product_model.product_type
        if product_type:
            variant = _find_or_create_variant(result.product_model, specs, product_type)
            if variant:
                # Check for conflicts
                if _has_conflicting_specs(variant, specs):
                    result.reasons.append("Conflicting specs with existing variant")
                    result.confidence = "medium"
                    result.confidence_score = 0.5
                    result.variant = None
                else:
                    result.variant = variant
                    result.reasons.append(f"Matched variant: {variant.canonical_label}")
            else:
                result.reasons.append("Could not match variant (empty identity)")

    # Step 3: Calculate confidence
    if result.product_model and result.variant:
        # Exact or high confidence
        identity_score = _compute_laptop_identity_score(specs) if product_type_slug == "laptop" else 0
        if identity_score >= EXACT_MATCH_THRESHOLD:
            result.confidence = "exact"
            result.confidence_score = 0.95
        elif identity_score >= HIGH_MATCH_THRESHOLD:
            result.confidence = "high"
            result.confidence_score = 0.85
        elif identity_score >= MEDIUM_MATCH_THRESHOLD:
            result.confidence = "medium"
            result.confidence_score = 0.7
        else:
            # Phone variant match
            storage = specs.get("storage_gb")
            sim = specs.get("sim_config")
            if storage and sim:
                result.confidence = "high"
                result.confidence_score = 0.8
            elif storage:
                result.confidence = "medium"
                result.confidence_score = 0.65
            else:
                result.confidence = "low"
                result.confidence_score = 0.4
    elif result.product_model:
        result.confidence = "low"
        result.confidence_score = 0.3
    else:
        result.confidence = "none"
        result.confidence_score = 0.0

    return result


def apply_match_to_listing(
    listing: MarketListing,
    match: MatchResult,
    specs: dict[str, Any] | None = None,
    confidence: float = 0,
) -> int:
    """Apply a MatchResult to a MarketListing and save spec values.

    Persists match_level, match_confidence, and match_reason on the listing.
    Returns the number of spec values saved.
    """
    from market.models import MarketListing as ML

    specs_saved = 0

    # Map MatchResult.confidence string to MatchLevel
    confidence_to_level = {
        "exact": ML.MatchLevel.EXACT_VARIANT,
        "high": ML.MatchLevel.STRONG_CANDIDATE,
        "medium": ML.MatchLevel.STRONG_CANDIDATE,
        "low": ML.MatchLevel.MODEL_ONLY if match.product_model and not match.variant else ML.MatchLevel.UNMATCHED,
        "none": ML.MatchLevel.UNMATCHED,
    }
    # Check for conflict
    if any("conflict" in r.lower() for r in match.reasons):
        match_level = ML.MatchLevel.CONFLICT
    else:
        match_level = confidence_to_level.get(match.confidence, ML.MatchLevel.UNMATCHED)

    # Set product model and variant
    if match.product_model:
        listing.product_model = match.product_model
    if match.variant:
        listing.variant = match.variant

    # Set match quality fields
    listing.match_level = match_level
    listing.match_confidence = match.confidence_score
    listing.match_reason = "; ".join(match.reasons) if match.reasons else ""

    # Set product type on listing's product model if not set
    if match.product_model and not match.product_model.product_type:
        from market.services.spec_extraction import detect_product_type
        detected = detect_product_type(listing.title_raw or "", listing.description_raw or "")
        if detected:
            try:
                pt = get_or_create_product_type(detected)
                match.product_model.product_type = pt
                match.product_model.save(update_fields=["product_type"])
            except Exception:
                pass

    # Save spec values
    if specs and match.product_model and match.product_model.product_type:
        saved = upsert_listing_specs_from_dict(
            listing,
            specs,
            confidence=confidence or match.confidence_score,
        )
        specs_saved = len(saved)

    return specs_saved
