import json
import re
import unicodedata

from market.models import Condition, MarketListing
from market.services.normalization import likely_brand, normalize_text


RAM_GB_VALUES = {2, 3, 4, 6, 8, 12, 16, 18, 24, 32}
STORAGE_GB_VALUES = {64, 128, 256, 512, 1024, 2048}

ACCESSORY_RE = re.compile(
    r"\b(case|k[ıi]l[ıi]f|kapak|cover|charger|şarj|sarj|airpods?|buds?|watch|saat)\b",
    re.IGNORECASE,
)

DIRTY_MODEL_RE = re.compile(
    r"\b(store|ileti[şs]im|gsm|s[ıi]f[ıi]r|kapal[ıi]|kutu|yd[ıi]s[ıi]|yurt\s*d[ıi][şs][ıi]|"
    r"pil|hatas[ıi]z|temiz|taksit|t[üu]m\s+renkler|\d+\s*ay|2\.?\s*el|kart|garanti|f[ıi]rsat)\b",
    re.IGNORECASE,
)


def ascii_fold(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = value.translate(
        str.maketrans(
            {
                "İ": "I",
                "ı": "i",
                "Ş": "S",
                "ş": "s",
                "Ğ": "G",
                "ğ": "g",
                "Ü": "U",
                "ü": "u",
                "Ö": "O",
                "ö": "o",
                "Ç": "C",
                "ç": "c",
            }
        )
    )
    return re.sub(r"\s+", " ", value).strip()


def description_metadata(description):
    if not description or "{" not in description:
        return {}
    candidate = description[description.find("{") :].strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {}


def parse_storage_ram(value):
    text = ascii_fold(value)
    storage_gb = None
    ram_gb = None

    pair = re.search(
        r"\b(?P<a>2|3|4|6|8|12|16|18|24|32|64|128|256|512|1024|2048)\s*/\s*"
        r"(?P<b>2|3|4|6|8|12|16|18|24|32|64|128|256|512|1024|2048)\b",
        text,
        re.IGNORECASE,
    )
    if pair:
        first = int(pair.group("a"))
        second = int(pair.group("b"))
        if first in RAM_GB_VALUES and second in STORAGE_GB_VALUES:
            ram_gb = first
            storage_gb = second
        elif second in RAM_GB_VALUES and first in STORAGE_GB_VALUES:
            storage_gb = first
            ram_gb = second

    explicit = re.search(
        r"\b(?P<storage>64|128|256|512|1024|2048|1\s*tb|2\s*tb)\s*(?:gb|g|go|tb|b)\b",
        text,
        re.IGNORECASE,
    )
    if explicit:
        token = explicit.group("storage").lower().replace(" ", "")
        storage_gb = int(token[0]) * 1024 if token.endswith("tb") else int(token)

    inline_ram = re.search(
        r"\b(?P<ram>2|3|4|6|8|12|16|18|24|32)\s*(?:gb|go)?\s*(?:ram)?\b"
        r"(?=[^\n]{0,16}\b(?:64|128|256|512|1024|2048|1\s*tb|2\s*tb)\b)",
        text,
        re.IGNORECASE,
    )
    if inline_ram:
        ram_gb = int(inline_ram.group("ram"))

    if storage_gb is None:
        loose = re.search(
            r"\b(?P<storage>64|128|256|512|1024|2048)\b"
            r"(?=[^\n]{0,24}(?:\b(?:gb|g|go|hafiza|hafıza|duos|dual|cift)\b|\b[12]\s*sim\b))",
            text,
            re.IGNORECASE,
        )
        if loose:
            storage_gb = int(loose.group("storage"))

    if storage_gb is None and re.search(
        r"\b(iphone|galaxy|samsung|xiaomi|redmi|poco|huawei|oppo|vivo|honor|oneplus|pixel)\b",
        text,
        re.IGNORECASE,
    ):
        loose_model_storage = re.search(
            r"\b(?:iphone|galaxy|samsung|xiaomi|redmi|poco|huawei|oppo|vivo|honor|oneplus|pixel)"
            r"[^\n]{0,80}\b(?P<storage>64|128|256|512|1024|2048)\b",
            text,
            re.IGNORECASE,
        )
        if loose_model_storage:
            storage_gb = int(loose_model_storage.group("storage"))

    return storage_gb, ram_gb


def parse_sim_config(value):
    text = ascii_fold(value).lower()
    if re.search(
        r"\b(2\s*sim|dual[\s-]*sim|dualsim|duos|cift(?:[\s-]*fiziki)?(?:[\s-]*sim)?|fiziki[\s-]*cift[\s-]*sim)\b",
        text,
    ):
        return "2sim"
    return ""


def parse_condition(value):
    text = ascii_fold(value).lower()
    sealed = ["sifir", "kapali kutu", "acilmamis", "no aktiv", "non active", "scelle", "neuf", "new", "sealed"]
    used = ["2.el", "2 el", "ikinci el", "temiz", "pil", "kullanim", "aktif", "hatasiz", "occasion", "used"]
    if any(token in text for token in sealed) and not any(token in text for token in ["pil", "2.el", "2 el", "occasion", "used"]):
        return Condition.SEALED
    if any(token in text for token in used):
        return Condition.USED
    return Condition.UNKNOWN


def is_accessory_title(value):
    text = ascii_fold(value).lower()
    return bool(ACCESSORY_RE.search(text)) and not re.search(r"\b(iphone|galaxy|samsung|xiaomi|redmi|poco|huawei|oppo|vivo)\b", text)


def _strip_noise(text):
    text = ascii_fold(text)
    text = re.sub(r"\b(?:2|3|4|6|8|12|16|18|24|32)\s*(?:gb|go)\s*(?:ram)?\b(?=\s+(?:64|128|256|512|1024|2048|1\s*tb|2\s*tb))", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:64|128|256|512|1024|2048)\s*/\s*(?:2|3|4|6|8|12|16|18|24|32)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:2|3|4|6|8|12|16|18|24|32)\s*/\s*(?:64|128|256|512|1024|2048)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:64|128|256|512|1024|2048|1\s*tb|2\s*tb)\s*(?:gb|g|go|tb)?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:100|[5-9]\d)\s*%(?=\s|$)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:1|2)\s*sim\b|\bdual\s*sim\b|\bdualsim\b|\bduos\b|\bcift\b|\bcift\s*fiziki\s*sim\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:boite|box|new|neuf|scelle|global(?:e)?|gloable|ce|yd|yurt\s*disi|kayitli|server\s*kayitli)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:pil|devir|hatasiz|temiz|taksit|takas|kapali|kutu|sifir|magazadan|param\s+guvende)\b.*$", " ", text, flags=re.IGNORECASE)
    # Turkish/French store listing noise
    text = re.sub(r"\b(?:orj|turkce|turk|yesil|siyah|beyaz|mavi|kirmizi|pembe|altin|gumus|renk|noir|blanc|bleu|rouge|vert|argent|or)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:go|stockage|rom|hafiza|depolama|kamerasi|kamera|islemci|batarya|ekran|cozunurluk|boyut|agirlik|fotografi|fotograf|kiti|smartphone)\b", " ", text, flags=re.IGNORECASE)
    # Strip trailing RAM numbers and RAM/storage combos
    text = re.sub(r"\s+\d+\s*(?:gb|go)\s*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*(?:gb|go|ram)\b", " ", text, flags=re.IGNORECASE)
    # Strip orphaned gb/go/tb after number was removed
    text = re.sub(r"\s+(?:gb|go|tb)\s*$", " ", text, flags=re.IGNORECASE)
    # Strip trailing standalone RAM numbers (4/6/8/12/16/18/24/32) at end
    # but not after brand words - check by removing them first then comparing
    trailing = re.search(r"\s+((?:4|6|8|12|16|18|24|32))\s*$", text)
    if trailing:
        before = text[:trailing.start()]
        brand_words = {"iphone", "galaxy", "samsung", "pixel", "honor", "vivo", "oppo",
                        "oneplus", "xiaomi", "redmi", "poco", "huawei", "magic", "iqoo",
                        "find", "note", "turbo"}
        last_word = before.split()[-1].lower() if before.split() else ""
        if last_word not in brand_words:
            text = before
    text = re.sub(r"[-/,!()+\"']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_model_text(title, description=""):
    title = normalize_text(title)
    metadata = description_metadata(description)
    metadata_model = normalize_text(metadata.get("model", ""))
    raw = metadata_model if metadata_model and likely_brand(metadata_model) else title
    raw = _strip_noise(raw)

    text = ascii_fold(raw)
    patterns = [
        r"\biphone\s*(?:air\s*)?\d{1,2}\s*(?:pro\s*max|pro|plus|air|max)?\b",
        r"\b(?:samsung\s*)?galaxy\s*(?:z\s*)?(?:fold|flip)\s*\d+\b",
        r"\b(?:samsung\s*)?galaxy\s*(?:s|a|m)\d{2}\s*(?:ultra|plus|edge|fe)?\b",
        r"\b(?:samsung\s*)?galaxy\s*note\s*\d{1,2}\s*(?:ultra|plus)?\b",
        r"\b(?:xiaomi\s*|mi\s*)\d{1,2}\s*(?:t\s*)?(?:lite|pro\s*max|pro|ultra|plus|max)?\b",
        r"\bredmi\s+note\s+\d{1,2}\s*(?:pro\s*plus|pro|plus)?(?:\s*5g)?\b",
        r"\bpoco\s+[a-z]\d+\s*(?:pro\s*max|pro|ultra|plus|max)?\b",
        r"\b(?:oppo|vivo|honor|huawei|oneplus|google|motorola|realme|redmagic|nubia|doogee)\s+[a-z0-9]+(?:\s+[a-z0-9]+){0,4}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            model = match.group(0).strip()
            if re.match(r"^(mi|xiaomi)\s+\d", model, re.IGNORECASE):
                model = re.sub(r"^mi\b", "Xiaomi", model, flags=re.IGNORECASE)
            return model
    return text


def is_dirty_model_name(value):
    text = ascii_fold(value)
    return bool(DIRTY_MODEL_RE.search(text)) or len(text) > 55


def listing_review_status(price, product_model, storage_gb):
    if not price or not product_model or not storage_gb:
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    if is_dirty_model_name(product_model.canonical_name):
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    return MarketListing.ReviewStatus.AUTO
