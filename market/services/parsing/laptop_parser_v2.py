"""Laptop listing parser v2 — hardened regex extraction from raw text."""

import re
from decimal import Decimal, InvalidOperation

from market.services.parsing.segments import (
    find_regex_segments,
    make_segment,
    merge_segments,
    sort_segments,
)

LAPTOP_BRANDS = {
    "lenovo": "Lenovo",
    "thinkpad": "Lenovo",
    "legion": "Lenovo",
    "ideapad": "Lenovo",
    "loq": "Lenovo",
    "asus": "ASUS",
    "rog": "ASUS",
    "tuf": "ASUS",
    "vivobook": "ASUS",
    "zenbook": "ASUS",
    "dell": "Dell",
    "inspiron": "Dell",
    "latitude": "Dell",
    "xps": "Dell",
    "alienware": "Dell",
    "precision": "Dell",
    "hp": "HP",
    "pavilion": "HP",
    "spectre": "HP",
    "omen": "HP",
    "elitebook": "HP",
    "probook": "HP",
    "victus": "HP",
    "zbook": "HP",
    "acer": "Acer",
    "nitro": "Acer",
    "predator": "Acer",
    "swift": "Acer",
    "aspire": "Acer",
    "macbook": "Apple",
    "apple": "Apple",
    "imac": "Apple",
    "msi": "MSI",
    "razer": "Razer",
    "razerblade": "Razer",
    "samsung": "Samsung",
    "lg": "LG",
    "gigabyte": "Gigabyte",
    "huawei": "Huawei",
    "microsoft": "Microsoft",
    "surface": "Microsoft",
}

# ── CPU patterns ────────────────────────────────────────────────────────────
# Order matters: more specific patterns first.

_CPU_PATTERNS = [
    # Apple Silicon — match M1/M2/M3/M4 with optional suffix, in Apple context
    (r"M[1-4]\s*(?:Pro|Max|Ultra)?\b", "apple"),
    # Intel Core i-series with full model number: "Intel Core i7-12700H"
    (r"Intel\s+Core\s+i[3579]-?\d{4,5}[A-Z]*", "intel_full"),
    # Intel i-series standalone with full model number: "i7-12700H", "i5-1135G7"
    (r"(?<![a-zA-Z])i([3579])-?\d{4,5}[A-Z]*", "intel_full_standalone"),
    # Intel Core i-series short with prefix: "Intel Core i5", "Intel Core i7"
    (r"Intel\s+Core\s+i[3579]\b(?![\s-]*\d)", "intel_short_prefix"),
    # Intel Core i-series short standalone: "i5 8GB", "i7 RTX" — not preceded by letter, not followed by SKU
    (r"(?<![a-zA-Z])i([3579])\b(?!\s*[-–]?\s*\d{3,5})", "intel_short"),
    # Intel Core Ultra
    (r"Core\s+Ultra\s+\d+\s*\d*[A-Z]*", "intel_ultra"),
    # Intel N-series / Pentium / Celeron
    (r"Intel\s+(?:Pentium|Celeron|Core)\s+\w+", "intel_other"),
    # AMD Ryzen with model number: Ryzen 7 5800H, Ryzen 5 5600H
    (r"Ryzen\s+[3579]\s+\d{4}[A-Z]*", "amd_full"),
    # AMD Ryzen short: Ryzen 3, Ryzen 5, Ryzen 7, Ryzen 9
    (r"Ryzen\s+[3579]\b", "amd_short"),
    # AMD R-series
    (r"R[579]-?\d{4}[A-Z]*", "amd_r"),
    # Snapdragon
    (r"Snapdragon\s+\w+\s*\d*", "other"),
]

# ── GPU patterns ────────────────────────────────────────────────────────────

_GPU_PATTERNS = [
    # NVIDIA RTX with model number
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?RTX\s+\d{4}(?:\s*(?:Ti|Laptop))?",
    # NVIDIA GTX with model number
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?GTX\s+\d{4}(?:\s*Ti)?",
    # NVIDIA MX
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?MX\d{3,4}",
    # AMD Radeon RX
    r"Radeon\s+RX\s+\w+\d*",
    # AMD Radeon Graphics (integrated)
    r"Radeon\s+Graphics",
    # Intel Arc
    r"Intel\s+Arc",
    # Intel Iris Xe
    r"Iris\s+Xe",
    # Intel UHD / Iris
    r"Intel\s+(?:UHD|Iris)\s+\w*",
]

# ── RAM patterns ────────────────────────────────────────────────────────────
# Valid RAM values for laptops (conservative set).
VALID_RAM_GB = frozenset({4, 6, 8, 12, 16, 18, 24, 32, 36, 48, 64, 96, 128})

_RAM_PATTERNS = [
    # "16GB RAM", "16 GB RAM", "16Go RAM"
    re.compile(r"(\d{1,3})\s*(?:GB|Go)\s*(?:RAM|ram)", re.IGNORECASE),
    # "RAM 16GB", "RAM: 16GB", "8 RAM", "16 RAM"
    re.compile(r"(?:RAM|ram)\s*[:=]?\s*(\d{1,3})\s*(?:GB|Go)?", re.IGNORECASE),
    # "16 RAM" — number followed by RAM without GB
    re.compile(r"\b(\d{1,3})\s+(?:RAM|ram)\b", re.IGNORECASE),
    # "16/512" pattern (RAM/storage) — RAM is the first number
    re.compile(r"\b(\d{1,3})\s*/\s*\d{3,4}\b"),
    # "32GB DDR5" or "32GB LPDDR5" — GB followed by memory type, not storage
    re.compile(r"\b(\d{1,3})\s*(?:GB|Go)\s+(?:DDR\d|LPDDR\d|MHz)", re.IGNORECASE),
    # Standalone "16GB" before known storage keywords (512GB SSD, 1TB NVMe, etc.)
    re.compile(r"\b(\d{1,3})\s*(?:GB|Go)\s+(?=\d+\s*(?:GB|TB|Go)\s*(?:SSD|HDD|NVMe|ssd|hdd|nvme))", re.IGNORECASE),
    # Standalone "8GB" at end of text or before non-storage words
    re.compile(r"\b(\d{1,3})\s*(?:GB|Go)\b(?!\s*(?:SSD|HDD|NVMe|ssd|hdd|nvme|DDR|LPDDR))", re.IGNORECASE),
    # "8 256" pattern — small number followed by 3-digit storage number
    re.compile(r"\b(\d{1,2})\s+(\d{3})\b"),
]

# ── Storage patterns ────────────────────────────────────────────────────────
# Valid storage values for laptops.
VALID_STORAGE_GB = frozenset({128, 256, 512, 1024, 2048, 4096, 8192})

_STORAGE_PATTERNS = [
    # "512GB SSD", "1TB SSD", "256 Go SSD", "512SSD", "256 M2 SSD", "256 M.2 SSD"
    re.compile(r"(\d{1,4})\s*(?:GB|TB|Go)?\s*(?:M\.?\s*2\s*)?(?:SSD|HDD|NVMe|nvme|ssd|hdd|PCIe|pcie)", re.IGNORECASE),
    # "SSD 512GB", "HDD 1TB"
    re.compile(r"(?:SSD|HDD|NVMe)\s*[:=]?\s*(\d{1,4})\s*(?:GB|TB|Go)?", re.IGNORECASE),
    # "512GB SSD" with trailing
    re.compile(r"(\d{1,4})\s*(?:GB|TB)\s*(?:SSD|HDD)", re.IGNORECASE),
    # "1TB" or "2TB" standalone (not RAM context)
    re.compile(r"\b(\d{1,4})\s*TB\b", re.IGNORECASE),
    # "16/512" pattern — storage is the second number (3-4 digits)
    re.compile(r"\b\d{1,3}\s*/\s*(\d{3,4})\b"),
    # "512GB" standalone (only if followed by SSD/HDD context or at end of text)
    re.compile(r"\b(\d{1,4})\s*GB\b", re.IGNORECASE),
]

# M.2 / NVMe storage type keywords (not to be confused with Apple M2)
_STORAGE_TYPE_KEYWORDS = re.compile(
    r"M\.2|NVMe|nvme|PCIe|pcie|SATA|sata|SSD|HDD",
    re.IGNORECASE,
)

_SCREEN_SIZE_PATTERN = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:inch|\")\b|"
    r"(\d{2,3})\s*(?:cm)\b",
    re.IGNORECASE,
)

_RESOLUTION_PATTERN = re.compile(
    r"(\d{3,4})\s*x\s*(\d{3,4})\b|"
    r"\b(FHD|Full\s*HD|QHD|2K|4K|UHD|HD|WQXGA|WXGA|FHD\+|QHD\+)\b",
    re.IGNORECASE,
)

_REFRESH_RATE_PATTERN = re.compile(
    r"(\d{2,3})\s*Hz\b",
    re.IGNORECASE,
)

_PANEL_PATTERN = re.compile(
    r"\b(IPS|VA|TN|OLED|AMOLED|Mini[\s-]?LED|IPS[\s-]?Level|触摸|Touch)\b",
    re.IGNORECASE,
)

_PRICE_AMOUNT_PATTERN = r"(?:\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d{4,8}(?:,\d{1,2})?|\d{1,3}(?:,\d{1,2})?)"
_PRICE_PATTERN = re.compile(
    rf"(?P<amount_before>{_PRICE_AMOUNT_PATTERN})\s*(?P<currency_after>DA|DZD|TL|TRY|₺|\$|USD|€|EUR)\b|"
    rf"(?<![A-Za-z])(?P<currency_before>DA|DZD|TL|TRY|₺|\$|USD|€|EUR)\s*(?P<amount_after>{_PRICE_AMOUNT_PATTERN})",
    re.IGNORECASE,
)

_CURRENCY_MAP = {
    "DA": "DZD", "DZD": "DZD",
    "TL": "TRY", "TRY": "TRY", "₺": "TRY",
    "$": "USD", "USD": "USD",
    "€": "EUR", "EUR": "EUR",
}

_CONDITION_KEYWORDS = {
    "sealed": ["sealed", "new", "yeni", "mint", "kapalı kutu", "unopened"],
    "used_a_plus": ["excellent", "like new", "mükemmel"],
    "used_a": ["very good", "iyi", "clean"],
    "used_b": ["good", "fair"],
    "used": ["used", "ikinci el", "kullanılmış", "pre-owned"],
}

# Words that should NOT be treated as model family names on their own.
_GARBAGE_WORDS = frozenset({
    "laptop", "notebook", "pc", "portable", "bilgisayar", "fiyatı",
    "sahibinden", "satis", "satılık", "ikinci", "el",
    "none", "null", "undefined", "price", "currency",
    "cell_ram", "cell_storage", "ram", "ssd", "hdd",
    "new", "yeni", "kutu", "kutudan", "çıkma",
})

# Known model families for cleaning model text.
_KNOWN_MODEL_FAMILIES = {
    "apple": {
        "macbook air", "macbook pro", "imac",
    },
    "lenovo": {
        "thinkpad", "legion", "ideapad", "loq",
    },
    "asus": {
        "tuf", "rog", "vivobook", "zenbook",
    },
    "hp": {
        "pavilion", "spectre", "omen", "elitebook", "probook", "victus", "zbook",
    },
    "dell": {
        "latitude", "precision", "xps", "inspiron", "alienware",
    },
    "acer": {
        "nitro", "predator", "swift", "aspire",
    },
    "msi": {
        "gf63", "katana", "raider", "stealth", "cyborg",
    },
}


def detect_brand(text):
    text_lower = text.lower()
    for keyword, brand_name in LAPTOP_BRANDS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text_lower):
            return brand_name
    return ""


def _is_apple_context(text):
    """Check if the text is clearly about Apple/MacBook."""
    text_lower = text.lower()
    return "macbook" in text_lower or "apple" in text_lower or "imac" in text_lower


def detect_cpu(text):
    """Detect CPU with Apple Silicon context awareness.

    M2 in 'M2 SSD' or 'M.2 NVMe' is storage, not CPU.
    Only detect M1/M2/M3/M4 as CPU when the row is clearly Apple/MacBook.
    """
    is_apple = _is_apple_context(text)

    for pattern, cpu_type in _CPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        matched = m.group().strip()

        if cpu_type == "apple" and is_apple:
            return _normalize_cpu(matched)
        elif cpu_type in ("intel_full", "intel_full_standalone", "intel_short_prefix", "intel_short"):
            # For intel_short, extract just the i3/i5/i7/i9 part
            if cpu_type == "intel_short":
                im = re.search(r"i([3579])", matched, re.IGNORECASE)
                if im:
                    return f"Intel Core i{im.group(1)}"
                return _normalize_cpu(matched)
            # For intel_full_standalone, extract the full chip
            if cpu_type == "intel_full_standalone":
                im = re.search(r"i([3579])[-–]?(\d{4,5}[A-Z]*)", matched, re.IGNORECASE)
                if im:
                    return f"Intel Core i{im.group(1)}-{im.group(2)}"
                return _normalize_cpu(matched)
            return _normalize_cpu(matched)
        elif cpu_type not in ("apple",):
            return _normalize_cpu(matched)
        # If cpu_type == "apple" but not is_apple, skip (it's M.2 storage)
        continue

    # Fallback: standalone i3/i5/i7/i9 not already caught
    if is_apple:
        return ""
    m = re.search(r"(?<![a-zA-Z])i([3579])\b", text, re.IGNORECASE)
    if m:
        return f"Intel Core i{m.group(1)}"
    return ""


def _normalize_cpu(raw):
    """Normalize CPU text to a consistent format."""
    text = raw.strip()
    # Normalize Apple Silicon
    m = re.match(r"(?:Apple\s+)?M([1-4])\s*(Pro|Max|Ultra)?", text, re.IGNORECASE)
    if m:
        gen = m.group(1)
        suffix = f" {m.group(2).title()}" if m.group(2) else ""
        return f"Apple M{gen}{suffix}"

    # Normalize Intel i-series — try full SKU first, then short
    m = re.match(r"(?:Intel\s+Core\s+)?i([3579])[-–](\d{4,5}[A-Z]*)", text, re.IGNORECASE)
    if m:
        return f"Intel Core i{m.group(1)}-{m.group(2)}"
    m = re.match(r"(?:Intel\s+Core\s+)?i([3579])\b", text, re.IGNORECASE)
    if m:
        return f"Intel Core i{m.group(1)}"

    # Normalize Intel Core Ultra
    m = re.match(r"(?:Intel\s+)?Core\s+Ultra\s+(\d+\s*\d*[A-Z]*)", text, re.IGNORECASE)
    if m:
        return f"Intel Core Ultra {m.group(1).strip()}"

    # Normalize AMD Ryzen
    m = re.match(r"(?:AMD\s+)?Ryzen\s+([3579])\s*(\d{4}[A-Z]*)?", text, re.IGNORECASE)
    if m:
        level = m.group(1)
        sku = m.group(2)
        if sku:
            return f"AMD Ryzen {level} {sku}"
        return f"AMD Ryzen {level}"

    # Normalize AMD R-series
    m = re.match(r"R([579])[-–]?(\d{4}[A-Z]*)", text, re.IGNORECASE)
    if m:
        return f"AMD R{m.group(1)}-{m.group(2)}"

    return text


def detect_gpu(text):
    """Detect GPU and normalize to standard format."""
    is_apple = _is_apple_context(text)

    for pattern in _GPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            matched = m.group().strip()
            return _normalize_gpu(matched, is_apple)

    # Apple integrated GPU (only for Apple context)
    if is_apple and re.search(r"\bGPU\b", text, re.IGNORECASE):
        return "Apple Integrated"

    return ""


def _normalize_gpu(raw, is_apple=False):
    """Normalize GPU text."""
    text = raw.strip()

    # NVIDIA RTX
    m = re.match(r"(?:NVIDIA\s+)?(?:GeForce\s+)?RTX\s+(\d{4})(?:\s*(Ti|Laptop))?", text, re.IGNORECASE)
    if m:
        model = m.group(1)
        suffix = f" {m.group(2).title()}" if m.group(2) else ""
        return f"NVIDIA RTX {model}{suffix}"

    # NVIDIA GTX
    m = re.match(r"(?:NVIDIA\s+)?(?:GeForce\s+)?GTX\s+(\d{4})(?:\s*Ti)?", text, re.IGNORECASE)
    if m:
        ti = " Ti" if "Ti" in text or "ti" in text.lower() else ""
        return f"NVIDIA GTX {m.group(1)}{ti}"

    # NVIDIA MX
    m = re.match(r"(?:NVIDIA\s+)?(?:GeForce\s+)?MX(\d{3,4})", text, re.IGNORECASE)
    if m:
        return f"NVIDIA MX{m.group(1)}"

    # AMD Radeon
    m = re.match(r"Radeon\s+(RX\s+\w+\d*|Graphics)", text, re.IGNORECASE)
    if m:
        return f"AMD Radeon {m.group(1).strip()}"

    # Intel Arc
    if re.match(r"Intel\s+Arc", text, re.IGNORECASE):
        return "Intel Arc"

    # Intel Iris Xe
    if re.match(r"Iris\s+Xe", text, re.IGNORECASE):
        return "Intel Iris Xe"

    # Intel UHD
    m = re.match(r"Intel\s+(UHD|Iris)\s*(\w*)", text, re.IGNORECASE)
    if m:
        return f"Intel {m.group(1).upper()} {m.group(2).title()}".strip()

    return text


def detect_ram_gb(text):
    """Extract RAM in GB. Conservative validation against known values."""
    for pat in _RAM_PATTERNS:
        for m in pat.finditer(text):
            val_str = m.group(1)
            if not val_str:
                continue
            val = int(val_str)
            if val in VALID_RAM_GB:
                return val
            # Also accept multiples of 4 in reasonable range
            if val in range(4, 129) and val % 4 == 0:
                return val
    return None


def detect_storage_gb(text):
    """Extract storage in GB. Handles TB conversion. Conservative validation."""
    for pat in _STORAGE_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1)
            if not raw:
                continue
            val = int(raw)

            # Check if it's TB
            is_tb = bool(re.search(rf"{re.escape(raw)}\s*TB", text, re.IGNORECASE))
            if is_tb:
                gb = val * 1024
            else:
                gb = val

            if gb in VALID_STORAGE_GB:
                return gb
            # Accept 64-16384 range for unusual configs
            if 64 <= gb <= 16384:
                return gb
    return None


def detect_storage_type(text):
    """Detect storage type: SSD, HDD, NVMe, M.2."""
    text_upper = text.upper()
    if "NVME" in text_upper or "M.2" in text_upper:
        return "NVMe"
    if "SSD" in text_upper:
        return "SSD"
    if "HDD" in text_upper:
        return "HDD"
    return ""


def detect_screen_size(text):
    m = _SCREEN_SIZE_PATTERN.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        if raw:
            val = float(raw)
            if m.group(2):
                val = val / 2.54
            if 10 <= val <= 20:
                return round(val, 1)
    return None


def detect_resolution(text):
    m = _RESOLUTION_PATTERN.search(text)
    if not m:
        return ""
    if m.group(1) and m.group(2):
        return f"{m.group(1)}x{m.group(2)}"
    if m.group(3):
        return m.group(3).upper().replace(" ", "")
    return ""


def detect_refresh_rate(text):
    m = _REFRESH_RATE_PATTERN.search(text)
    if m:
        val = int(m.group(1))
        if val in (60, 90, 120, 144, 165, 240, 300, 360):
            return val
    return None


def detect_panel_type(text):
    m = _PANEL_PATTERN.search(text)
    if m:
        return m.group().strip().upper().replace(" ", "")
    return ""


def detect_price(text):
    for m in _PRICE_PATTERN.finditer(text):
        raw = m.group("amount_before") or m.group("amount_after")
        if not raw:
            continue
        matched_currency = _CURRENCY_MAP.get(
            (m.group("currency_after") or m.group("currency_before") or "").upper(),
            detect_currency(m.group(0)),
        )
        cleaned = re.sub(r"[^\d.,]", "", raw).strip()
        if not cleaned:
            continue
        cleaned = cleaned.replace(" ", "")
        if matched_currency == "TRY":
            if "," in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(".", "")
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if len(parts[-1]) == 3:
                cleaned = "".join(parts)
            else:
                cleaned = cleaned.replace(",", ".")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            continue
    return None


def detect_currency(text):
    m = re.search(r"(DA|DZD|TL|TRY|₺|\$|USD|€|EUR)", text, re.IGNORECASE)
    if m:
        return _CURRENCY_MAP.get(m.group().upper(), "DZD")
    return "DZD"


def detect_condition(text):
    text_lower = text.lower()
    for condition, keywords in _CONDITION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return condition
    return "unknown"


def _identity_text(raw_text="", title_raw=""):
    """Prefer human listing text over serialized collector metadata for identity."""
    text = raw_text or title_raw or ""
    if "{\"source\"" in text:
        text = text.split("{\"source\"", 1)[0]
    if '"source" "sahibinden_cdp"' in text:
        text = text.split('"source" "sahibinden_cdp"', 1)[0]
    text = text.strip()
    if title_raw and (not text or len(text) > len(title_raw) * 2):
        return title_raw
    return text or title_raw or raw_text or ""


def _extract_model_text(text, brand):
    """Extract model family from text after removing spec tokens and garbage.

    Strategy:
    1. Find brand position in text.
    2. Take text after brand, up to first known spec keyword.
    3. Clean up: remove specs, garbage words, repeated tokens.
    4. Keep meaningful model family tokens.
    """
    if not brand:
        return ""

    # Find brand position
    brand_match = re.search(re.escape(brand), text, re.IGNORECASE)
    if not brand_match:
        return ""

    after_brand = text[brand_match.end():]

    # Cut at first spec keyword
    spec_cutoff = re.search(
        r"\b(?:i[3579]|i[3579]-\d|Ryzen|RTX|GTX|MX\d|Iris|UHD|Radeon|Intel|AMD|NVIDIA|"
        r"\d+\s*(?:GB|TB|Go|RAM|SSD|HDD|NVMe|Hz|inch|cm)|"
        r"FHD|QHD|4K|UHD|\d{3,4}x\d{3,4})",
        after_brand,
        re.IGNORECASE,
    )
    if spec_cutoff:
        after_brand = after_brand[:spec_cutoff.start()]

    # Also cut at price patterns
    price_match = re.search(r"\d[\d\s.,]*\s*(?:DA|DZD|TL|TRY|€|EUR|\$|USD)", after_brand, re.IGNORECASE)
    if price_match:
        after_brand = after_brand[:price_match.start()]

    # Tokenize and clean
    tokens = re.split(r"[\s\-/,]+", after_brand.strip())
    cleaned = []
    seen = set()

    for token in tokens:
        t = token.strip(".,;:!?()[]{}|/\\")
        if not t:
            continue
        t_lower = t.lower()
        if t_lower in _GARBAGE_WORDS:
            continue
        if t_lower in seen:
            continue
        # Skip pure numbers (likely specs)
        if re.fullmatch(r"\d+", t):
            continue
        # Skip obvious spec fragments
        if re.fullmatch(r"\d+(?:gb|tb|go|cm|inch|hz|ram|ssd|hdd)", t_lower):
            continue
        seen.add(t_lower)
        cleaned.append(t)

    # Remove duplicated brand words
    brand_lower = brand.lower()
    cleaned = [t for t in cleaned if t.lower() != brand_lower]

    return " ".join(cleaned[:5]).strip()


def _detect_series(text, brand):
    """Detect the product series/family for the brand."""
    text_lower = text.lower()
    brand_lower = brand.lower()

    families = _KNOWN_MODEL_FAMILIES.get(brand_lower, set())
    for family in sorted(families, key=len, reverse=True):
        if family in text_lower:
            return family.title()

    return ""


def parse_laptop(raw_text="", title_raw="", raw_payload=None):
    text = raw_text or title_raw or ""
    if not text and raw_payload:
        text = raw_payload.get("title", "") or raw_payload.get("description", "") or ""
    identity_text = _identity_text(text, title_raw)

    brand = detect_brand(identity_text)
    cpu = detect_cpu(identity_text) or detect_cpu(text)
    gpu = detect_gpu(identity_text) or detect_gpu(text)
    ram_gb = detect_ram_gb(text)
    storage_gb = detect_storage_gb(text)
    screen_size = detect_screen_size(text)
    resolution = detect_resolution(text)
    refresh_rate_hz = detect_refresh_rate(text)
    panel_type = detect_panel_type(text)
    condition = detect_condition(text)
    price_original = detect_price(text)
    currency_original = detect_currency(text)

    model_text = _extract_model_text(identity_text, brand)
    series = _detect_series(identity_text, brand)

    segments = []
    if brand:
        m = re.search(re.escape(brand), identity_text, re.IGNORECASE)
        if m:
            segments.append(make_segment("brand", m.group(), m.start(), m.end(), 0.95))
    if cpu:
        m = re.search(re.escape(cpu), text, re.IGNORECASE)
        if m:
            segments.append(make_segment("cpu", m.group(), m.start(), m.end(), 0.9))
    if gpu:
        m = re.search(re.escape(gpu), text, re.IGNORECASE)
        if m:
            segments.append(make_segment("gpu", m.group(), m.start(), m.end(), 0.9))

    segments = merge_segments(sort_segments(segments))

    confidence = 0.0
    if brand:
        confidence += 0.2
    if cpu:
        confidence += 0.2
    if gpu:
        confidence += 0.15
    if ram_gb:
        confidence += 0.1
    if storage_gb:
        confidence += 0.1
    if price_original is not None:
        confidence += 0.1
    if screen_size:
        confidence += 0.05
    if resolution:
        confidence += 0.05
    if condition != "unknown":
        confidence += 0.05

    return {
        "brand_text": brand,
        "model_text": model_text,
        "series": series,
        "cpu": cpu,
        "gpu": gpu,
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "screen_size": screen_size,
        "resolution": resolution,
        "refresh_rate_hz": refresh_rate_hz,
        "panel_type": panel_type,
        "condition": condition,
        "price_original": price_original,
        "currency_original": currency_original,
        "segments": segments,
        "confidence": min(confidence, 1.0),
    }
