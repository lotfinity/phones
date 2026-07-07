"""Generic spec extraction from listing text.

Provides product type detection and spec extraction for all device types.
Currently implements full laptop extraction and wraps existing phone logic.

Usage:
    from market.services.spec_extraction import extract_specs_from_text, detect_product_type
    specs = extract_specs_from_text("laptop", "Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz")
    ptype = detect_product_type("Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from market.services.laptop_parser import (
    parse_cpu,
    parse_gpu,
    parse_panel_type,
    parse_ram_gb,
    parse_screen_size,
    parse_storage_gb,
    parse_resolution,
)


from market.models import Condition

# Specs that are too weak to count as meaningful extraction.
USELESS_SPEC_KEYS = {"condition"}


def clean_extracted_specs(specs: dict[str, Any], product_type_slug: str = "") -> dict[str, Any]:
    """Remove useless or low-quality spec values before writing.

    Filters out:
    - condition=UNKNOWN / condition=empty
    - box_status if empty
    - resolution values that are actually panel types (VA, IPS, OLED, etc.)
    - Any key with an empty/None value
    """
    cleaned: dict[str, Any] = {}
    for key, value in specs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        # Filter unknown condition
        if key == "condition":
            val_str = str(value).strip().lower()
            if val_str in ("", "unknown"):
                continue

        # Filter empty box_status
        if key == "box_status" and not str(value).strip():
            continue

        # Filter resolution values that are actually panel types
        if key == "resolution":
            val_str = str(value).strip().upper()
            if val_str in ("VA", "IPS", "OLED", "TN", "AMOLED", "MINI-LED", "MINI LED"):
                continue

        cleaned[key] = value
    return cleaned


def has_useful_specs(specs: dict[str, Any], product_type_slug: str = "") -> bool:
    """Return True if the spec dict contains at least one meaningful spec value.

    A dict with only condition=UNKNOWN (or similar weak metadata) is not useful.
    """
    cleaned = clean_extracted_specs(specs, product_type_slug)
    return bool(cleaned)


# ---------------------------------------------------------------------------
# ParsedListing dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedListing:
    """Structured result from spec extraction."""
    product_type: str | None = None
    brand: str | None = None
    model_text: str | None = None
    specs: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Product type detection
# ---------------------------------------------------------------------------

LAPTOP_KEYWORDS = re.compile(
    r"\b(laptop|notebook|macbook|legion|rog|strix|victus|tuf|thinkpad|ideapad|pavilion|"
    r"predator|alienware|macbook\s*pro|macbook\s*air|zenbook|vivobook|spectre|envy|"
    r"omen|nitro|aspire|chromebook|yoga|legion|razer)\b",
    re.IGNORECASE,
)

LAPTOP_BRAND_PATTERNS = re.compile(
    r"\b(lenovo|asus|hp|dell|acer|msi|razer|samsung|lg|toshiba|fujitsu|huawei|microsoft|apple)\b",
    re.IGNORECASE,
)

LAPTOP_GPU_EVIDENCE = re.compile(
    r"\b(rtx|gtx|radeon|geforce|arc\s+a\d|iris\s+xe|uhd\s+graphics)\b",
    re.IGNORECASE,
)

LAPTOP_CPU_EVIDENCE = re.compile(
    r"\b(core\s+ultra|i[3579]-\d{4,5}[A-Z]*|ryzen\s+\d\s+\d{4}[A-Z]*|m[1-4]\s*(pro|max|ultra)?|"
    r"pentium|celeron)\b",
    re.IGNORECASE,
)

PHONE_KEYWORDS = re.compile(
    r"\b(iphone|galaxy|pixel|xiaomi|redmi|poco|oppo|vivo|honor|huawei|oneplus|"
    r"motorola|realme|redmagic|nubia|doogee|blackview|gopro|samsung)\b",
    re.IGNORECASE,
)

PHONE_MODEL_PATTERNS = re.compile(
    r"\b(iphone\s*\d|galaxy\s*[szam]\d|pixel\s*\d|xiaomi\s*\d|redmi\s*note|poco\s+[a-z]\d|"
    r"oppo\s+find|vivo\s+x\d|honor\s+magic|huawei\s+p|oneplus\s+\d|"
    r"motorola\s+razr|realme\s+gt|samsung\s+galaxy)\b",
    re.IGNORECASE,
)

TABLET_KEYWORDS = re.compile(
    r"\b(ipad|galaxy\s*tab|tab\s*[sS]\d|surface\s*pro|surface\s*go|kindle|"
    r"lenovo\s+tab|lenovo\s+pad|xiaomi\s*pad|redmi\s*pad|oppo\s*pad)\b",
    re.IGNORECASE,
)

CONSOLE_KEYWORDS = re.compile(
    r"\b(playstation|ps5|ps4|xbox|nintendo|switch|steam\s*deck|rog\s*ally)\b",
    re.IGNORECASE,
)

VR_KEYWORDS = re.compile(
    r"\b(quest|rift|vive|index|pico|vision\s*pro|psvr|mixed\s*reality)\b",
    re.IGNORECASE,
)

CAMERA_KEYWORDS = re.compile(
    r"\b(canonly|nikon|sony\s*(?:a7|a9|a1|zv)|fujifilm|gopro|dji|"
    r"mirrorless|dslr|lens|camera)\b",
    re.IGNORECASE,
)


def detect_product_type(title: str, description: str = "") -> str | None:
    """Detect product type from listing title and description.

    Returns one of: 'laptop', 'phone', 'tablet', 'console', 'vr_headset', 'camera', or None.
    Priority: explicit keywords > GPU/CPU evidence > brand patterns > phone fallback.
    """
    text = f"{title} {description}".strip()
    if not text:
        return None

    # Strong laptop signals: explicit keywords
    if LAPTOP_KEYWORDS.search(text):
        return "laptop"

    # Tablet (check before GPU/CPU evidence since "M2" matches CPU pattern)
    if TABLET_KEYWORDS.search(text):
        return "tablet"

    # Laptop GPU/CPU evidence (very strong for laptops)
    if LAPTOP_GPU_EVIDENCE.search(text) or LAPTOP_CPU_EVIDENCE.search(text):
        # Check it's not a phone with GPU mention (rare but possible)
        if not PHONE_MODEL_PATTERNS.search(text):
            return "laptop"

    # Console
    if CONSOLE_KEYWORDS.search(text):
        return "console"

    # VR headset
    if VR_KEYWORDS.search(text):
        return "vr_headset"

    # Camera
    if CAMERA_KEYWORDS.search(text):
        return "camera"

    # Phone (strong model patterns)
    if PHONE_MODEL_PATTERNS.search(text):
        return "phone"

    # Phone (brand keywords with phone-like context)
    if PHONE_KEYWORDS.search(text):
        # If it also has laptop evidence, laptop wins
        if LAPTOP_BRAND_PATTERNS.search(text) and (
            re.search(r"\b\d{2,3}\s*(?:gb|go)\s*(?:ssd|hdd|nvme|ram)\b", text, re.IGNORECASE)
            or re.search(r"\b(ssd|hdd|nvme)\b", text, re.IGNORECASE)
        ):
            return "laptop"
        return "phone"

    # Weak laptop signal: brand + storage patterns
    if LAPTOP_BRAND_PATTERNS.search(text):
        if re.search(r"\b\d+\s*(?:gb|go)\s+(?:ssd|hdd|nvme|ram)\b", text, re.IGNORECASE):
            return "laptop"

    return None


# ---------------------------------------------------------------------------
# Laptop spec extraction
# ---------------------------------------------------------------------------

# Refresh rate patterns
REFRESH_RATE_PATTERNS = [
    r"(\d{2,3})\s*(?:hz|hertz|fps|Hz)",
    r"(\d{2,3})\s*Hz",
]

# Touchscreen patterns
TOUCHSCREEN_PATTERNS = [
    r"\b(touch(?:screen)?|tactile|ekran\s*dokunmatik)\b",
]

# Warranty patterns
WARRANTY_PATTERNS = [
    r"(\d{1,2})\s*(?:ay|months?|mois)\s*(?:garanti|warranty)",
    r"(?:garanti|warranty)\s*[:\s]*(\d{1,2})\s*(?:ay|months?|mois)?",
]

# Box status patterns
BOX_STATUS_PATTERNS = [
    (r"\b(s[ıi]f[ıi]r|kapal[ıi]\s*kutu|sealed|neuf|new|acilmamis|no\s*aktiv)\b", "sealed"),
    (r"\b(a[cç][ıi]lm[ıi][şs]\s*kutu|open\s*box|boite\s*ouverte)\b", "boxed"),
    (r"\b(kutusuz|no\s*box|sans\s*boite|without\s*box)\b", "no_box"),
]

# Condition patterns (laptop-specific)
LAPTOP_CONDITION_PATTERNS = [
    (r"\b(s[ıi]f[ıi]r|kapal[ıi]\s*kutu|sealed|neuf|new|acilmamis|mint)\b", "sealed"),
    (r"\b(ikinci\s*el|2\.?\s*el|used|occasion|temiz|kullanim|aktif)\b", "used"),
]

# GPU VRAM patterns
GPU_VRAM_PATTERNS = [
    r"(\d{1,2})\s*gb\s*(?:vram|dedicated|gddr)",
    r"(?:vram|dedicated)\s*[:\s]*(\d{1,2})\s*gb",
    r"(?:rtx|gtx)\s*\d{4}\s+(\d{1,2})\s*gb",
]

# Screen size with inch patterns (including standalone)
SCREEN_SIZE_STANDALONE = [
    r'(\d{2}(?:\.\d)?)\s*[""″\'\']',
    r"(\d{2}(?:\.\d)?)\s*(?:pouces?|inches?|inch|inç)",
]


def _extract_refresh_rate(text: str) -> int | None:
    """Extract refresh rate in Hz from text."""
    for pattern in REFRESH_RATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 60 <= val <= 500:
                return val
    return None


def _extract_touchscreen(text: str) -> bool | None:
    """Detect touchscreen mention."""
    for pattern in TOUCHSCREEN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return None


def _extract_warranty_months(text: str) -> int | None:
    """Extract warranty duration in months."""
    for pattern in WARRANTY_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 60:
                return val
    return None


def _extract_box_status(text: str) -> str:
    """Extract box status from text."""
    lower_text = text.lower()
    for pattern, status in BOX_STATUS_PATTERNS:
        if re.search(pattern, lower_text):
            return status
    return ""


def _extract_laptop_condition(text: str) -> str:
    """Extract condition from laptop listing text."""
    from market.models import Condition
    lower_text = text.lower()
    for pattern, condition in LAPTOP_CONDITION_PATTERNS:
        if re.search(pattern, lower_text):
            return condition
    return Condition.UNKNOWN


def _extract_gpu_vram(text: str) -> int | None:
    """Extract GPU VRAM in GB."""
    for pattern in GPU_VRAM_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 2 <= val <= 32:
                return val
    return None


def _extract_screen_size_standalone(text: str) -> float | None:
    """Extract screen size from standalone patterns like 15.6" or 16 pouces."""
    for pattern in SCREEN_SIZE_STANDALONE:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            size = float(m.group(1))
            if 10 <= size <= 20:
                return size
    return None


def extract_laptop_specs(text: str) -> dict[str, Any]:
    """Extract laptop-specific specs from text.

    Returns a dict with keys matching spec definition keys:
    cpu_model, gpu_model, ram_gb, ssd_gb, screen_inches, refresh_hz,
    resolution, touchscreen, gpu_vram_gb, warranty_months, box_status, condition.
    """
    specs: dict[str, Any] = {}

    # CPU
    cpu = parse_cpu(text)
    if cpu:
        specs["cpu_model"] = cpu
        # Extract CPU brand
        if "intel" in cpu.lower() or "core" in cpu.lower() or "pentium" in cpu.lower() or "celeron" in cpu.lower():
            specs["cpu_brand"] = "Intel"
        elif "amd" in cpu.lower() or "ryzen" in cpu.lower():
            specs["cpu_brand"] = "AMD"
        elif "apple" in cpu.lower() or cpu.lower().startswith("m"):
            specs["cpu_brand"] = "Apple"

    # GPU
    gpu = parse_gpu(text)
    if gpu:
        specs["gpu_model"] = gpu
        # Extract GPU brand
        if "nvidia" in gpu.lower() or "rtx" in gpu.lower() or "gtx" in gpu.lower() or "geforce" in gpu.lower():
            specs["gpu_brand"] = "NVIDIA"
        elif "radeon" in gpu.lower() or "amd" in gpu.lower():
            specs["gpu_brand"] = "AMD"
        elif "arc" in gpu.lower() or "iris" in gpu.lower() or "uhd" in gpu.lower():
            specs["gpu_brand"] = "Intel"

    # RAM
    ram = parse_ram_gb(text)
    if ram is not None:
        specs["ram_gb"] = ram

    # SSD/Storage
    ssd = parse_storage_gb(text)
    if ssd is not None:
        specs["ssd_gb"] = ssd

    # Screen size (try laptop parser first, then standalone)
    screen = parse_screen_size(text)
    if screen is None:
        screen = _extract_screen_size_standalone(text)
    if screen is not None:
        specs["screen_inches"] = screen

    # Resolution
    resolution = parse_resolution(text)
    if resolution:
        specs["resolution"] = resolution

    # Panel type (stored separately, not as resolution)
    panel_type = parse_panel_type(text)
    if panel_type:
        specs["panel_type"] = panel_type

    # Refresh rate
    refresh = _extract_refresh_rate(text)
    if refresh is not None:
        specs["refresh_hz"] = refresh

    # Touchscreen
    touchscreen = _extract_touchscreen(text)
    if touchscreen is not None:
        specs["touchscreen"] = touchscreen

    # GPU VRAM
    vram = _extract_gpu_vram(text)
    if vram is not None:
        specs["gpu_vram_gb"] = vram

    # Warranty
    warranty = _extract_warranty_months(text)
    if warranty is not None:
        specs["warranty_months"] = warranty

    # Box status
    box_status = _extract_box_status(text)
    if box_status:
        specs["box_status"] = box_status

    # Condition
    condition = _extract_laptop_condition(text)
    if condition:
        specs["condition"] = condition

    return specs


# ---------------------------------------------------------------------------
# Phone spec extraction (wraps existing logic)
# ---------------------------------------------------------------------------

def extract_phone_specs(text: str) -> dict[str, Any]:
    """Extract phone specs from text, wrapping existing parser logic.

    Returns a dict with keys: storage_gb, ram_gb, sim_config, condition.
    """
    from market.services.listing_parser import parse_storage_ram, parse_sim_config, parse_condition

    specs: dict[str, Any] = {}

    storage_gb, ram_gb = parse_storage_ram(text)
    if storage_gb is not None:
        specs["storage_gb"] = storage_gb
    if ram_gb is not None:
        specs["ram_gb"] = ram_gb

    sim = parse_sim_config(text)
    if sim:
        specs["sim_config"] = sim

    condition = parse_condition(text)
    if condition:
        specs["condition"] = condition

    return specs


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_specs_from_text(
    product_type_slug: str | None,
    text: str,
    title: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Extract specs from listing text for a given product type.

    Args:
        product_type_slug: Product type slug (laptop, phone, etc.) or None for auto-detect.
        text: Combined text to extract from (title + description).
        title: Listing title (used for product type detection if slug is None).
        description: Listing description.

    Returns:
        Dict of spec key -> value pairs.
    """
    if not text and not title:
        return {}

    combined = f"{title} {description} {text}".strip() if text else f"{title} {description}".strip()

    # Auto-detect product type if not provided
    if product_type_slug is None:
        product_type_slug = detect_product_type(title, description)

    if product_type_slug == "laptop":
        return clean_extracted_specs(extract_laptop_specs(combined), "laptop")
    elif product_type_slug == "phone":
        return clean_extracted_specs(extract_phone_specs(combined), "phone")
    else:
        # For tablet/console/vr/camera, try laptop-style extraction as fallback
        # since they may share some specs (RAM, storage, screen)
        return clean_extracted_specs(extract_laptop_specs(combined), product_type_slug or "")


def extract_specs_from_listing(
    product_type_slug: str | None,
    title: str,
    description: str = "",
    raw_metadata: dict | None = None,
) -> ParsedListing:
    """High-level extraction that returns a ParsedListing.

    Args:
        product_type_slug: Product type slug or None for auto-detect.
        title: Listing title.
        description: Listing description.
        raw_metadata: Additional metadata dict (e.g., from CDP extraction).

    Returns:
        ParsedListing with detected product type, specs, confidence, and reasons.
    """
    reasons: list[str] = []
    confidence = 0.0

    # Detect product type
    detected_type = detect_product_type(title, description)
    product_type = product_type_slug or detected_type

    if product_type:
        reasons.append(f"Detected product type: {product_type}")
        confidence += 0.3
    else:
        reasons.append("Could not detect product type")
        confidence -= 0.2

    # Extract specs
    combined_text = f"{title} {description}".strip()
    if raw_metadata:
        # Include metadata values in extraction text
        meta_parts = [str(v) for v in raw_metadata.values() if v]
        if meta_parts:
            combined_text = f"{combined_text} {' '.join(meta_parts)}"

    specs = extract_specs_from_text(product_type, combined_text, title, description)

    # Calculate confidence based on extracted specs
    if specs:
        spec_count = len([v for v in specs.values() if v is not None and v != "" and v != False])
        confidence += min(spec_count * 0.08, 0.5)
        reasons.append(f"Extracted {spec_count} specs")

    # Brand detection
    brand = None
    from market.services.normalization import likely_brand
    brand = likely_brand(title)
    if brand:
        reasons.append(f"Detected brand: {brand}")
        confidence += 0.1

    # Model extraction
    model_text = None
    if product_type == "phone":
        from market.services.listing_parser import extract_model_text
        model_text = extract_model_text(title, description)
    elif product_type == "laptop":
        # Try to extract laptop model
        model_text = _extract_laptop_model_text(title)

    if model_text:
        reasons.append(f"Detected model: {model_text}")
        confidence += 0.1

    confidence = min(max(confidence, 0.0), 1.0)

    return ParsedListing(
        product_type=product_type,
        brand=brand,
        model_text=model_text,
        specs=specs,
        confidence=round(confidence, 3),
        reasons=reasons,
    )


def _extract_laptop_model_text(title: str) -> str | None:
    """Extract a clean laptop model name from title."""
    text = title.strip()
    if not text:
        return None

    # Try common laptop model patterns
    patterns = [
        # Lenovo Legion
        r"(?:lenovo\s+)?legion\s+(?:\d+\s*)?(?:pro\s+)?(?:\d+\s*)?(?:irx\d+|iap\d+|ach\d+)?",
        # Lenovo IdeaPad
        r"(?:lenovo\s+)?ideapad\s+\w+\s*\d*",
        # ASUS ROG
        r"(?:asus\s+)?(?:rog\s+)?(?:strix|zephyrus|flow|tuf)\s+\w+\s*\d*",
        # HP Victus/Omen/Pavilion
        r"(?:hp\s+)?(?:victus|omen|pavilion|spectre|envy)\s+\w*\s*\d*",
        # Dell
        r"(?:dell\s+)?(?:inspiron|xps|latitude|precision|g\d+)\s*\w*\s*\d*",
        # Acer
        r"(?:acer\s+)?(?:nitro|predator|aspire|swift)\s+\w*\s*\d*",
        # MSI
        r"(?:msi\s+)?(?:raider|stealth|creator|pulse|katana)\s+\w*\s*\d*",
        # MacBook
        r"macbook\s*(?:pro|air)\s*(?:\d+(?:\.\d+)?)?",
        # Generic: Brand + Model pattern
        r"(?:lenovo|asus|hp|dell|acer|msi|razer|samsung|huawei|microsoft)\s+\w+\s+\w+",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            model = m.group(0).strip()
            # Clean up extra whitespace
            model = re.sub(r"\s+", " ", model)
            return model

    # Fallback: first few words that look like a model
    words = text.split()
    if len(words) >= 2:
        # Take first 3-4 words as model hint
        candidate = " ".join(words[:min(4, len(words))])
        return candidate

    return text[:60] if text else None
