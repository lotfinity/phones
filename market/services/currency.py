from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


def money(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dzd_to_eur(amount_dzd):
    return money(Decimal(str(amount_dzd)) / Decimal(str(settings.DZD_PER_EUR_BLACK)))


def usd_to_eur(amount_usd):
    return money(Decimal(str(amount_usd)) / Decimal(str(settings.EUR_USD)))


def try_to_eur(amount_try):
    return money(Decimal(str(amount_try)) / Decimal(str(settings.EUR_TRY)))


def convert_to_eur(amount, currency):
    if amount is None:
        return None
    currency = (currency or "").upper()
    if currency == "DZD":
        return dzd_to_eur(amount)
    if currency == "USD":
        return usd_to_eur(amount)
    if currency == "TRY":
        return try_to_eur(amount)
    if currency == "EUR":
        return money(amount)
    return None
