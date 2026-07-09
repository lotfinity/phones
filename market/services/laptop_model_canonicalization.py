"""Helpers for normalizing laptop model names across marketplace text variants."""

import re


def ascii_fold(value):
    """Fold Turkish casing variants and common dotted-I variants for matching."""
    return (
        str(value or "")
        .replace("İ", "I")
        .replace("ı", "i")
        .replace("ş", "s")
        .replace("Ş", "S")
        .replace("ğ", "g")
        .replace("Ğ", "G")
        .replace("ü", "u")
        .replace("Ü", "U")
        .replace("ö", "o")
        .replace("Ö", "O")
        .replace("ç", "c")
        .replace("Ç", "C")
    )


# Brand prefixes to strip when normalizing.
_BRAND_PREFIXES = {
    "apple", "lenovo", "asus", "dell", "hp", "acer", "msi", "razer",
    "samsung", "lg", "gigabyte", "huawei", "microsoft",
}

# Aliases: map common variations to canonical family names.
_FAMILY_ALIASES = {
    "macbook air": "MacBook Air",
    "macbookpro": "MacBook Pro",
    "macbook pro": "MacBook Pro",
    "macbook air m1": "MacBook Air M1",
    "macbook air m2": "MacBook Air M2",
    "macbook air m3": "MacBook Air M3",
    "macbook pro m1": "MacBook Pro M1",
    "macbook pro m2": "MacBook Pro M2",
    "macbook pro m3": "MacBook Pro M3",
    "macbook air 13 m1": "MacBook Air M1",
    "macbook air 13 m2": "MacBook Air M2",
    "macbook pro 13 m2": "MacBook Pro M2",
    "macbook pro 14 m2": "MacBook Pro M2",
    "macbook pro 16 m2": "MacBook Pro M2",
    "legion5": "Legion 5",
    "legion 5": "Legion 5",
    "legion 5 pro": "Legion 5 Pro",
    "legion5pro": "Legion 5 Pro",
    "legion 7": "Legion 7",
    "thinkpad x280": "ThinkPad X280",
    "thinkpad t480": "ThinkPad T480",
    "thinkpad t490": "ThinkPad T490",
    "thinkpad x1 carbon": "ThinkPad X1 Carbon",
    "tuf a15": "TUF A15",
    "tuf f15": "TUF F15",
    "tuf gaming a15": "TUF A15",
    "tuf gaming f15": "TUF F15",
    "rog strix": "ROG Strix",
    "rog zephyrus": "ROG Zephyrus",
    "rog strix g15": "ROG Strix G15",
    "vivobook": "VivoBook",
    "zenbook": "ZenBook",
    "victus": "Victus",
    "omen": "Omen",
    "elitebook": "EliteBook",
    "probook": "ProBook",
    "pavilion": "Pavilion",
    "zbook": "ZBook",
    "latitude": "Latitude",
    "precision": "Precision",
    "xps": "XPS",
    "xps 13": "XPS 13",
    "xps 15": "XPS 15",
    "alienware": "Alienware",
    "inspiron": "Inspiron",
    "nitro": "Nitro",
    "nitro 5": "Nitro 5",
    "predator": "Predator",
    "aspire": "Aspire",
    "swift": "Swift",
    "gf63": "GF63",
    "katana": "Katana",
    "raider": "Raider",
    "stealth": "Stealth",
    "cyborg": "Cyborg",
    "loq": "LOQ",
    "ideapad": "IdeaPad",
}

# CPU generation suffixes to preserve but normalize.
_CPU_GENERATION_RE = re.compile(r"\b(?:\d{1,2}(?:st|nd|rd|th)\s*(?:gen|generation)?)\b", re.IGNORECASE)

# Spec tokens to remove from model name (they belong in variant, not model).
_SPEC_TOKEN_RE = re.compile(
    r"(?:\d+\s*(?:GB|TB|Go|RAM|SSD|HDD|NVMe|Hz|inch|cm)|"
    r"i[3579]-?\d{4,5}[A-Z]*|"
    r"[Rr]yzen\s*[3579]\s*\d{4}[A-Z]*|"
    r"[Rr]yzen\s*[3579]|[3579]\s*[Rr]yzen|"
    r"M[1-4]\s*(?:Pro|Max|Ultra)?|"
    r"RTX\s*\d{4}|GTX\s*\d{4}|"
    r"Iris\s*Xe|Intel\s*UHD|Radeon|"
    r"\d{3,4}x\d{3,4}|FHD|QHD|4K|UHD)",
    re.IGNORECASE,
)


def _clean_tokens(text):
    """Lowercase, fold Turkish, remove special chars, collapse whitespace."""
    text = ascii_fold(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _strip_brand_prefix(tokens):
    """Remove leading brand tokens."""
    if tokens and tokens[0] in _BRAND_PREFIXES:
        tokens = tokens[1:]
    return tokens


def normalize_laptop_model_name(brand_name, model_name):
    """Produce a readable canonical model name from noisy marketplace text.

    Examples:
        "MACBOOK AİR M1"           => "MacBook Air M1"
        "Macbook Air 13 M1"        => "MacBook Air M1"
        "Apple MacBook Air M1"     => "MacBook Air M1"
        "Macbook Pro M2"           => "MacBook Pro M2"
        "MACBOOK PRO 13 M2"        => "MacBook Pro M2"
        "LENOVO LEGION 5"          => "Legion 5"
        "Legion5"                  => "Legion 5"
        "Lenovo Legion 5 Ryzen 7"  => "Legion 5"
        "THINKPAD X280"            => "ThinkPad X280"
        "Lenovo ThinkPad X280"     => "ThinkPad X280"
        "ASUS TUF A15"             => "TUF A15"
        "TUF GAMING A15"           => "TUF A15"
        "ROG STRIX G15"            => "ROG Strix G15"
        "HP VICTUS"                => "Victus"
        "DELL XPS 13"              => "XPS 13"
    """
    if not model_name:
        return ""

    text = str(model_name).strip()
    if not text:
        return ""

    # Normalize for lookup
    lookup = _clean_tokens(text)

    # Try direct alias match (with numbers included)
    if lookup in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[lookup]

    # Try alias match after stripping common spec words
    lookup_stripped = re.sub(
        r"\b(?:ryzen\s*[3579]|[3579]\s*ryzen|i[3579](?:\s*[-–]\s*\d{4,5}[A-Z]*)?|"
        r"\d+\s*(?:gb|tb|go|ram|ssd|hdd|nvme|hz|inch|cm)|"
        r"rtx\s*\d{4}|gtx\s*\d{4}|iris\s*xe|uhd|radeon)\b",
        "",
        lookup,
        flags=re.IGNORECASE,
    )
    lookup_stripped = " ".join(lookup_stripped.split())
    if lookup_stripped in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[lookup_stripped]

    # Tokenize and clean
    tokens = lookup.split()

    # Strip brand prefix
    tokens = _strip_brand_prefix(tokens)

    if not tokens:
        return text.strip()

    # Remove spec tokens that don't belong in model name
    # But keep: model numbers (5 in Legion 5), screen sizes (13 in XPS 13), Apple silicon
    clean = []
    prev_was_ryzen = False
    for t in tokens:
        # Remove pure spec tokens (CPU names, GPU names, storage/RAM specs)
        if _SPEC_TOKEN_RE.fullmatch(t):
            continue
        # Remove "gaming" keyword (TUF GAMING A15 → TUF A15)
        if t == "gaming":
            continue
        # Remove "ryzen" and following number (Ryzen 7 → removed)
        if t in ("ryzen", "intel", "amd", "nvidia"):
            prev_was_ryzen = True
            continue
        if prev_was_ryzen and re.fullmatch(r"[3579]", t):
            prev_was_ryzen = False
            continue
        prev_was_ryzen = False
        clean.append(t)

    if not clean:
        clean = [t for t in tokens if t not in _BRAND_PREFIXES]

    if not clean:
        return text.strip()

    # Format output with proper casing
    result = _format_model_tokens(clean)
    return result


def _format_model_tokens(tokens):
    """Apply proper casing to model tokens."""
    # Uppercase acronyms that should stay uppercase
    _UPPERCASE_TOKENS = frozenset({
        "tuf", "rog", "xps", "loq", "gf63",
    })
    # Title-case tokens (family names) — some need special casing
    _TITLECASE_TOKENS = frozenset({
        "macbook", "ideapad", "vivobook", "zenbook", "legion",
        "ocean", "predator", "aspire", "swift",
        "latitude", "precision", "inspiron", "alienware", "victus",
        "omen", "elitebook", "probook", "pavilion", "zbook",
        "katana", "raider", "stealth", "cyborg", "nitro",
        "air", "pro", "max", "ultra",
    })
    # Lowercase tokens (Apple silicon)
    _LOWERCASE_TOKENS = frozenset({"m1", "m2", "m3", "m4"})

    out = []
    for t in tokens:
        if t in _UPPERCASE_TOKENS:
            out.append(t.upper())
        elif t == "thinkpad":
            out.append("ThinkPad")
        elif t in _TITLECASE_TOKENS:
            out.append(t.title())
        elif t in _LOWERCASE_TOKENS:
            out.append(t.lower())
        elif re.fullmatch(r"[a-z]\d+", t):
            out.append(t.upper())
        elif re.fullmatch(r"\d+[a-z]*", t):
            out.append(t.upper())
        elif t.isupper() and len(t) > 2:
            out.append(t.title())
        else:
            out.append(t)
    return " ".join(out)


def laptop_model_merge_key(brand_name, model_name):
    """Return a stable key for grouping equivalent LaptopModel rows.

    The key ignores casing, brand prefixes, Turkish-I, and spec fragments.
    Different models that happen to share the same family (e.g. Legion 5 vs
    Legion 5 Pro) should produce different keys.
    """
    brand = ascii_fold(brand_name).lower().strip()
    text = ascii_fold(model_name).lower().strip()

    # Remove brand prefix
    tokens = text.split()
    tokens = [t for t in tokens if t not in _BRAND_PREFIXES]

    # Remove spec tokens
    clean = []
    for t in tokens:
        if _SPEC_TOKEN_RE.fullmatch(t):
            continue
        if re.fullmatch(r"\d+", t):
            continue
        clean.append(t)

    return brand, " ".join(clean)


def normalize_cpu_family(cpu_text):
    """Normalize CPU text to a family key for grouping.

    Examples:
        "Intel Core i7-12700H"   => "intel_core_i7"
        "AMD Ryzen 7 5800H"     => "amd_ryzen_7"
        "Apple M2 Pro"          => "apple_m2"
        "i5-1135G7"             => "intel_core_i5"
    """
    if not cpu_text:
        return ""

    text = cpu_text.strip().lower()

    # Apple Silicon
    m = re.match(r"(?:apple\s+)?m([1-4])", text)
    if m:
        return f"apple_m{m.group(1)}"

    # Intel i-series
    m = re.match(r"(?:intel\s+core\s+)?i([3579])", text)
    if m:
        return f"intel_core_i{m.group(1)}"

    # Intel Core Ultra
    if "core ultra" in text:
        return "intel_core_ultra"

    # AMD Ryzen
    m = re.match(r"(?:amd\s+)?ryzen\s+([3579])", text)
    if m:
        return f"amd_ryzen_{m.group(1)}"

    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def normalize_gpu_family(gpu_text):
    """Normalize GPU text to a family key for grouping.

    Examples:
        "NVIDIA RTX 3060"   => "nvidia_rtx_3060"
        "NVIDIA GTX 1650"   => "nvidia_gtx_1650"
        "Intel Iris Xe"     => "intel_iris_xe"
    """
    if not gpu_text:
        return ""

    text = gpu_text.strip().lower()

    m = re.match(r"(?:nvidia\s+)?rtx\s+(\d{4})", text)
    if m:
        return f"nvidia_rtx_{m.group(1)}"

    m = re.match(r"(?:nvidia\s+)?gtx\s+(\d{4})", text)
    if m:
        return f"nvidia_gtx_{m.group(1)}"

    m = re.match(r"(?:nvidia\s+)?mx(\d{3,4})", text)
    if m:
        return f"nvidia_mx{m.group(1)}"

    if "iris xe" in text:
        return "intel_iris_xe"
    if "uhd" in text:
        return "intel_uhd"
    if "arc" in text:
        return "intel_arc"

    if "radeon" in text:
        return "amd_radeon"

    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def build_laptop_signature(brand_name, model_name, cpu_text, gpu_text, ram_gb, storage_gb):
    """Build a spec signature for opportunity matching.

    This signature ensures we only compare truly equivalent laptops:
    same brand, model, CPU family, GPU family, RAM, and storage.
    """
    brand = ascii_fold(brand_name).lower().strip() if brand_name else ""
    model_key = laptop_model_merge_key(brand_name, model_name)[1]
    cpu_key = normalize_cpu_family(cpu_text)
    gpu_key = normalize_gpu_family(gpu_text)

    return (
        brand,
        model_key,
        cpu_key,
        gpu_key,
        ram_gb or 0,
        storage_gb or 0,
    )
