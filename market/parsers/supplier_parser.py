import re
from dataclasses import dataclass
from decimal import Decimal

from market.services.normalization import normalize_text


PRICE_RE = re.compile(r"(?P<price>(?:\d{1,3}[.,]\d{3})+|\d{2,6})\s?(?:\$|usd)", re.IGNORECASE)
CAPACITY_RE = re.compile(r"(?P<a>\d{2,4})\s*/\s*(?P<b>\d{1,3})")
STORAGE_RE = re.compile(r"(?P<storage>64|128|256|512|1024|1\s?tb|2\s?tb)\s?(?:gb|g|go)?", re.IGNORECASE)


@dataclass
class ParsedSupplierLine:
    raw_text: str
    model_text: str = ""
    storage_gb: int | None = None
    ram_gb: int | None = None
    price_usd: Decimal | None = None
    confidence: float = 0


def _to_gb(value):
    token = str(value).lower().replace(" ", "")
    if token.endswith("tb"):
        return int(token[:-2]) * 1024
    return int(token)


def _to_usd(value):
    return Decimal(str(value).replace(".", "").replace(",", ""))


def parse_supplier_line(line):
    raw = normalize_text(line)
    parsed = ParsedSupplierLine(raw_text=raw)
    price_match = PRICE_RE.search(raw)
    if price_match:
        parsed.price_usd = _to_usd(price_match.group("price"))
        raw_without_price = raw[: price_match.start()].strip()
    else:
        raw_without_price = raw

    cap_match = CAPACITY_RE.search(raw_without_price)
    if cap_match:
        first = int(cap_match.group("a"))
        second = int(cap_match.group("b"))
        parsed.storage_gb = first
        parsed.ram_gb = second if second >= 4 else None
        model_end = cap_match.start()
    else:
        storage_match = STORAGE_RE.search(raw_without_price)
        if storage_match:
            parsed.storage_gb = _to_gb(storage_match.group("storage"))
            model_end = storage_match.start()
        else:
            model_end = len(raw_without_price)

    parsed.model_text = raw_without_price[:model_end].strip(" -:/")
    score = 0
    score += 35 if parsed.price_usd else 0
    score += 25 if parsed.model_text else 0
    score += 20 if parsed.storage_gb else 0
    score += 10 if parsed.ram_gb else 0
    parsed.confidence = min(score / 100, 1)
    return parsed
