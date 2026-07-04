import re
import unicodedata

KNOWN_BRANDS = [
    ("Apple", ["apple", "iphone", "ipad", "macbook", "appelle"]),
    ("Samsung", ["samsung", "samasung", "galaxy"]),
    ("Xiaomi", ["xiaomi", "redmi", "poco", "mi"]),
    ("Huawei", ["huawei"]),
    ("Honor", ["honor"]),
    ("Vivo", ["vivo"]),
    ("Oppo", ["oppo"]),
    ("OnePlus", ["oneplus", "one plus"]),
    ("Google", ["google", "pixel"]),
    ("Motorola", ["motorola"]),
    ("Realme", ["realme"]),
    ("Redmagic", ["redmagic", "red magic"]),
    ("Doogee", ["doogee"]),
    ("Nubia", ["nubia"]),
    ("BlackView", ["blackview", "black view"]),
    ("GoPro", ["gopro", "go pro"]),
    ("IQoo", ["iqoo", "i qoo"]),
]

BRAND_ALIASES = {brand: aliases for brand, aliases in KNOWN_BRANDS}


def normalize_text(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("İ", "I").replace("ı", "i")
    return re.sub(r"\s+", " ", value).strip()


def slug_model_text(value):
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value).lower()).strip()


def likely_brand(value):
    normalized = f" {slug_model_text(value)} "
    for brand, aliases in KNOWN_BRANDS:
        if any(f" {slug_model_text(alias)} " in normalized for alias in aliases):
            return brand
    return ""


def normalize_samsung_model_tokens(parts):
    cleaned = [part for part in parts if part not in {"samsung", "samasung"}]
    normalized = []
    skip_next = False
    for index, part in enumerate(cleaned):
        if skip_next:
            skip_next = False
            continue
        next_part = cleaned[index + 1] if index + 1 < len(cleaned) else ""
        if part in {"64", "128", "256", "512", "1024"}:
            continue
        if re.match(r"^\d+(?:gb|g|go|tb|ram|sim|mha|mah|mpxl)$", part):
            continue
        if part in {"gb", "g", "go", "tb", "ram", "sim", "duos", "dual"}:
            continue
        if next_part in {"gb", "g", "go", "tb", "ram", "sim", "mha", "mah", "mpxl"} and part.isdigit():
            skip_next = True
            continue
        short_ultra = re.match(r"^(s\d+)u$", part)
        if short_ultra:
            normalized.extend([short_ultra.group(1), "ultra"])
            continue
        short_fe = re.match(r"^(s\d+)fe$", part)
        if short_fe:
            normalized.extend([short_fe.group(1), "fe"])
            continue
        if part == "zflip":
            normalized.extend(["z", "flip"])
            continue
        if part == "zfold":
            normalized.extend(["z", "fold"])
            continue
        normalized.append(part)
    cleaned = normalized
    if not cleaned:
        return cleaned
    if cleaned[0] == "galaxy":
        return cleaned
    if re.match(r"^(?:s|a|z|m|note)\d+", cleaned[0]):
        return ["galaxy", *cleaned]
    return cleaned


def canonical_samsung_parts(parts):
    text = " ".join(parts)
    if match := re.search(r"\bgalaxy\s+z\s+(fold|flip)\s+(\d+)\b", text):
        return ["galaxy", "z", match.group(1), match.group(2)]
    if match := re.search(r"\bgalaxy\s+z\s+trifold\b", text):
        return ["galaxy", "z", "trifold"]
    if match := re.search(r"\bgalaxy\s+(s|a|m)(\d+)\s*(ultra|plus|edge|fe)?\b", text):
        tokens = ["galaxy", f"{match.group(1)}{match.group(2)}"]
        if match.group(3):
            tokens.append(match.group(3))
        return tokens
    if match := re.search(r"\bgalaxy\s+note\s+(\d+)\s*(ultra|plus|fe)?\b", text):
        tokens = ["galaxy", "note", match.group(1)]
        if match.group(2):
            tokens.append(match.group(2))
        return tokens
    if match := re.search(r"\bgalaxy\s+tab\s+([as])\s*(\d+)\s*(fe|plus|ultra)?\b", text):
        tokens = ["galaxy", "tab", match.group(1), match.group(2)]
        if match.group(3):
            tokens.append(match.group(3))
        return tokens
    if match := re.search(r"\bgalaxy\s+watch\s+(\d+)\s*(classic)?\b", text):
        tokens = ["galaxy", "watch", match.group(1)]
        if match.group(2):
            tokens.append(match.group(2))
        return tokens
    if match := re.search(r"\bgalaxy\s+buds\s+(\d+|fe)\s*(pro|fe)?\b", text):
        tokens = ["galaxy", "buds", match.group(1)]
        if match.group(2):
            tokens.append(match.group(2))
        return tokens
    return parts


def canonical_model_name(raw_model):
    raw_model = normalize_text(raw_model)
    lowered = slug_model_text(raw_model)
    replacements = {
        "pro max": "Pro Max",
        "promax": "Pro Max",
        "ultra": "Ultra",
        "plus": "Plus",
    }
    parts = lowered.split()
    if likely_brand(raw_model) == "Samsung":
        parts = normalize_samsung_model_tokens(parts)
        parts = canonical_samsung_parts(parts)

    tokens = []
    for part in parts:
        if part in {"iphone", "samsung", "galaxy", "xiaomi", "redmi", "poco", "mi", "macbook"}:
            tokens.append(part.title() if part != "iphone" else "iPhone")
        elif part.isdigit():
            tokens.append(part)
        else:
            tokens.append(replacements.get(part, part.upper() if len(part) <= 2 else part.title()))
    label = " ".join(tokens)
    label = label.replace("Pro Max", "Pro Max").replace("Iphone", "iPhone")
    return label or raw_model
