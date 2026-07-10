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
VALID_OPPORTUNITY_STORAGE_GB = frozenset({128, 256, 512, 1024, 2048, 4096, 8192})
VALID_OPPORTUNITY_RAM_GB = frozenset({4, 8, 12, 16, 18, 24, 32, 36, 48, 64, 96})
_PORTABLE_CONSOLE_MODEL_RE = re.compile(
    r"\b(?:rog\s+ally|xbox\s+ally|legion\s+go|steam\s+deck|nintendo\s+switch|playstation\s+portal|msi\s+claw)\b",
    re.IGNORECASE,
)


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
    if "source ouedkniss cdp category" in cleaned:
        return True
    if "webp source" in cleaned:
        return True
    if "gpu ram gb" in cleaned or "cell ram" in cleaned or "price currency" in cleaned:
        return True
    if cleaned in {"macbook pro pro", "macbook air air"}:
        return True
    if cleaned in {"l gion"}:
        return True
    return len(cleaned) > 80


def is_generic_laptop_model_name(model_name):
    return clean_model_key(model_name) in _GENERIC_LAPTOP_MODELS


def is_portable_console_laptop_model_name(model_name):
    return bool(_PORTABLE_CONSOLE_MODEL_RE.search(model_name or ""))


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


def listing_has_laptop_opportunity_identity(listing):
    """Stricter identity gate for opportunity/enrichment math."""
    model_name = listing.laptop_model.canonical_name if listing.laptop_model else ""
    if is_garbage_laptop_model_name(model_name):
        return False
    if is_portable_console_laptop_model_name(model_name):
        return False
    has_model = bool(clean_model_key(model_name))
    if listing.storage_gb and listing.storage_gb not in VALID_OPPORTUNITY_STORAGE_GB:
        return False
    if listing.ram_gb and listing.ram_gb not in VALID_OPPORTUNITY_RAM_GB:
        return False
    has_ram_storage = bool(has_model and listing.ram_gb and listing.storage_gb)
    has_exact_variant = bool(listing.variant and has_model and float(listing.parsed_confidence or 0) >= 0.90)
    if is_generic_laptop_model_name(model_name) and not (has_ram_storage or has_exact_variant):
        return False
    return bool(has_ram_storage or has_exact_variant)


def is_implausible_laptop_price(listing):
    if listing.price_eur is None:
        return True
    price = float(listing.price_eur)
    if price < 100 or price > 5000:
        return True

    model_name = clean_model_key(listing.laptop_model.canonical_name if listing.laptop_model else "")
    cpu = clean_model_key(listing.cpu)
    combined = f"{model_name} {cpu}"
    if "m4 pro" in combined and price < 1000:
        return True
    if "m4" in combined and price < 600:
        return True
    if "m3" in combined and price < 450:
        return True
    if "m2" in combined and price < 300:
        return True
    if "m1" in combined and price < 220:
        return True
    return False
