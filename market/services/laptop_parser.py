import re


# ── CPU patterns ──────────────────────────────────────────────────────────
CPU_PATTERNS = [
    # Intel Core Ultra (Arrow Lake) — "Ultra 9 275HX", "Intel Ultra 9 275HX"
    r"(?:Intel\s+)?Core\s+Ultra\s+(\d)\s+(\d{3}[A-Z]*)",
    r"(?:Intel\s+)?Ultra\s+(\d)\s+(\d{3}[A-Z]*)",
    # Intel Core i-series 12th-14th gen — "i9-14900HX", "i7-13700H"
    r"(?:Intel\s+)?Core\s+i(\d)-(\d{4,5}[A-Z]*)",
    r"\bi(\d)-(\d{4,5}[A-Z]*)\b",
    # Intel Core i-series older — "i7 12700", "i5 10400", "i9 14900H"
    r"(?:Intel\s+)?Core\s+i(\d)\s+(\d{4,5}[A-Z]*)",
    # Intel with gen label — "i9 14th Gen 14900H"
    r"(?:Intel\s+)?Core\s+i(\d)\s+\d{1,2}(?:st|nd|rd|th)\s+Gen\s+(\d{4,5}[A-Z]*)",
    # Intel Pentium / Celeron
    r"(?:Intel\s+)?(Pentium|Celeron)\s+(\w+)",
    # AMD Ryzen (must come before Apple to avoid false positives)
    r"(?:AMD\s+)?Ryzen\s+(\d)\s+(\d{4}[A-Z]*)",
    # Apple Silicon
    r"(?:Apple\s+)?M(\d)\s*(Pro|Max|Ultra)?",
]

# ── GPU patterns ──────────────────────────────────────────────────────────
GPU_PATTERNS = [
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?RTX\s+(\d{4})\s*(Ti|Laptop)?",
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?GTX\s+(\d{4})\s*(Ti)?",
    r"(?:AMD\s+)?Radeon\s+(RX\s+\d{4}[SM]?\w*|Pro\s+\w+)",
    r"(?:Intel\s+)?Arc\s+(A\d{3})\s*(M\d)?",
    r"(?:Intel\s+)?(Iris\s+Xe|UHD\s+Graphics)",
]

# ── RAM patterns ──────────────────────────────────────────────────────────
RAM_PATTERNS = [
    r"(\d{1,2})\s*(?:Go|GB)\s*(?:de\s+)?(?:RAM|ram)?",
    r"(?:RAM|ram|mémoire)\s*[:\s]*(\d{1,2})\s*(?:Go|GB)?",
]

# ── Storage patterns ──────────────────────────────────────────────────────
STORAGE_PATTERNS = [
    # Prefer TB/TO first (avoid matching "32GO" when "1TO" exists)
    r"(\d+)\s*(?:To|TB)\s*(?:SSD|HDD|NVMe|PCIe)?",
    r"(?:SSD|HDD|NVMe|PCIe)\s*[:\s]*(\d+)\s*(?:To|TB)?",
    # GB/GO — only match if followed by SSD/HDD/NVMe to avoid RAM
    r"(\d+)\s*(?:Go|GB)\s+(?:SSD|HDD|NVMe|PCIe)",
    r"(?:SSD|HDD|NVMe|PCIe)\s*[:\s]*(\d+)\s*(?:Go|GB)?",
]

# ── Screen size patterns ─────────────────────────────────────────────────
SCREEN_PATTERNS = [
    r'(\d{2}(?:\.\d)?)\s*[""″\'\']',
    r"Écran\s+(\d{2}(?:\.\d)?)",
    r"Screen\s+(\d{2}(?:\.\d)?)",
]

# ── Resolution patterns ──────────────────────────────────────────────────
RESOLUTION_PATTERNS = [
    r"(\d{3,4})\s*[xX×]\s*(\d{3,4})",
    r"(QHD\+?|FHD\+?|UHD|4K|2K|WXGA|WUXGA|3K|WQXGA)",
    r"(OLED|IPS|VA|TN|Mini[\s-]?LED|AMOLED)",
]


def parse_cpu(text):
    for pattern in CPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                brand_line = groups[0] or ""
                sku = groups[1] or ""
                if brand_line.lower() in ("pentium", "celeron"):
                    return f"Intel {brand_line} {sku}".strip()
                elif sku.lower() in ("pro", "max", "ultra", ""):
                    return f"Apple M{brand_line} {sku}".strip()
                elif brand_line.isdigit() and int(brand_line) >= 1:
                    if "ultra" in pattern.lower():
                        return f"Intel Ultra {brand_line}-{sku}".strip()
                    elif "ryzen" in pattern.lower():
                        return f"AMD Ryzen {brand_line} {sku}".strip()
                    else:
                        return f"Intel Core i{brand_line}-{sku}".strip()
                else:
                    return f"AMD Ryzen {brand_line} {sku}".strip()
            elif len(groups) == 1:
                return groups[0] or ""
    return ""


def parse_gpu(text):
    for pattern in GPU_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                model = groups[0] or ""
                suffix = groups[1] or ""
                if model.isdigit():
                    if "gtx" in pattern.lower():
                        return f"NVIDIA GTX {model} {suffix}".strip()
                    return f"NVIDIA RTX {model} {suffix}".strip()
                else:
                    return f"{model} {suffix}".strip()
            elif len(groups) == 1:
                val = groups[0] or ""
                if val.isdigit():
                    return f"NVIDIA RTX {val}".strip()
                if "radeon" in pattern.lower() and "radeon" not in val.lower():
                    return f"AMD Radeon {val}".strip()
                if "arc" in pattern.lower() and "arc" not in val.lower():
                    return f"Intel Arc {val}".strip()
                return val
    return ""


def parse_ram_gb(text):
    for pattern in RAM_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 2 <= val <= 128:
                return val
    # Fallback: standalone Xgo/XGB
    m = re.search(r"\b(\d{1,2})\s*(?:go|gb)\b", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if val in (4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128):
            return val
    return None


def parse_storage_gb(text):
    for pattern in STORAGE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            full = m.group(0).lower()
            if "tb" in full or "to" in full:
                return val * 1024
            elif "mb" in full or "mo" in full:
                continue
            elif val >= 32:
                return val
    return None


def parse_screen_size(text):
    for pattern in SCREEN_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            size = float(m.group(1))
            if 10 <= size <= 20:
                return size
    return None


def parse_resolution(text):
    for pattern in RESOLUTION_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


def parse_laptop_title(title):
    return {
        "cpu": parse_cpu(title),
        "gpu": parse_gpu(title),
        "ram_gb": parse_ram_gb(title),
        "storage_gb": parse_storage_gb(title),
        "screen_size": parse_screen_size(title),
        "resolution": parse_resolution(title),
    }


def laptop_review_status(price, product_model, ram_gb):
    from market.models import MarketListing
    if not price or not product_model or not ram_gb:
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    return MarketListing.ReviewStatus.AUTO
