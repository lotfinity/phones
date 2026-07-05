import json
import re
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from market.models import CurrencyRate, MarketListing
from market.services.currency import convert_to_eur


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 PriceBridge/0.1",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}


def fetch_url(url, timeout=20):
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def decimal_value(value):
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"Invalid rate value: {value}") from exc


def validate_rate(rate, low, high, label):
    if rate < Decimal(str(low)) or rate > Decimal(str(high)):
        raise ValueError(f"{label} rate {rate} is outside expected range {low}-{high}.")
    return rate


def fetch_frankfurter_rates():
    url = "https://api.frankfurter.app/latest?from=EUR&to=TRY,USD"
    payload = json.loads(fetch_url(url))
    rates = payload.get("rates") or {}
    return {
        "TRY": validate_rate(decimal_value(rates["TRY"]), 1, 200, "EUR/TRY"),
        "USD": validate_rate(decimal_value(rates["USD"]), Decimal("0.5"), 2, "EUR/USD"),
    }, {
        "source": "frankfurter.app",
        "url": url,
        "date": payload.get("date", ""),
    }


def fetch_exchangedz_eur_dzd():
    url = "https://www.exchangedz.com/rates/eur-to-dzd"
    html = fetch_url(url)
    compact_html = re.sub(r"\s+", " ", html)

    buy_match = re.search(
        r'"value"\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*,\s*"description"\s*:\s*"1 EUR buy rate[^"]*Square market',
        compact_html,
        re.IGNORECASE,
    )
    sell_match = re.search(
        r'"value"\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*,\s*"description"\s*:\s*"1 EUR sell rate[^"]*Square market',
        compact_html,
        re.IGNORECASE,
    )
    if not buy_match:
        raise ValueError("Could not find ExchangeDZ Square EUR/DZD buy rate.")

    buy_rate = validate_rate(decimal_value(buy_match.group(1)), 150, 500, "EUR/DZD black-market buy")
    sell_rate = decimal_value(sell_match.group(1)) if sell_match else None
    notes = f"url={url}; basis=Square Port Said buy rate"
    if sell_rate:
        notes += f"; sell_rate={sell_rate}"
    return buy_rate, {"source": "exchangedz square buy", "url": url, "notes": notes}


def save_rate(base, quote, rate, source, notes="", dry_run=False):
    if dry_run:
        return None
    return CurrencyRate.objects.create(
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        source=source,
        notes=notes,
    )


class Command(BaseCommand):
    help = "Fetch EUR exchange rates and store them for marketplace price conversion."

    def add_arguments(self, parser):
        parser.add_argument("--skip-official", action="store_true", help="Skip EUR/TRY and EUR/USD fetch.")
        parser.add_argument("--skip-dzd", action="store_true", help="Skip Algeria black-market EUR/DZD scrape.")
        parser.add_argument("--dry-run", action="store_true", help="Fetch and print rates without writing rows.")
        parser.add_argument(
            "--recalculate-listings",
            action="store_true",
            help="Recalculate stored MarketListing.price_eur values after saving rates.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        saved = []

        with transaction.atomic():
            if not options["skip_official"]:
                try:
                    rates, meta = fetch_frankfurter_rates()
                except Exception as exc:
                    raise CommandError(f"Frankfurter fetch failed: {exc}") from exc
                for quote, rate in rates.items():
                    save_rate(
                        "EUR",
                        quote,
                        rate,
                        meta["source"],
                        notes=f"url={meta['url']}; date={meta['date']}",
                        dry_run=dry_run,
                    )
                    saved.append(("EUR", quote, rate, meta["source"]))

            if not options["skip_dzd"]:
                try:
                    rate, meta = fetch_exchangedz_eur_dzd()
                except Exception as exc:
                    fallback = Decimal(str(settings.DZD_PER_EUR_BLACK))
                    self.stdout.write(
                        self.style.WARNING(
                            f"ExchangeDZ scrape failed: {exc}. Using fallback EUR/DZD={fallback}."
                        )
                    )
                    rate = fallback
                    meta = {
                        "source": "settings fallback",
                        "notes": "Fallback from DZD_PER_EUR_BLACK after scrape failure.",
                    }
                save_rate("EUR", "DZD", rate, meta["source"], notes=meta.get("notes", ""), dry_run=dry_run)
                saved.append(("EUR", "DZD", rate, meta["source"]))

            recalculated = 0
            if options["recalculate_listings"] and not dry_run:
                for listing in MarketListing.objects.exclude(price_original__isnull=True).iterator():
                    new_price_eur = convert_to_eur(listing.price_original, listing.currency_original)
                    if listing.price_eur != new_price_eur:
                        listing.price_eur = new_price_eur
                        listing.save(update_fields=["price_eur"])
                        recalculated += 1

        for base, quote, rate, source in saved:
            prefix = "Would save" if dry_run else "Saved"
            self.stdout.write(f"{prefix} {base}/{quote} {rate} from {source}")
        if options["recalculate_listings"] and not dry_run:
            self.stdout.write(f"Recalculated {recalculated} listing EUR prices.")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run only; no CurrencyRate rows were created."))
