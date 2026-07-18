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
VALID_PHONE_RAM_GB = {2, 3, 4, 6, 8, 12, 16, 18, 24, 32, 36, 48, 64}

MODEL_PATTERNS = [
    r"(?:Samsung\s+)?Galaxy\s+(?:S\d+\s*(?:Ultra|Plus|\+|FE|Pro)?)",
    r"(?:Samsung\s+)?Galaxy\s+(?:A\d+[a-z]*)",
    r"(?:Samsung\s+)?Galaxy\s+(?:Z\s*(?:Flip|Fold)\s*\d*)",
    r"(?:Samsung\s+)?Galaxy\s+(?:Note\s*\d+)",
    r"(?:\biPhone\s+SE\b|\bSE\s*(?:20\d{2}|\d(?:st|nd|rd)?\s*gen)\b)",
    r"iPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|\+|mini|SE|E)?",
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
    r"([\d \t.,]+)[ \t]*(?:DA|DZD|TL|TRY|₺|\$|USD|€|EUR)\b|"
    r"(?:DA|DZD|TL|TRY|₺|\$|USD|€|EUR)[ \t]*([\d \t.,]+)|"
    r"(?:prix|price)\D{0,12}(\d[\d \t.,]{2,})",
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

BATTERY_HEALTH_PATTERN = re.compile(
    r"(\d{1,3})\s*%|(?:batterie|battery)\D{0,12}(\d{1,3})",
    re.IGNORECASE,
)

BOX_PATTERN = re.compile(
    r"\b(kapal[ıi]\s*kutu|sealed|open\s*box|a[cç][ıi]k\s*kutu|kutu[su]?\s*(?:i[cç]erir|mevcut)|box)\b",
    re.IGNORECASE,
)

STORE_WARRANTY_PATTERN = re.compile(
    r"\b(?:garantie|garenty|garentie|warranty)\s*(?:boutique|store)?\s*[:=]?\s*\d+\s*(?:mois|jour|jours|days?|months?)\b",
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
            model = m.group().strip()
            if re.match(r"(?i)^SE\b", model):
                return f"iPhone {model}"
            return model
    return ""


def _valid_storage(value):
    try:
        gb = int(value)
    except (TypeError, ValueError):
        return None
    return gb if gb in VALID_PHONE_STORAGE_GB else None


def _int_from_structured(value):
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None


def _structured_price(data):
    price = data.get("price")
    if isinstance(price, dict):
        amount = price.get("amount")
    else:
        amount = price
    if amount in (None, ""):
        return None
    try:
        return Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _structured_currency(data):
    price = data.get("price")
    if isinstance(price, dict) and price.get("currency"):
        return str(price.get("currency")).upper()
    return detect_currency(" ".join(str(item) for item in [data.get("price"), data.get("visible_text")] if item))


def _structured_text_payload(raw_payload):
    if not isinstance(raw_payload, dict):
        return {}
    data = raw_payload.get("nvidia_structured")
    return data if isinstance(data, dict) else {}


def _visible_text_section(text):
    match = re.search(r"(?is)\bVisible text\s*:\s*(.+)$", text or "")
    if not match:
        return ""
    lines = []
    for line in match.group(1).splitlines():
        clean = line.strip()
        if not clean:
            continue
        lines.append(clean)
        if len(lines) >= 3 and re.search(r"(?i)\b(?:prix|price)\b", clean):
            break
        if len(lines) >= 6:
            break
    return "\n".join(lines)


def _model_key(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _visible_model_keys(text):
    keys = set()
    for pattern in MODEL_PATTERNS:
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            keys.add(_model_key(detect_model(match.group())))
    return {key for key in keys if key}


def _visible_identity_override(text, brand, model):
    visible_text = _visible_text_section(text)
    if not visible_text:
        return {}
    if len(_visible_model_keys(visible_text)) > 1:
        return {}
    visible_brand = detect_brand(visible_text)
    visible_model = detect_model(visible_text, visible_brand or brand)
    if not visible_model:
        return {}
    return {
        "visible_text": visible_text,
        "brand": visible_brand or brand or ("Apple" if "iphone" in visible_model.lower() else ""),
        "model": visible_model,
        "storage_gb": detect_storage(visible_text),
        "ram_gb": detect_ram(visible_text) if re.search(r"(?i)\bram\b|\b(?:2|3|4|6|8|12|16)\s*/\s*(?:64|128|256|512)\b", visible_text) else None,
        "sim_config": detect_sim(visible_text),
        "battery_health": detect_battery_health(visible_text),
        "condition": detect_condition(visible_text),
        "box_status": detect_box_status(visible_text),
        "store_warranty": detect_store_warranty(visible_text),
        "price_original": detect_price(visible_text),
        "currency_original": detect_currency(visible_text),
    }


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
        raw = m.group(1) or m.group(2) or m.group(3)
        if not raw:
            continue
        if m.group(3):
            number_tokens = re.findall(r"\d[\d.,]*", raw)
            if number_tokens:
                raw = number_tokens[-1]
        cleaned = _normalize_money_token(raw)
        if not cleaned:
            continue
        try:
            price = Decimal(cleaned)
        except InvalidOperation:
            continue
        if price <= 0 or price > Decimal("1000000000"):
            continue
        return price
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
        val = int(m.group(1) or m.group(2))
        if 1 <= val <= 100:
            return val
    return None


def detect_condition(text):
    text_lower = text.lower()
    if re.search(r"\b(?:etat|état)\s*(?:10|20)\s*/\s*(?:10|20)\b", text_lower):
        return "used_a_plus"
    if re.search(r"\b(?:etat|état)\s*9\s*/\s*10\b", text_lower):
        return "used_a"
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


def detect_store_warranty(text):
    m = STORE_WARRANTY_PATTERN.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group()).strip()


def parse_phone(raw_text="", title_raw="", raw_payload=None):
    """Parse phone listing text. Returns dict with extracted fields and segments."""
    text = raw_text or title_raw or ""
    if not text and raw_payload:
        text = raw_payload.get("title", "") or raw_payload.get("description", "") or ""
    structured = _structured_text_payload(raw_payload)

    brand = structured.get("brand") or detect_brand(text)
    model = structured.get("model") or detect_model(text, brand)
    visible_override = _visible_identity_override(text, brand, model)
    if visible_override:
        brand = visible_override.get("brand") or brand
        model = visible_override["model"]
    storage_gb = _valid_storage(_int_from_structured(structured.get("storage_gb"))) if structured else None
    if visible_override and visible_override.get("storage_gb"):
        storage_gb = visible_override["storage_gb"]
    if storage_gb is None:
        storage_gb = detect_storage(text)
    ram_gb = None
    if visible_override:
        ram_gb = visible_override.get("ram_gb")
    elif structured:
        ram_value = _int_from_structured(structured.get("ram_gb"))
        ram_gb = ram_value if ram_value in VALID_PHONE_RAM_GB else None
    else:
        ram_gb = detect_ram(text)
    if visible_override:
        sim_config = visible_override.get("sim_config") or ""
    else:
        sim_config = structured.get("sim") or detect_sim(text)
    battery_health = _int_from_structured(structured.get("battery_health")) if structured else None
    if visible_override and visible_override.get("battery_health") is not None:
        battery_health = visible_override["battery_health"]
    if battery_health is None:
        battery_health = detect_battery_health(text)
    condition = visible_override.get("condition") if visible_override else ""
    condition = condition if condition and condition != "unknown" else detect_condition(text)
    box_status = visible_override.get("box_status", "") if visible_override else detect_box_status(text)
    price_original = _structured_price(structured) if structured else None
    if visible_override and visible_override.get("price_original") is not None:
        price_original = visible_override["price_original"]
    if price_original is None:
        price_original = detect_price(text)
    currency_original = visible_override.get("currency_original") if visible_override else ""
    currency_original = currency_original or (_structured_currency(structured) if structured else detect_currency(text))
    color = structured.get("color", "") if structured else ""
    store_warranty = ""
    if visible_override:
        store_warranty = visible_override.get("store_warranty", "")
    if structured:
        store_warranty = store_warranty or structured.get("store_warranty") or structured.get("warranty") or ""

    segments = []
    if brand:
        idx = text.lower().find(brand.lower())
        if idx >= 0:
            segments.append(make_segment("brand", text[idx:idx + len(brand)], idx, idx + len(brand), 0.95))
    segment_text = visible_override.get("visible_text") if visible_override else text
    if model:
        m = re.search(re.escape(model), segment_text, re.IGNORECASE)
        if m:
            segments.append(make_segment("model", m.group(), m.start(), m.end(), 0.9))
    if storage_gb:
        sm = STORAGE_PATTERN.search(segment_text)
        if sm:
            raw_val = sm.group()
            idx = segment_text.find(raw_val)
            if idx >= 0:
                segments.append(make_segment("storage", raw_val, idx, idx + len(raw_val), 0.85))
    if ram_gb:
        rm = RAM_PATTERN.search(segment_text)
        if rm:
            raw_val = rm.group()
            idx = segment_text.find(raw_val)
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
        "store_warranty": store_warranty,
        "color": color,
        "condition": condition,
        "price_original": price_original,
        "currency_original": currency_original,
        "segments": segments,
        "confidence": min(confidence, 1.0),
    }
