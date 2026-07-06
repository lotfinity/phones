from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def money(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def latest_rate(base_currency, quote_currency):
    from market.models import CurrencyRate

    max_age_days = getattr(settings, "FX_RATE_MAX_AGE_DAYS", 3)
    min_observed_at = timezone.now() - timedelta(days=max_age_days)
    rate = (
        CurrencyRate.objects.filter(
            base_currency=base_currency,
            quote_currency=quote_currency,
            observed_at__gte=min_observed_at,
        )
        .order_by("-observed_at")
        .first()
    )
    return Decimal(str(rate.rate)) if rate else None


def latest_eur_rate(quote_currency):
    return latest_rate("EUR", quote_currency)


def eur_rate_or_setting(quote_currency, setting_name):
    return latest_eur_rate(quote_currency) or Decimal(str(getattr(settings, setting_name)))


def usd_try_rate():
    return latest_rate("USD", "TRY") or Decimal(str(getattr(settings, "USD_TRY")))


def eur_try_rate():
    return eur_rate_or_setting("TRY", "EUR_TRY")


def eur_usd_rate():
    return eur_try_rate() / usd_try_rate()


def dzd_to_eur(amount_dzd):
    return money(Decimal(str(amount_dzd)) / eur_rate_or_setting("DZD", "DZD_PER_EUR_BLACK"))


def usd_to_eur(amount_usd):
    # Supplier lists are quoted in USD. Convert through TRY using fetched USD/TRY and EUR/TRY.
    return money((Decimal(str(amount_usd)) * usd_try_rate()) / eur_try_rate())


def try_to_eur(amount_try):
    return money(Decimal(str(amount_try)) / eur_rate_or_setting("TRY", "EUR_TRY"))


def eur_to_dzd(amount_eur):
    if amount_eur is None:
        return None
    return money(Decimal(str(amount_eur)) * eur_rate_or_setting("DZD", "DZD_PER_EUR_BLACK"))


def eur_to_usd(amount_eur):
    if amount_eur is None:
        return None
    return money(Decimal(str(amount_eur)) * eur_usd_rate())


def eur_to_try(amount_eur):
    if amount_eur is None:
        return None
    return money(Decimal(str(amount_eur)) * eur_try_rate())


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
