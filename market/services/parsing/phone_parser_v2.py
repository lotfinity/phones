"""Phone listing parser v2 — regex-based extraction from raw text."""

import re
from decimal import Decimal, InvalidOperation

from market.services.parsing.segments import (
    find_regex_segments,
    make_segment,
    merge_segments,
    sort_segments,
)

PHONE_BRANDS = {
    "samsung": "Samsung",
    "galaxy": "Samsung",
    "apple": "Apple",
    "iphone": "Apple",
    "xiaomi": "Xiaomi",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "huawei": "Huawei",
    "oppo": "OPPO",
    "vivo": "Vivo",
    "oneplus": "OnePlus",
    "honor": "Honor",
    "google": "Google",
    "pixel": "Google",
    "nokia": "Nokia",
    "motorola": "Motorola",
    "moto": "Motorola",
    "realme": "Realme",
    "tecno": "Tecno",
    "infinix": "Infinix",
    "iqoo": "iQOO",
    "lenovo": "Lenovo",
    "sony": "Sony",
    "asus": "ASUS",
    "nothing": "Nothing",
}

VALID_PHONE_STORAGE_GB = {64, 128, 256, 512, 1024, 2048}

MODEL_PATTERNS = [
    r"(?:Samsung\s+)?Galaxy\s+(?:S\d+\s*(?:Ultra|Plus|\+|FE|Pro)?)",
    r"(?:Samsung\s+)?Galaxy\s+(?:A\d+[a-z]*)",
    r"(?:Samsung\s+)?Galaxy\s+(?:Z\s*(?:Flip|Fold)\s*\d*)",
    r"(?:Samsung\s+)?Galaxy\s+(?:Note\s*\d+)",
    r"iPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|\+|mini|SE)?",
    r"Redmi\s+(?:Note\s+)?\d+\s*(?:Pro\s*Plus|Pro|Plus|\+)?",
    r"Poco\s+\w+\d+",
    r"Honor\s+(?:Magic\s+\d+\s*(?:Pro|Ultimate)?|[NX]\d+[a-z]*)",
    r"Pixel\s+\d+\s*(?:Pro|a)?",
    r"OnePlus\s+\d+\s*(?:Pro|T|RT|CE)?",
    r"OPPO\s+(?:Find|reno|A)\s*\d+\w*",
    r"Vivo\s+(?:V|X|Y)\d+\w*",
    r"Realme\s+(?:GT|GT\s*Neo|Number|C|Narzo)\s*\d+\w*",
    r"Motorola\s+(?:Edge|ThinkPhone|Moto\s+)?\w*\s*\d+",
]

STORAGE_PATTERN = re.compile(
    r"(\d{2,4})\s*(?:GB|Go|Mo|gb|go)\b|"
    r"(?:storage|kapasite|hafiza|hafıza)\s*[:=]?\s*(\d{2,4})\s*(?:GB|Go)?\b|"
    r"\b(\d{1,4})\s*/\s*(\d{2,4})\b",
    re.IGNORECASE,
)

RAM_PATTERN = re.compile(
    r"(\d{1,2})\s*(?:GB|Go|ram)\b|"
    r"(?:ram)\s*[:=]?\s*(\d{1,2})\s*(?:GB|Go)?\b|"
    r"\b(\d{1,2})\s*/\s*\d{2,4}\b",
    re.IGNORECASE,
)

PRICE_PATTERN = re.compile(
    r"([\d\s.,]+)\s*(?:DA|DZD|TL|TRY|₺|\$|USD|€|EUR)\b|"
    r"(?:DA|DZD|TL|TRY|₺|\$|USD|€|EUR)\s*([\d\s.,]+)",
    re.IGNORECASE,
)

CURRENCY_MAP = {
    "DA": "DZD", "DZD": "DZD",
    "TL": "TRY", "TRY": "TRY", "₺": "TRY",
    "$": "USD", "USD": "USD",
    "€": "EUR", "EUR": "EUR",
}

SIM_PATTERN = re.compile(
    r"\b(2\s*sim|dual\s*sim|dualsim|duos|2sim|single\s*sim|1\s*sim|esim)\b",
    re.IGNORECASE,
)

BATTERY_HEALTH_PATTERN = re.compile(r"(\d{1,3})\s*%", re.IGNORECASE)

BOX_PATTERN = re.compile(
    r"\b(kapal[ıi]\s*kutu|sealed|open\s*box|a[cç][ıi]k\s*kutu|kutu[su]?\s*(?:i[cç]erir|mevcut)|box)\b",
    re.IGNORECASE,
)

CONDITION_KEYWORDS = {
    "sealed": ["sealed", "kapalı kutu", "new", "yeni", "mint"],
    "used_a_plus": ["excellent", "mükemmel", "a+"],
    "used_a": ["very good", "iyi", "clean"],
    "used_b": ["good", "kabul edilebilir"],
    "used": ["used", "ikinci el", "kullanılmış"],
}


def detect_brand(text):
    text_lower = text.lower()
    for keyword, brand_name in PHONE_BRANDS.items():
        if keyword in text_lower:
            return brand_name
    return ""


def detect_model(text, brand=""):
    for pattern in MODEL_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group().strip()
    return ""


def _valid_storage(value):
    try:
        gb = int(value)
    except (TypeError, ValueError):
        return None
    return gb if gb in VALID_PHONE_STORAGE_GB else None


def detect_storage(text):
    slash = re.search(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b", text or "")
    if slash:
        first = int(slash.group(1))
        second = int(slash.group(2))
        if first <= 32:
            value = _valid_storage(second)
            if value:
                return value
        value = _valid_storage(first)
        if value:
            return value
        value = _valid_storage(second)
        if value:
            return value

    for m in STORAGE_PATTERN.finditer(text):
        val = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        value = _valid_storage(val)
        if value:
            return value
    return None


def detect_ram(text):
    for m in RAM_PATTERN.finditer(text):
        val = m.group(1) or m.group(2) or m.group(3)
        if val:
            gb = int(val)
            if 1 <= gb <= 32:
                return gb
    return None


def _normalize_money_token(raw):
    """Normalize marketplace money text into Decimal-compatible form.

    Turkish/Algerian marketplace prices often use dots as thousands separators:
    `49.500 TL` should be 49500, not 49.500. Keep true decimal separators
    only when the trailing group is not a thousands group.
    """
    cleaned = re.sub(r"[^\d.,]", "", raw or "").strip().replace(" ", "")
    if not cleaned:
        return ""

    if "," in cleaned and "." in cleaned:
        # Turkish style: 47.499,99 -> 47499.99
        if cleaned.rfind(",") > cleaned.rfind("."):
            return cleaned.replace(".", "").replace(",", ".")
        # US style: 47,499.99 -> 47499.99
        return cleaned.replace(",", "")

    if "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            return "".join(parts)
        return cleaned.replace(",", ".")

    if "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) and all(part.isdigit() for part in parts):
            return "".join(parts)
        return cleaned

    return cleaned


def detect_price(text):
    for m in PRICE_PATTERN.finditer(text):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        cleaned = _normalize_money_token(raw)
        if not cleaned:
            continue
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            continue
    return None


def detect_currency(text):
    m = re.search(r"(DA|DZD|TL|TRY|₺|\$|USD|€|EUR)", text, re.IGNORECASE)
    if m:
        return CURRENCY_MAP.get(m.group().upper(), "DZD")
    return "DZD"


def detect_sim(text):
    m = SIM_PATTERN.search(text)
    if not m:
        return ""
    raw = re.sub(r"\s+", "", m.group().lower())
    if raw in ("2sim", "dualsim", "duos", "2sim"):
        return "2sim"
    if raw in ("esim", "e-sim"):
        return "esim"
    return ""


def detect_battery_health(text):
    m = BATTERY_HEALTH_PATTERN.search(text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 100:
            return val
    return None


def detect_condition(text):
    text_lower = text.lower()
    for condition, keywords in CONDITION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return condition
    return "unknown"


def detect_box_status(text):
    m = BOX_PATTERN.search(text)
    if not m:
        return ""
    raw = m.group().lower()
    if any(k in raw for k in ("kapalı", "sealed")):
        return "sealed"
    if any(k in raw for k in ("açık", "open")):
        return "open_box"
    return "box"


def parse_phone(raw_text="", title_raw="", raw_payload=None):
    """Parse phone listing text. Returns dict with extracted fields and segments."""
    text = raw_text or title_raw or ""
    if not text and raw_payload:
        text = raw_payload.get("title", "") or raw_payload.get("description", "") or ""

    brand = detect_brand(text)
    model = detect_model(text, brand)
    storage_gb = detect_storage(text)
    ram_gb = detect_ram(text)
    sim_config = detect_sim(text)
    battery_health = detect_battery_health(text)
    condition = detect_condition(text)
    box_status = detect_box_status(text)
    price_original = detect_price(text)
    currency_original = detect_currency(text)

    segments = []
    if brand:
        idx = text.lower().find(brand.lower())
        if idx >= 0:
            segments.append(make_segment("brand", text[idx:idx + len(brand)], idx, idx + len(brand), 0.95))
    if model:
        m = re.search(re.escape(model), text, re.IGNORECASE)
        if m:
            segments.append(make_segment("model", m.group(), m.start(), m.end(), 0.9))
    if storage_gb:
        sm = STORAGE_PATTERN.search(text)
        if sm:
            raw_val = sm.group()
            idx = text.find(raw_val)
            if idx >= 0:
                segments.append(make_segment("storage", raw_val, idx, idx + len(raw_val), 0.85))
    if ram_gb:
        rm = RAM_PATTERN.search(text)
        if rm:
            raw_val = rm.group()
            idx = text.find(raw_val)
            if idx >= 0:
                segments.append(make_segment("ram", raw_val, idx, idx + len(raw_val), 0.8))

    segments = merge_segments(sort_segments(segments))

    confidence = 0.0
    if brand:
        confidence += 0.25
    if model:
        confidence += 0.25
    if storage_gb:
        confidence += 0.15
    if price_original is not None:
        confidence += 0.15
    if sim_config:
        confidence += 0.05
    if ram_gb:
        confidence += 0.05
    if condition != "unknown":
        confidence += 0.05
    if battery_health is not None:
        confidence += 0.05

    return {
        "brand_text": brand,
        "model_text": model,
        "storage_gb": storage_gb,
        "ram_gb": ram_gb,
        "sim_config": sim_config,
        "battery_health": battery_health,
        "battery_cycles": None,
        "box_status": box_status,
        "condition": condition,
        "price_original": price_original,
        "currency_original": currency_original,
        "segments": segments,
        "confidence": min(confidence, 1.0),
    }
