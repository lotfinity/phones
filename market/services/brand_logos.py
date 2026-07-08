"""Brand logo helpers using Simple Icons CDN."""

import re
import unicodedata

SIMPLE_ICONS_CDN = "https://cdn.simpleicons.org"

BRAND_LOGO_SLUGS = {
    "apple": "apple",
    "iphone": "apple",
    "ipad": "apple",
    "macbook": "apple",

    "samsung": "samsung",
    "galaxy": "samsung",

    "xiaomi": "xiaomi",
    "mi": "xiaomi",
    "redmi": "xiaomi",
    "poco": "xiaomi",

    "huawei": "huawei",
    "honor": "honor",
    "oppo": "oppo",
    "vivo": "vivo",
    "oneplus": "oneplus",
    "realme": "realme",
    "motorola": "motorola",
    "nokia": "nokia",
    "nothing": "nothing",
    "iqoo": "iqoo",
    "nubia": "nubia",
    "redmagic": "nubia",
    "doogee": "doogee",

    "lenovo": "lenovo",
    "thinkpad": "lenovo",
    "asus": "asus",
    "rog": "asusrog",
    "asus rog": "asusrog",
    "acer": "acer",
    "hp": "hp",
    "dell": "dell",
    "msi": "msi",
    "razer": "razer",
    "alienware": "alienware",
    "microsoft": "microsoft",
    "surface": "microsoft",

    "nvidia": "nvidia",
    "amd": "amd",
    "intel": "intel",

    "sony": "sony",
    "playstation": "playstation",
    "xbox": "xbox",
    "nintendo": "nintendo",
    "meta": "meta",
    "meta quest": "meta",
    "oculus": "oculus",

    "canon": "canon",
    "nikon": "nikon",
    "fujifilm": "fujifilm",
    "gopro": "gopro",
    "dji": "dji",

    "anker": "anker",
    "logitech": "logitech",
    "jbl": "jbl",
    "beats": "beats",
    "bose": "bose",

    "google": "google",
}

_TURKISH_MAP = str.maketrans("ıİğüüşöç", "iIguusoc")


def normalize_brand_key(value):
    if not value or not isinstance(value, str):
        return None
    s = value.strip().lower()
    s = s.translate(_TURKISH_MAP)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def simple_icon_slug(value):
    key = normalize_brand_key(value)
    if not key:
        return None
    slug = BRAND_LOGO_SLUGS.get(key)
    if slug:
        return slug
    for alias, slug in BRAND_LOGO_SLUGS.items():
        if key == normalize_brand_key(alias):
            return slug
    return None


def brand_logo_url(value):
    slug = simple_icon_slug(value)
    if not slug:
        return None
    return f"{SIMPLE_ICONS_CDN}/{slug}"


def brand_initial(value):
    if not value or not isinstance(value, str):
        return "?"
    s = value.strip()
    return s[0].upper() if s else "?"
