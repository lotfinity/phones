from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from market.models import CurrencyRate


DEFAULT_ENDPOINT = "https://api.frankfurter.dev/v2/rates"
DEFAULT_SOURCE = "frankfurter.dev"
PUBLIC_BASE = "EUR"
PUBLIC_QUOTES = ("TRY", "USD")
RATE_QUANT = Decimal("0.000001")


def parse_decimal(value, label):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommandError(f"Invalid decimal value for {label}: {value!r}") from exc


def quantize_rate(value):
    return Decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def fetch_public_rates(endpoint, timeout):
    try:
        response = requests.get(
            endpoint,
            params={"base": PUBLIC_BASE, "quotes": ",".join(PUBLIC_QUOTES)},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CommandError(f"FX request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CommandError("FX provider returned invalid JSON.") from exc

    payload = normalize_provider_payload(payload)
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise CommandError("FX provider response is missing a rates object.")

    missing = [quote for quote in PUBLIC_QUOTES if quote not in rates]
    if missing:
        raise CommandError(f"FX provider response is missing rates for: {', '.join(missing)}")

    return payload


def normalize_provider_payload(payload):
    if isinstance(payload, dict):
        return payload

    if not isinstance(payload, list):
        raise CommandError("FX provider returned an unsupported JSON shape.")

    rates = {}
    provider_date = ""
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("base") != PUBLIC_BASE:
            continue
        quote = item.get("quote")
        if quote in PUBLIC_QUOTES:
            rates[quote] = item.get("rate")
            provider_date = provider_date or item.get("date", "")

    return {
        "base": PUBLIC_BASE,
        "date": provider_date,
        "rates": rates,
    }


def build_rate_rows(payload, *, source, dzd_per_eur_black=None, include_dzd_black=True, observed_at=None):
    observed_at = observed_at or timezone.now()
    provider_date = payload.get("date") or "unknown date"
    rates = payload["rates"]

    eur_try = quantize_rate(parse_decimal(rates["TRY"], "EUR/TRY"))
    eur_usd = quantize_rate(parse_decimal(rates["USD"], "EUR/USD"))
    if eur_usd == 0:
        raise CommandError("FX provider returned EUR/USD=0, cannot derive USD/TRY.")
    usd_try = quantize_rate(eur_try / eur_usd)

    public_note = f"Fetched from {source} for provider date {provider_date}."
    rows = [
        {
            "base_currency": "EUR",
            "quote_currency": "TRY",
            "rate": eur_try,
            "source": source,
            "observed_at": observed_at,
            "notes": public_note,
        },
        {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "rate": eur_usd,
            "source": source,
            "observed_at": observed_at,
            "notes": public_note,
        },
        {
            "base_currency": "USD",
            "quote_currency": "TRY",
            "rate": usd_try,
            "source": f"{source}:derived",
            "observed_at": observed_at,
            "notes": f"Derived from EUR/TRY divided by EUR/USD for provider date {provider_date}.",
        },
    ]

    if include_dzd_black:
        if dzd_per_eur_black is None:
            dzd_per_eur_black = getattr(settings, "DZD_PER_EUR_BLACK", None)
        if dzd_per_eur_black is None:
            raise CommandError(
                "DZD black-market rate is not configured. Set DZD_PER_EUR_BLACK, "
                "pass --dzd-per-eur-black, or use --skip-dzd-black."
            )
        rows.append(
            {
                "base_currency": "EUR",
                "quote_currency": "DZD",
                "rate": quantize_rate(parse_decimal(dzd_per_eur_black, "EUR/DZD black-market")),
                "source": "manual:black_market",
                "observed_at": observed_at,
                "notes": (
                    "Configured Algeria black-market benchmark for PriceBridge buy-side math; "
                    "not an official central-bank DZD rate."
                ),
            }
        )

    return rows


class Command(BaseCommand):
    help = (
        "Fetch latest public FX rates, save them to CurrencyRate, and optionally "
        "refresh opportunity snapshots."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--endpoint",
            default=getattr(settings, "FX_RATE_ENDPOINT", DEFAULT_ENDPOINT),
            help="FX provider endpoint. Defaults to Frankfurter's latest rates endpoint.",
        )
        parser.add_argument(
            "--source",
            default=getattr(settings, "FX_RATE_SOURCE", DEFAULT_SOURCE),
            help="Source label stored on CurrencyRate rows.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=15,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--dzd-per-eur-black",
            default=None,
            help=(
                "Manual Algeria black-market EUR/DZD benchmark to save. "
                "Defaults to settings.DZD_PER_EUR_BLACK."
            ),
        )
        parser.add_argument(
            "--skip-dzd-black",
            action="store_true",
            help="Do not save the manual EUR/DZD black-market benchmark.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print rates without writing CurrencyRate rows.",
        )
        parser.add_argument(
            "--recompute-opportunities",
            action="store_true",
            help="After saving rates, run run_opportunity_analysis so opportunities use the new FX rows.",
        )

    def handle(self, *args, **options):
        payload = fetch_public_rates(options["endpoint"], options["timeout"])
        rows = build_rate_rows(
            payload,
            source=options["source"],
            dzd_per_eur_black=options["dzd_per_eur_black"],
            include_dzd_black=not options["skip_dzd_black"],
        )

        action = "Would save" if options["dry_run"] else "Saving"
        for row in rows:
            self.stdout.write(
                f"{action} {row['base_currency']}/{row['quote_currency']} "
                f"{row['rate']} from {row['source']}"
            )

        if options["dry_run"]:
            if options["recompute_opportunities"]:
                self.stdout.write("Dry run selected; skipping opportunity recompute.")
            return

        with transaction.atomic():
            saved = [CurrencyRate.objects.create(**row) for row in rows]

        self.stdout.write(self.style.SUCCESS(f"Saved {len(saved)} FX rate rows."))

        if options["recompute_opportunities"]:
            self.stdout.write("Recomputing opportunity and deal snapshots...")
            call_command("run_opportunity_analysis")
