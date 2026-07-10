from decimal import Decimal, ROUND_HALF_UP

from market.services.currency import eur_to_dzd, eur_to_try, eur_to_usd, money, usd_to_eur


GAIN_SPLIT_TIERS = [
    (Decimal("50"), Decimal("0"), Decimal("0")),
    (Decimal("100"), Decimal("0.20"), Decimal("35")),
    (Decimal("250"), Decimal("0.25"), Decimal("60")),
    (Decimal("500"), Decimal("0.35"), Decimal("100")),
    (None, Decimal("0.50"), Decimal("150")),
]
GOOD_DEAL_GROSS_FLOOR_EUR = Decimal("150")
SUPPLIER_BUYER_DISCOUNT_USD = Decimal("100")


def _decimal_or_none(value):
    if value is None:
        return None
    return Decimal(str(value))


def _quantized_percent(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_gain_split(*, algeria_min_eur, turkiye_avg_eur=None, gross_margin_eur=None, supplier_eur=None):
    algeria_min = _decimal_or_none(algeria_min_eur)
    if algeria_min is None:
        return None

    supplier = _decimal_or_none(supplier_eur)
    if supplier is not None:
        buyer_floor = usd_to_eur(SUPPLIER_BUYER_DISCOUNT_USD)
        gross = supplier - algeria_min
        split_pool = gross - buyer_floor

        if split_pool <= 0:
            my_gain = Decimal("0")
            buyer_gain = gross
            offer_price = algeria_min
            deal_quality = "weak" if buyer_gain > 0 else "ignore"
            notes = (
                f"Supplier-list rule: target buyer discount USD {SUPPLIER_BUYER_DISCOUNT_USD:.0f}; "
                "spread is too thin to split after the target discount."
            )
        else:
            my_gain = split_pool / Decimal("2")
            buyer_gain = buyer_floor + (split_pool / Decimal("2"))
            offer_price = algeria_min + my_gain
            buyer_gain_pct = (buyer_gain / offer_price * Decimal("100")) if offer_price else Decimal("0")
            if buyer_gain_pct >= 30:
                deal_quality = "strong"
            elif buyer_gain_pct >= 15 or split_pool >= GOOD_DEAL_GROSS_FLOOR_EUR:
                deal_quality = "medium"
            else:
                deal_quality = "weak"
            notes = (
                f"Supplier-list rule: buyer gets USD {SUPPLIER_BUYER_DISCOUNT_USD:.0f} below supplier, "
                "then remaining spread is split 50/50."
            )

        buyer_gain_pct = (buyer_gain / offer_price * Decimal("100")) if offer_price else Decimal("0")
        my_gain_pct_of_gross = (my_gain / gross * Decimal("100")) if gross else Decimal("0")
        return {
            "pricing_basis": "supplier",
            "gross_margin_eur": money(gross),
            "my_gain_eur": money(my_gain),
            "buyer_gain_eur": money(buyer_gain),
            "offer_price_to_buyer_eur": money(offer_price),
            "buyer_gain_percent": _quantized_percent(buyer_gain_pct),
            "my_gain_percent_of_gross": _quantized_percent(my_gain_pct_of_gross),
            "my_gain_dzd": money(eur_to_dzd(my_gain)),
            "offer_price_to_buyer_dzd": money(eur_to_dzd(offer_price)),
            "deal_quality": deal_quality,
            "notes": notes,
        }

    gross = _decimal_or_none(gross_margin_eur)
    turkiye_avg = _decimal_or_none(turkiye_avg_eur)
    if gross is None and turkiye_avg is not None:
        gross = turkiye_avg - algeria_min
    if gross is None or turkiye_avg is None:
        return None

    if gross <= 0:
        return {
            "pricing_basis": "turkiye_market",
            "gross_margin_eur": money(gross),
            "my_gain_eur": money(Decimal("0")),
            "buyer_gain_eur": money(gross),
            "offer_price_to_buyer_eur": money(algeria_min),
            "buyer_gain_percent": Decimal("0.00"),
            "my_gain_percent_of_gross": Decimal("0.00"),
            "my_gain_dzd": money(Decimal("0")),
            "offer_price_to_buyer_dzd": money(eur_to_dzd(algeria_min)),
            "deal_quality": "ignore",
            "notes": "No spread available to split.",
        }

    my_gain_pct = Decimal("0")
    buyer_min = Decimal("0")
    for threshold, gain_pct, min_gain in GAIN_SPLIT_TIERS:
        if threshold is None or gross < threshold:
            my_gain_pct = gain_pct
            buyer_min = min_gain
            break

    my_gain = gross * my_gain_pct
    capped = False
    max_my_gain = gross - buyer_min
    if my_gain > max_my_gain:
        my_gain = max(Decimal("0"), max_my_gain)
        capped = True

    buyer_gain = gross - my_gain
    offer_price = algeria_min + my_gain
    my_gain_pct_of_gross = (my_gain / gross * Decimal("100")) if gross else Decimal("0")
    buyer_gain_pct = (buyer_gain / offer_price * Decimal("100")) if offer_price else Decimal("0")

    if gross < Decimal("50"):
        deal_quality = "weak"
    elif buyer_gain_pct >= 30:
        deal_quality = "strong"
    elif buyer_gain_pct >= 15:
        deal_quality = "medium"
    elif gross >= GOOD_DEAL_GROSS_FLOOR_EUR and buyer_gain > 0:
        deal_quality = "medium"
    elif buyer_gain_pct > 0:
        deal_quality = "weak"
    else:
        deal_quality = "ignore"

    notes_parts = []
    if my_gain_pct > 0:
        notes_parts.append(f"My cut: {my_gain_pct * 100:.0f}% of spread")
    if capped and buyer_gain >= buyer_min and buyer_min > 0:
        notes_parts.append(f"Capped to leave buyer at least EUR {buyer_min:.0f}")
    elif buyer_gain < buyer_min and buyer_min > 0:
        notes_parts.append(f"Buyer minimum target EUR {buyer_min:.0f} is not met")
    if gross >= GOOD_DEAL_GROSS_FLOOR_EUR and deal_quality == "medium" and buyer_gain_pct < 15:
        notes_parts.append(f"Absolute spread above EUR {GOOD_DEAL_GROSS_FLOOR_EUR:.0f}; kept as medium")
    if deal_quality == "weak":
        notes_parts.append("Thin margin for buyer; may not close")
    if deal_quality == "strong":
        notes_parts.append("Healthy buyer profit; attractive deal")

    return {
        "pricing_basis": "turkiye_market",
        "gross_margin_eur": money(gross),
        "my_gain_eur": money(my_gain),
        "buyer_gain_eur": money(buyer_gain),
        "offer_price_to_buyer_eur": money(offer_price),
        "buyer_gain_percent": _quantized_percent(buyer_gain_pct),
        "my_gain_percent_of_gross": _quantized_percent(my_gain_pct_of_gross),
        "my_gain_dzd": money(eur_to_dzd(my_gain)),
        "offer_price_to_buyer_dzd": money(eur_to_dzd(offer_price)),
        "deal_quality": deal_quality,
        "notes": "; ".join(notes_parts),
    }


def buyer_proposal_from_gain_split(gain_split):
    if not gain_split:
        return None
    offer = gain_split.get("offer_price_to_buyer_eur")
    if offer is None:
        return None
    return {
        "proposed_buyer_price_eur": money(offer),
        "proposed_buyer_price_usd": money(eur_to_usd(offer)),
        "proposed_buyer_price_dzd": money(eur_to_dzd(offer)),
        "proposed_buyer_price_try": money(eur_to_try(offer)),
    }


def attach_buyer_pricing(row, *, margin_key="gross_margin_eur"):
    gain_split = compute_gain_split(
        algeria_min_eur=row.get("algeria_min_eur"),
        turkiye_avg_eur=row.get("turkiye_avg_eur"),
        gross_margin_eur=row.get(margin_key),
        supplier_eur=row.get("supplier_eur"),
    )
    if not gain_split:
        return row
    row["gain_split"] = gain_split
    row["buyer_proposal"] = buyer_proposal_from_gain_split(gain_split)
    return row


def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value
