"""Laptop listing parser v2 — regex-based extraction from raw text."""

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
    "asus": "ASUS",
    "rog": "ASUS",
    "tuf": "ASUS",
    "dell": "Dell",
    "inspiron": "Dell",
    "latitude": "Dell",
    "xps": "Dell",
    "alienware": "Dell",
    "hp": "HP",
    "pavilion": "HP",
    "spectre": "HP",
    "omen": "HP",
    "elitebook": "HP",
    "acer": "Acer",
    "nitro": "Acer",
    "predator": "Acer",
    "swift": "Acer",
    "macbook": "Apple",
    "apple": "Apple",
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

CPU_PATTERNS = [
    r"i[3579]-?\d{4,5}[A-Z]*",
    r"core\s+ultra\s+\d+\s*\d*[A-Z]*",
    r"R[579]-?\d{4}[A-Z]*",
    r"Ryzen\s+[3579]\s+\d{4}[A-Z]*",
    r"Apple\s+M[1234]\s*(?:Pro|Max|Ultra)?",
    r"M[1234]\s*(?:Pro|Max|Ultra)",
    r"Snapdragon\s+\w+\s*\d*",
]

GPU_PATTERNS = [
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?RTX\s+\d{4}(?:\s*(?:Ti|Laptop))?",
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?GTX\s+\d{4}(?:\s*(?:Ti))?",
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?MX\d{3,4}",
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?RTX\s+Ada\s+\w+\s*\d*",
    r"Radeon\s+RX\s+\w+\d*",
    r"Radeon\s+Graphics",
    r"Iris\s+Xe",
    r"Intel\s+(?:UHD|Iris)\s+\w*",
    r"Apple\s+GPU",
]

RAM_PATTERN = re.compile(
    r"(\d{1,3})\s*(?:GB|Go)\s*(?:RAM|ram)?|"
    r"(?:RAM|ram)\s*[:=]?\s*(\d{1,3})\s*(?:GB|Go)?",
    re.IGNORECASE,
)

STORAGE_PATTERN = re.compile(
    r"(\d{1,4})\s*(?:GB|TB|Go)\s*(?:SSD|HDD|NVMe|nvme|ssd|hdd)?|"
    r"(?:SSD|HDD|NVMe)\s*[:=]?\s*(\d{1,4})\s*(?:GB|TB|Go)?|"
    r"(\d{1,4})\s*(?:GB|TB)\s*(?:SSD|HDD)",
    re.IGNORECASE,
)

SCREEN_SIZE_PATTERN = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:inch|\")\b|"
    r"(\d{2,3})\s*(?:cm)\b",
    re.IGNORECASE,
)

RESOLUTION_PATTERN = re.compile(
    r"(\d{3,4})\s*x\s*(\d{3,4})\b|"
    r"\b(FHD|Full\s*HD|QHD|2K|4K|UHD|HD|WQXGA|WXGA|FHD\+|QHD\+)\b",
    re.IGNORECASE,
)

REFRESH_RATE_PATTERN = re.compile(
    r"(\d{2,3})\s*Hz\b",
    re.IGNORECASE,
)

PANEL_PATTERN = re.compile(
    r"\b(IPS|VA|TN|OLED|AMOLED|Mini[\s-]?LED|IPS[\s-]?Level|触摸|Touch)\b",
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

CONDITION_KEYWORDS = {
    "sealed": ["sealed", "new", "yeni", "mint", "kapalı kutu", "unopened"],
    "used_a_plus": ["excellent", "like new", "mükemmel"],
    "used_a": ["very good", "iyi", "clean"],
    "used_b": ["good", "fair"],
    "used": ["used", "ikinci el", "kullanılmış", "pre-owned"],
}


def detect_brand(text):
    text_lower = text.lower()
    for keyword, brand_name in LAPTOP_BRANDS.items():
        if keyword in text_lower:
            return brand_name
    return ""


def detect_cpu(text):
    for pattern in CPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group().strip()
    return ""


def detect_gpu(text):
    for pattern in GPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group().strip()
    return ""


def detect_ram_gb(text):
    for m in RAM_PATTERN.finditer(text):
        val = m.group(1) or m.group(2)
        if val:
            gb = int(val)
            if 1 <= gb <= 128:
                return gb
    return None


def detect_storage_gb(text):
    for m in STORAGE_PATTERN.finditer(text):
        raw = m.group(1) or m.group(2) or m.group(3)
        if not raw:
            continue
        val = int(raw)
        is_tb = bool(re.search(rf"{raw}\s*TB", text, re.IGNORECASE))
        if is_tb:
            gb = val * 1024
        else:
            gb = val
        if 64 <= gb <= 8192:
            return gb
    return None


def detect_screen_size(text):
    m = SCREEN_SIZE_PATTERN.search(text)
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
    m = RESOLUTION_PATTERN.search(text)
    if not m:
        return ""
    if m.group(1) and m.group(2):
        return f"{m.group(1)}x{m.group(2)}"
    if m.group(3):
        return m.group(3).upper().replace(" ", "")
    return ""


def detect_refresh_rate(text):
    m = REFRESH_RATE_PATTERN.search(text)
    if m:
        val = int(m.group(1))
        if val in (60, 90, 120, 144, 165, 240, 300, 360):
            return val
    return None


def detect_panel_type(text):
    m = PANEL_PATTERN.search(text)
    if m:
        return m.group().strip().upper().replace(" ", "")
    return ""


def detect_price(text):
    for m in PRICE_PATTERN.finditer(text):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        cleaned = re.sub(r"[^\d.,]", "", raw).strip()
        if not cleaned:
            continue
        cleaned = cleaned.replace(" ", "")
        if "," in cleaned and "." in cleaned:
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
        return CURRENCY_MAP.get(m.group().upper(), "DZD")
    return "DZD"


def detect_condition(text):
    text_lower = text.lower()
    for condition, keywords in CONDITION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return condition
    return "unknown"


def parse_laptop(raw_text="", title_raw="", raw_payload=None):
    text = raw_text or title_raw or ""
    if not text and raw_payload:
        text = raw_payload.get("title", "") or raw_payload.get("description", "") or ""

    brand = detect_brand(text)
    cpu = detect_cpu(text)
    gpu = detect_gpu(text)
    ram_gb = detect_ram_gb(text)
    storage_gb = detect_storage_gb(text)
    screen_size = detect_screen_size(text)
    resolution = detect_resolution(text)
    refresh_rate_hz = detect_refresh_rate(text)
    panel_type = detect_panel_type(text)
    condition = detect_condition(text)
    price_original = detect_price(text)
    currency_original = detect_currency(text)

    model_text = ""
    if brand:
        brand_pattern = re.compile(re.escape(brand), re.IGNORECASE)
        m = brand_pattern.search(text)
        if m:
            rest = text[m.end():].strip()
            words = rest.split()[:4]
            model_text = " ".join(words)

    segments = []
    if brand:
        m = re.search(re.escape(brand), text, re.IGNORECASE)
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
        "series": "",
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
