import re
from dataclasses import dataclass
from decimal import Decimal

from market.models import Condition
from market.parsers.supplier_parser import CAPACITY_RE, STORAGE_RE
from market.services.normalization import normalize_text


EXPLICIT_PRICE_DZD_RE = re.compile(
    r"(?<!\d)(?:prix|price|سعر)?\s*[:\-]?\s*(?P<price>\d{5,7})\s?(?:da|dzd)\b",
    re.IGNORECASE,
)
GENERIC_PRICE_DZD_RE = re.compile(
    r"(?<!\d)(?:prix|price|سعر)?\s*[:\-]?\s*(?P<price>\d{5,7})(?!\d)(?:\s?(?:da|dzd))?",
    re.IGNORECASE,
)
BATTERY_RE = re.compile(r"(?P<battery>100|[5-9]\d)\s?%")
CYCLES_RE = re.compile(r"(?:cycle|cycles)\s*[:\-]?\s*(?P<cycles>\d{1,4})", re.IGNORECASE)
SIM_RE = re.compile(r"(?P<sim>[12])\s?(?:sim|سيم)", re.IGNORECASE)
PRODUCT_LINE_RE = re.compile(r"\b(i\s?phone|iphone|samsung|xiaomi|redmi|poco)\b.*", re.IGNORECASE)


@dataclass
class ParsedOCRText:
    raw_text: str
    model_text: str = ""
    storage_text: str = ""
    storage_gb: int | None = None
    price_dzd: Decimal | None = None
    battery_text: str = ""
    battery_health: int | None = None
    battery_cycles: int | None = None
    condition_text: str = ""
    condition: str = Condition.UNKNOWN
    sim_text: str = ""
    confidence: float = 0


def parse_ocr_text(text):
    raw_lines = [normalize_text(line) for line in (text or "").splitlines()]
    raw_lines = [line for line in raw_lines if line]
    raw = normalize_text(text)
    parsed = ParsedOCRText(raw_text=raw)

    explicit_price_matches = list(EXPLICIT_PRICE_DZD_RE.finditer(raw))
    generic_price_matches = list(GENERIC_PRICE_DZD_RE.finditer(raw))
    price_match = None
    for candidate in explicit_price_matches or generic_price_matches:
        value = candidate.group("price")
        if value.startswith("0"):
            continue
        amount = int(value)
        if candidate not in explicit_price_matches and amount > 400000 and 50000 <= int(value[1:]) <= 300000:
            value = value[1:]
            amount = int(value)
        if 40000 <= amount <= 400000:
            price_match = candidate
            parsed.price_dzd = Decimal(value)
            break

    product_line_match = None
    for line in raw_lines or [raw]:
        product_line_match = PRODUCT_LINE_RE.search(line)
        if product_line_match:
            break
    product_text = product_line_match.group(0) if product_line_match else ""

    capacity_match = CAPACITY_RE.search(product_text) or CAPACITY_RE.search(raw)
    if capacity_match:
        first = int(capacity_match.group("a"))
        second = int(capacity_match.group("b"))
        if first <= 32 and second >= 64:
            parsed.storage_gb = second
            parsed.storage_text = capacity_match.group(0)
        else:
            parsed.storage_gb = first
            parsed.storage_text = capacity_match.group(0)

    storage_match = STORAGE_RE.search(product_text) or STORAGE_RE.search(raw)
    if storage_match:
        parsed.storage_text = storage_match.group(0)
        token = storage_match.group("storage").lower().replace(" ", "")
        parsed.storage_gb = int(token[:-2]) * 1024 if token.endswith("tb") else int(token)

    battery_match = BATTERY_RE.search(raw)
    if battery_match:
        parsed.battery_text = battery_match.group(0)
        parsed.battery_health = int(battery_match.group("battery"))

    cycles_match = CYCLES_RE.search(raw)
    if cycles_match:
        parsed.battery_cycles = int(cycles_match.group("cycles"))

    sim_match = SIM_RE.search(raw)
    if sim_match:
        parsed.sim_text = sim_match.group(0)

    lowered = raw.lower()
    if any(token in lowered for token in ["neuf", "new", "sealed", "جديد"]):
        parsed.condition = Condition.SEALED
        parsed.condition_text = "new/sealed"
    elif any(token in lowered for token in ["مستعمل", "used", "occasion"]):
        parsed.condition = Condition.USED
        parsed.condition_text = "used"

    if product_text:
        model_cut = len(product_text)
        for match in [capacity_match, storage_match, battery_match, cycles_match, sim_match]:
            if match:
                model_cut = min(model_cut, match.start())
        parsed.model_text = product_text[:model_cut].strip(" -:/|=")

    score = 0
    score += 30 if parsed.price_dzd else 0
    score += 25 if parsed.model_text else 0
    score += 20 if parsed.storage_gb else 0
    score += 10 if parsed.condition != Condition.UNKNOWN else 0
    score += 10 if parsed.battery_health or parsed.battery_cycles is not None else 0
    parsed.confidence = min(score / 100, 1)
    return parsed
