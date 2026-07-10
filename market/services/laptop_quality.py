"""Quality gates for laptop parsing, final listings, and exports."""

import re


_MODEL_GARBAGE_TOKENS = frozenset({
    "gpu",
    "ram",
    "gb",
    "go",
    "storage",
    "cell",
    "cell_ram",
    "cell_storage",
    "price",
    "currency",
    "ssd",
    "hdd",
    "nvme",
    "cpu",
    "source",
    "sahibinden",
    "cdp",
    "category",
    "laptops",
    "laptop",
    "notebook",
})

_GENERIC_LAPTOP_MODELS = frozenset({
    "legion",
    "thinkpad",
    "ideapad",
    "loq",
    "tuf",
    "rog",
    "vivobook",
    "zenbook",
    "latitude",
    "inspiron",
    "precision",
    "xps",
    "victus",
    "omen",
    "elitebook",
    "probook",
    "pavilion",
    "nitro",
    "predator",
    "aspire",
    "swift",
    "macbook",
    "macbook air",
    "macbook pro",
})


def clean_model_key(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def is_garbage_laptop_model_name(model_name):
    cleaned = clean_model_key(model_name)
    if not cleaned:
        return True
    tokens = set(cleaned.split())
    if tokens and tokens.issubset(_MODEL_GARBAGE_TOKENS):
        return True
    if "source sahibinden cdp category" in cleaned:
        return True
    if "gpu ram gb" in cleaned or "cell ram" in cleaned or "price currency" in cleaned:
        return True
    if cleaned in {"macbook pro pro", "macbook air air"}:
        return True
    return len(cleaned) > 80


def is_generic_laptop_model_name(model_name):
    return clean_model_key(model_name) in _GENERIC_LAPTOP_MODELS


def has_laptop_export_identity(*, model_name="", cpu="", gpu="", ram_gb=None, storage_gb=None, variant=None, confidence=0):
    """Return True when a laptop row is specific enough for buyer-facing exports."""
    if is_garbage_laptop_model_name(model_name):
        return False

    has_model = bool(clean_model_key(model_name))
    meaningful_gpu = bool(gpu and clean_model_key(gpu) not in {"apple integrated", "integrated"})
    has_ram_storage = bool(has_model and ram_gb and storage_gb)
    has_cpu_gpu = bool(has_model and cpu and meaningful_gpu)
    has_exact_variant = bool(variant and has_model and float(confidence or 0) >= 0.90)

    if is_generic_laptop_model_name(model_name) and not (has_ram_storage or has_cpu_gpu or has_exact_variant):
        return False

    return bool(has_ram_storage or has_cpu_gpu or has_exact_variant)


def candidate_has_laptop_export_identity(candidate):
    specs = candidate.laptop_specs_json or {}
    return has_laptop_export_identity(
        model_name=candidate.model_text,
        cpu=specs.get("cpu", ""),
        gpu=specs.get("gpu", ""),
        ram_gb=specs.get("ram_gb"),
        storage_gb=specs.get("storage_gb"),
        variant=candidate.matched_laptop_variant,
        confidence=candidate.confidence,
    )


def listing_has_laptop_export_identity(listing):
    model_name = listing.laptop_model.canonical_name if listing.laptop_model else ""
    return has_laptop_export_identity(
        model_name=model_name,
        cpu=listing.cpu,
        gpu=listing.gpu,
        ram_gb=listing.ram_gb,
        storage_gb=listing.storage_gb,
        variant=listing.variant,
        confidence=listing.parsed_confidence,
    )
