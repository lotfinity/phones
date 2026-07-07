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
    get_variant_spec_value,
    upsert_listing_specs_from_dict,
    upsert_variant_specs_from_dict,
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


LAPTOP_IDENTITY_WEIGHTS = {
    "gpu_model": 10,
    "cpu_model": 8,
    "ram_gb": 6,
    "ssd_gb": 5,
    "screen_inches": 4,
    "refresh_hz": 3,
}

EXACT_MATCH_THRESHOLD = 20
HIGH_MATCH_THRESHOLD = 12
MEDIUM_MATCH_THRESHOLD = 5


def match_result_to_level(match: MatchResult) -> str:
    """Map a MatchResult to the persisted MarketListing.match_level value."""
    if any("conflict" in r.lower() for r in match.reasons):
        return MarketListing.MatchLevel.CONFLICT

    confidence_to_level = {
        "exact": MarketListing.MatchLevel.EXACT_VARIANT,
        "high": MarketListing.MatchLevel.STRONG_CANDIDATE,
        "medium": MarketListing.MatchLevel.STRONG_CANDIDATE,
        "low": MarketListing.MatchLevel.MODEL_ONLY if match.product_model and not match.variant else MarketListing.MatchLevel.UNMATCHED,
        "none": MarketListing.MatchLevel.UNMATCHED,
    }
    return confidence_to_level.get(match.confidence, MarketListing.MatchLevel.UNMATCHED)


def _compute_laptop_identity_score(specs: dict[str, Any]) -> int:
    score = 0
    for key, weight in LAPTOP_IDENTITY_WEIGHTS.items():
        val = specs.get(key)
        if val is not None and val != "" and val is not False:
            score += weight
    return score


def _has_identity_value(value: Any) -> bool:
    return value is not None and value != "" and value is not False


def _has_conflicting_specs(variant: DeviceVariant, specs: dict[str, Any]) -> bool:
    if not variant or not variant.pk or not variant.product_model or not variant.product_model.product_type:
        return False

    product_type = variant.product_model.product_type
    for key, value in specs.items():
        if not _has_identity_value(value):
            continue
        spec_def = get_spec_definition(product_type, key)
        if not spec_def or not spec_def.is_variant_identity:
            continue
        existing = get_variant_spec_value(variant, key)
        if existing is not None and str(existing).lower() != str(value).lower():
            return True
    return False


def _variant_matches_specs(variant: DeviceVariant, specs: dict[str, Any], product_type: ProductType) -> bool:
    checked = 0
    for spec in product_type.spec_definitions.filter(is_variant_identity=True):
        wanted = specs.get(spec.key)
        if not _has_identity_value(wanted):
            continue
        checked += 1
        existing = get_variant_spec_value(variant, spec.key)
        if existing is None or str(existing).lower() != str(wanted).lower():
            return False
    return checked > 0


def _find_variant_by_spec_values(
    product_model: ProductModel,
    specs: dict[str, Any],
    product_type: ProductType,
) -> DeviceVariant | None:
    for variant in product_model.devicevariant_set.all().prefetch_related("spec_values__spec", "spec_values__option"):
        if _variant_matches_specs(variant, specs, product_type):
            return variant
    return None


def _empty_identity_key(product_type: ProductType) -> str:
    keys = list(
        product_type.spec_definitions.filter(is_variant_identity=True)
        .order_by("sort_order", "key")
        .values_list("key", flat=True)
    )
    return "|".join(f"{key}=" for key in keys)


def _typed_variant_label(product_model: ProductModel, specs: dict[str, Any]) -> str:
    label_parts = [product_model.canonical_name]
    for key in ["gpu_model", "cpu_model", "ram_gb", "ssd_gb"]:
        val = specs.get(key)
        if val:
            label_parts.append(str(val))
    return " ".join(label_parts)[:220]


def _find_or_create_variant(
    product_model: ProductModel,
    specs: dict[str, Any],
    product_type: ProductType | None = None,
    *,
    allow_create: bool = True,
) -> DeviceVariant | None:
    """Find or create a variant based on spec values.

    ``allow_create=False`` is used by dry-run commands. In that mode this
    function may return an unsaved variant placeholder so confidence/level
    reporting still reflects what would happen, but it must not mutate the DB.
    """
    if not product_type and product_model:
        product_type = product_model.product_type

    if not product_type:
        return None

    if product_type.slug == "phone":
        storage_gb = specs.get("storage_gb")
        sim_config = specs.get("sim_config", "")
        if not storage_gb:
            return None

        from market.services.matching import find_existing_variant, get_or_create_variant
        existing = find_existing_variant(product_model, storage_gb=storage_gb, sim_config=sim_config)
        if existing:
            if allow_create:
                upsert_variant_specs_from_dict(existing, {k: v for k, v in specs.items() if k in {"storage_gb", "ram_gb", "sim_config"}})
            return existing

        if not allow_create:
            bits = [product_model.canonical_name, f"{storage_gb}GB"]
            if sim_config:
                bits.append(str(sim_config))
            return DeviceVariant(
                product_model=product_model,
                storage_gb=storage_gb,
                sim_config=sim_config,
                canonical_label=" ".join(bits),
            )

        variant = get_or_create_variant(product_model, storage_gb=storage_gb, sim_config=sim_config)
        upsert_variant_specs_from_dict(variant, {k: v for k, v in specs.items() if k in {"storage_gb", "ram_gb", "sim_config"}})
        return variant

    identity_key = build_variant_identity_from_specs(product_type, specs)
    if not identity_key or identity_key == _empty_identity_key(product_type):
        return None

    variant = _find_variant_by_spec_values(product_model, specs, product_type)
    if variant:
        return variant

    variant = DeviceVariant.objects.filter(product_model=product_model, identity_key=identity_key).first()
    if variant:
        if allow_create:
            upsert_variant_specs_from_dict(variant, specs)
        return variant

    label = _typed_variant_label(product_model, specs)
    if not allow_create:
        return DeviceVariant(
            product_model=product_model,
            canonical_label=label,
            storage_gb=specs.get("ssd_gb") or specs.get("storage_gb"),
            sim_config="",
            identity_key=identity_key,
        )

    variant = DeviceVariant.objects.create(
        product_model=product_model,
        canonical_label=label,
        storage_gb=specs.get("ssd_gb") or specs.get("storage_gb"),
        sim_config="",
    )
    DeviceVariant.objects.filter(pk=variant.pk).update(identity_key=identity_key)
    variant.identity_key = identity_key
    upsert_variant_specs_from_dict(variant, specs)
    return variant


def _product_type_for_matching(
    product_model: ProductModel,
    product_type_slug: str | None,
    *,
    allow_create: bool,
) -> ProductType | None:
    """Resolve product type for scoring without forcing dry-run DB writes."""
    if product_model.product_type:
        return product_model.product_type
    if not product_type_slug:
        return None
    if allow_create:
        return get_or_create_product_type(product_type_slug)
    return ProductType.objects.filter(slug=product_type_slug).first()


def match_listing_to_catalog(
    title: str,
    description: str = "",
    product_type_slug: str | None = None,
    brand_name: str | None = None,
    model_text: str | None = None,
    specs: dict[str, Any] | None = None,
    *,
    allow_create: bool = True,
) -> MatchResult:
    """Progressive matching of a listing against the product catalog.

    Set ``allow_create=False`` for dry-run/inspection paths. That prevents model,
    variant, product_type, and spec-value writes while preserving match scoring.
    """
    from market.services.matching import find_existing_model
    from market.services.normalization import likely_brand

    result = MatchResult()
    specs = specs or {}

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

    if model_text:
        if is_dirty_model_name(model_text):
            result.reasons.append(f"Model name is dirty: {model_text}")
            result.confidence = "low"
            result.confidence_score = 0.2
            return result

        product_model = find_existing_model(model_text)
        if product_model:
            result.product_model = product_model
            result.reasons.append(f"Found existing model: {product_model.canonical_name}")
        elif brand_name:
            if not allow_create:
                result.reasons.append(f"No existing model found for: {model_text}")
                result.confidence = "low"
                result.confidence_score = 0.2
                return result
            from market.services.matching import get_or_create_model
            category_name = "Laptops" if product_type_slug == "laptop" else "Phones"
            product_model = get_or_create_model(model_text, category_name=category_name)
            result.product_model = product_model
            result.reasons.append(f"Created new model: {product_model.canonical_name}")

            if product_type_slug and not product_model.product_type:
                try:
                    pt = get_or_create_product_type(product_type_slug)
                    product_model.product_type = pt
                    product_model.save(update_fields=["product_type"])
                except Exception:
                    logger.exception("Failed setting product_type=%s on model=%s", product_type_slug, product_model.pk)
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

    if result.product_model and specs:
        product_type = _product_type_for_matching(
            result.product_model,
            product_type_slug,
            allow_create=allow_create,
        )
        if product_type:
            variant = _find_or_create_variant(
                result.product_model,
                specs,
                product_type,
                allow_create=allow_create,
            )
            if variant:
                if _has_conflicting_specs(variant, specs):
                    result.reasons.append("Conflicting specs with existing variant")
                    result.confidence = "medium"
                    result.confidence_score = 0.5
                    result.variant = None
                else:
                    result.variant = variant
                    label = variant.canonical_label or "unsaved variant"
                    result.reasons.append(f"Matched variant: {label}")
            else:
                result.reasons.append("Could not match variant (empty identity)")

    if result.product_model and result.variant:
        if product_type_slug == "phone":
            if specs.get("storage_gb"):
                result.confidence = "exact"
                result.confidence_score = 0.95
            else:
                result.confidence = "high"
                result.confidence_score = 0.8
        else:
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
    """Apply a MatchResult to a MarketListing and save spec values."""
    specs_saved = 0
    match_level = match_result_to_level(match)

    if match.product_model:
        listing.product_model = match.product_model
    if match.variant:
        listing.variant = match.variant
        if not listing.storage_gb and match.variant.storage_gb:
            listing.storage_gb = match.variant.storage_gb

    listing.match_level = match_level
    listing.match_confidence = match.confidence_score
    listing.match_reason = "; ".join(match.reasons) if match.reasons else ""

    if match.product_model and not match.product_model.product_type:
        from market.services.spec_extraction import detect_product_type
        detected = detect_product_type(listing.title_raw or "", listing.description_raw or "")
        if detected:
            try:
                pt = get_or_create_product_type(detected)
                match.product_model.product_type = pt
                match.product_model.save(update_fields=["product_type"])
            except Exception:
                logger.exception("Failed setting detected product type on model=%s", match.product_model.pk)

    if specs and match.product_model and match.product_model.product_type:
        saved = upsert_listing_specs_from_dict(listing, specs, confidence=confidence or match.confidence_score)
        specs_saved = len(saved)

    return specs_saved
