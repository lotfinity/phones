"""Generic typed spec system helpers.

Provides functions for creating, normalizing, and upserting spec values
on ProductVariants and MarketListings. Supports building identity keys
from variant-level spec definitions.
"""

from __future__ import annotations

from typing import Any

from market.models import (
    DeviceVariant,
    MarketListing,
    MarketListingSpecValue,
    ProductType,
    ProductVariantSpecValue,
    SpecDefinition,
    SpecOption,
)


def get_or_create_product_type(slug: str, name: str = "", description: str = "") -> ProductType:
    """Get or create a ProductType by slug."""
    defaults = {"name": name or slug.replace("-", " ").title()}
    if description:
        defaults["description"] = description
    pt, _ = ProductType.objects.get_or_create(slug=slug, defaults=defaults)
    return pt


def get_spec_definition(product_type: ProductType, key: str) -> SpecDefinition | None:
    """Get a SpecDefinition by product type and key."""
    return SpecDefinition.objects.filter(product_type=product_type, key=key).first()


def _coerce_integer(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_decimal(value: Any):
    from decimal import Decimal, InvalidOperation

    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_spec_value(spec: SpecDefinition, raw_value: Any) -> dict[str, Any]:
    """Normalize a raw value into typed fields for a spec value row.

    Returns a dict with keys: option, value_text, value_integer, value_decimal,
    value_boolean.  The caller should save the result onto the appropriate
    spec value model.
    """
    result: dict[str, Any] = {
        "option": None,
        "value_text": "",
        "value_integer": None,
        "value_decimal": None,
        "value_boolean": None,
    }

    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        return result

    raw_str = str(raw_value).strip()

    if spec.value_type == SpecDefinition.ValueType.BOOLEAN:
        result["value_boolean"] = raw_str.lower() in ("true", "1", "yes", "on")
        return result

    if spec.value_type == SpecDefinition.ValueType.INTEGER:
        result["value_integer"] = _coerce_integer(raw_value)
        return result

    if spec.value_type == SpecDefinition.ValueType.DECIMAL:
        result["value_decimal"] = _coerce_decimal(raw_value)
        return result

    if spec.value_type in (SpecDefinition.ValueType.OPTION, SpecDefinition.ValueType.MULTI_OPTION):
        normalized = raw_str.lower().strip()
        option = SpecOption.objects.filter(
            spec=spec,
            normalized_value=normalized,
        ).first()
        if not option:
            for alias_opt in SpecOption.objects.filter(spec=spec):
                if normalized in [a.lower() for a in (alias_opt.aliases or [])]:
                    option = alias_opt
                    break
        if option:
            result["option"] = option
            result["value_text"] = option.value
        else:
            result["value_text"] = raw_str
        return result

    result["value_text"] = raw_str
    return result


def upsert_variant_spec_value(
    variant: DeviceVariant,
    key: str,
    value: Any,
    raw_value: str = "",
    confidence: float = 0,
) -> ProductVariantSpecValue | None:
    """Upsert a single spec value on a DeviceVariant.

    Looks up the SpecDefinition by the variant's product model's product type.
    If the product type or spec definition is missing, returns None silently.
    """
    product_type = (
        variant.product_model.product_type if variant.product_model and variant.product_model.product_type else None
    )
    if not product_type:
        return None

    spec = get_spec_definition(product_type, key)
    if not spec:
        return None

    normalized = normalize_spec_value(spec, value)
    raw_value = raw_value or (str(value) if value is not None else "")

    obj, _created = ProductVariantSpecValue.objects.update_or_create(
        variant=variant,
        spec=spec,
        defaults={
            "option": normalized["option"],
            "value_text": normalized["value_text"],
            "value_integer": normalized["value_integer"],
            "value_decimal": normalized["value_decimal"],
            "value_boolean": normalized["value_boolean"],
            "raw_value": raw_value,
        },
    )
    return obj


def upsert_listing_spec_value(
    listing: MarketListing,
    key: str,
    value: Any,
    raw_value: str = "",
    confidence: float = 0,
) -> MarketListingSpecValue | None:
    """Upsert a single spec value on a MarketListing.

    Looks up the SpecDefinition via the listing's product model's product type.
    """
    product_type = (
        listing.product_model.product_type
        if listing.product_model and listing.product_model.product_type
        else None
    )
    if not product_type:
        return None

    spec = get_spec_definition(product_type, key)
    if not spec:
        return None

    normalized = normalize_spec_value(spec, value)
    raw_value = raw_value or (str(value) if value is not None else "")

    obj, _created = MarketListingSpecValue.objects.update_or_create(
        listing=listing,
        spec=spec,
        defaults={
            "option": normalized["option"],
            "value_text": normalized["value_text"],
            "value_integer": normalized["value_integer"],
            "value_decimal": normalized["value_decimal"],
            "value_boolean": normalized["value_boolean"],
            "raw_value": raw_value,
            "confidence": confidence,
        },
    )
    return obj


def build_variant_identity_from_specs(
    product_type: ProductType,
    spec_values: dict[str, Any],
) -> str:
    """Build a deterministic identity key from variant-level spec values.

    Only specs with ``is_variant_identity=True`` participate in the key.
    Specs are sorted by sort_order then key.  The result is a pipe-delimited
    string like ``cpu_model=Intel Core i7-13700H|gpu_model=NVIDIA RTX 4060|ram_gb=16|ssd_gb=512``.
    """
    identity_specs = (
        SpecDefinition.objects.filter(
            product_type=product_type,
            is_variant_identity=True,
        )
        .order_by("sort_order", "key")
    )

    parts = []
    for spec in identity_specs:
        raw = spec_values.get(spec.key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            parts.append(f"{spec.key}=")
            continue
        normalized = normalize_spec_value(spec, raw)
        display = ""
        if normalized["option"]:
            display = normalized["option"].value
        elif normalized["value_integer"] is not None:
            display = str(normalized["value_integer"])
        elif normalized["value_decimal"] is not None:
            display = str(normalized["value_decimal"])
        elif normalized["value_boolean"] is not None:
            display = str(normalized["value_boolean"])
        else:
            display = normalized.get("value_text", "")
        parts.append(f"{spec.key}={display}")

    return "|".join(parts)


def upsert_variant_specs_from_dict(
    variant: DeviceVariant,
    specs: dict[str, Any],
    raw_values: dict[str, str] | None = None,
    confidence: float = 0,
) -> list[ProductVariantSpecValue]:
    """Convenience: upsert multiple spec values from a dict keyed by spec key."""
    raw_values = raw_values or {}
    results = []
    for key, value in specs.items():
        obj = upsert_variant_spec_value(
            variant,
            key,
            value,
            raw_value=raw_values.get(key, ""),
            confidence=confidence,
        )
        if obj:
            results.append(obj)
    return results


def upsert_listing_specs_from_dict(
    listing: MarketListing,
    specs: dict[str, Any],
    raw_values: dict[str, str] | None = None,
    confidence: float = 0,
) -> list[MarketListingSpecValue]:
    """Convenience: upsert multiple listing spec values from a dict keyed by spec key."""
    raw_values = raw_values or {}
    results = []
    for key, value in specs.items():
        obj = upsert_listing_spec_value(
            listing,
            key,
            value,
            raw_value=raw_values.get(key, ""),
            confidence=confidence,
        )
        if obj:
            results.append(obj)
    return results


def get_variant_spec_value(variant: DeviceVariant, key: str) -> Any:
    """Read a single spec value from a variant, returning the effective value or None."""
    product_type = (
        variant.product_model.product_type if variant.product_model and variant.product_model.product_type else None
    )
    if not product_type:
        return None
    spec = get_spec_definition(product_type, key)
    if not spec:
        return None
    sv = ProductVariantSpecValue.objects.filter(variant=variant, spec=spec).first()
    return sv.effective_value if sv else None


def get_listing_spec_value(listing: MarketListing, key: str) -> Any:
    """Read a single spec value from a listing, returning the effective value or None."""
    product_type = (
        listing.product_model.product_type
        if listing.product_model and listing.product_model.product_type
        else None
    )
    if not product_type:
        return None
    spec = get_spec_definition(product_type, key)
    if not spec:
        return None
    sv = MarketListingSpecValue.objects.filter(listing=listing, spec=spec).first()
    return sv.effective_value if sv else None
