from django.utils.text import slugify
from django.core.exceptions import MultipleObjectsReturned

from market.models import Brand, Category, DeviceVariant, ProductModel, build_device_variant_identity, normalize_sim_config
from market.services.normalization import canonical_model_name, likely_brand

SUPPORTED_STORAGE_GB = {64, 128, 256, 512, 1024}


def get_default_category(name="Phones"):
    return Category.objects.get_or_create(
        slug=slugify(name),
        defaults={"name": name},
    )[0]


def get_or_create_model(raw_model, category_name="Phones"):
    canonical = canonical_model_name(raw_model)
    brand_name = likely_brand(raw_model) or "Unknown"
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"aliases": []})
    category = get_default_category(category_name)
    product_model, _ = ProductModel.objects.get_or_create(
        brand=brand,
        canonical_name=canonical,
        defaults={"category": category, "aliases": [raw_model] if raw_model and raw_model != canonical else []},
    )
    if not product_model.category_id:
        product_model.category = category
        product_model.save(update_fields=["category"])
    return product_model


def get_or_create_variant(product_model, storage_gb=None, sim_config=""):
    if storage_gb and storage_gb not in SUPPORTED_STORAGE_GB:
        storage_gb = None
    sim_config = normalize_sim_config(sim_config)
    identity_key = build_device_variant_identity(storage_gb, sim_config)
    bits = [product_model.canonical_name]
    if storage_gb:
        bits.append(f"{storage_gb}GB")
    if sim_config:
        bits.append(sim_config)
    label = " ".join(bits)
    try:
        variant, _ = DeviceVariant.objects.get_or_create(
            product_model=product_model,
            identity_key=identity_key,
            defaults={
                "storage_gb": storage_gb,
                "sim_config": sim_config,
                "canonical_label": label,
            },
        )
    except MultipleObjectsReturned:
        variant = (
            DeviceVariant.objects.filter(
                product_model=product_model,
                identity_key=identity_key,
            )
            .order_by("id")
            .first()
        )
    return variant
