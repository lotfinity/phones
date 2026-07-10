"""Parser for portable gaming console marketplace rows."""

import re

from market.services.currency import convert_to_eur
from market.services.parsing.laptop_parser_v2 import (
    detect_condition,
    detect_currency,
    detect_price,
    detect_ram_gb,
    detect_storage_gb,
)


PARSER_VERSION = "console_v1"

_CONSOLE_PATTERNS = [
    (re.compile(r"\b(?:asus\s+)?rog\s+ally\s+x\b", re.IGNORECASE), "ASUS", "ROG Ally X"),
    (re.compile(r"\b(?:asus\s+)?rog\s+ally\b", re.IGNORECASE), "ASUS", "ROG Ally"),
    (re.compile(r"\b(?:lenovo\s+)?legion\s+go\b", re.IGNORECASE), "Lenovo", "Legion Go"),
    (re.compile(r"\b(?:valve\s+)?steam\s+deck\s+oled\b", re.IGNORECASE), "Valve", "Steam Deck OLED"),
    (re.compile(r"\b(?:valve\s+)?steam\s+deck\b", re.IGNORECASE), "Valve", "Steam Deck"),
    (re.compile(r"\b(?:msi\s+)?claw\b", re.IGNORECASE), "MSI", "Claw"),
    (re.compile(r"\bnintendo\s+switch\s+oled\b|\bswitch\s+oled\b", re.IGNORECASE), "Nintendo", "Switch OLED"),
    (re.compile(r"\bnintendo\s+switch\s+lite\b|\bswitch\s+lite\b", re.IGNORECASE), "Nintendo", "Switch Lite"),
    (re.compile(r"\bnintendo\s+switch\b", re.IGNORECASE), "Nintendo", "Switch"),
    (re.compile(r"\b(?:playstation|ps)\s*portal\b", re.IGNORECASE), "Sony", "PlayStation Portal"),
    (re.compile(r"\bxbox\s+ally\s+x\b", re.IGNORECASE), "Microsoft", "Xbox Ally X"),
    (re.compile(r"\bxbox\s+ally\b", re.IGNORECASE), "Microsoft", "Xbox Ally"),
]

_CHIPSET_PATTERNS = [
    (re.compile(r"\bz1\s+extreme\b", re.IGNORECASE), "AMD Z1 Extreme"),
    (re.compile(r"\bryzen\s+z1\b", re.IGNORECASE), "AMD Z1"),
    (re.compile(r"\bcore\s+ultra\s+7\b", re.IGNORECASE), "Intel Core Ultra 7"),
    (re.compile(r"\btegra\b", re.IGNORECASE), "NVIDIA Tegra"),
]

_REFRESH_RE = re.compile(r"\b(60|90|120|144)\s*hz\b", re.IGNORECASE)
_SCREEN_RE = re.compile(r"\b(5\.5|6\.2|7|7\.4|8|8\.8)\s*(?:inch|in|\"|pouce)?\b", re.IGNORECASE)


def is_portable_console_text(text):
    text = re.sub(r"[-_/]+", " ", text or "")
    return any(pattern.search(text) for pattern, _brand, _model in _CONSOLE_PATTERNS)


def detect_console_identity(text):
    text = re.sub(r"[-_/]+", " ", text or "")
    for pattern, brand, model in _CONSOLE_PATTERNS:
        if pattern.search(text or ""):
            return brand, model
    return "", ""


def detect_chipset(text):
    text = re.sub(r"[-_/]+", " ", text or "")
    for pattern, chipset in _CHIPSET_PATTERNS:
        if pattern.search(text or ""):
            return chipset
    return ""


def detect_refresh_rate_hz(text):
    m = _REFRESH_RE.search(text or "")
    return int(m.group(1)) if m else None


def detect_screen_size(text):
    m = _SCREEN_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_console(raw_text="", title="", payload=None):
    payload = payload or {}
    text = "\n".join(
        str(part or "")
        for part in [
            title,
            raw_text,
            payload.get("url", ""),
            payload.get("listing_url", ""),
            payload.get("raw_title", ""),
        ]
        if part
    )
    brand, model = detect_console_identity(text)
    price_original = detect_price(text)
    currency_original = detect_currency(text) if price_original is not None else ""
    price_eur = convert_to_eur(price_original, currency_original) if price_original and currency_original else None
    storage_gb = detect_storage_gb(text)
    ram_gb = detect_ram_gb(text)
    chipset = detect_chipset(text)
    refresh_rate_hz = detect_refresh_rate_hz(text)
    screen_size = detect_screen_size(text)

    confidence = 0.0
    if brand:
        confidence += 0.35
    if model:
        confidence += 0.35
    if storage_gb:
        confidence += 0.1
    if chipset or ram_gb:
        confidence += 0.1
    if price_original:
        confidence += 0.1

    return {
        "brand_text": brand,
        "model_text": model,
        "variant_text": "",
        "chipset": chipset,
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "screen_size": screen_size,
        "refresh_rate_hz": refresh_rate_hz,
        "connectivity": "",
        "color": "",
        "condition": detect_condition(text),
        "price_original": price_original,
        "currency_original": currency_original,
        "price_eur": price_eur,
        "segments": [],
        "confidence": min(confidence, 1.0),
        "parser_version": PARSER_VERSION,
    }
