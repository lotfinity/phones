"""Build targeted marketplace search queries for missing comparison data."""

from decimal import Decimal
from urllib.parse import quote_plus

from django.core.management.base import BaseCommand
from django.db.models import Count, Min

from market.models import ConsoleListing, Country, LaptopListing, PhoneListing


SAHIBINDEN_BASE = "https://www.sahibinden.com/arama?query_text={query}"


def sahibinden_url(query):
    return SAHIBINDEN_BASE.format(query=quote_plus(query))


class Command(BaseCommand):
    help = "Print prioritized search queries for enriching one-sided clean listing data."

    def add_arguments(self, parser):
        parser.add_argument("--category", choices=["phones", "laptops", "consoles", "all"], default="all")
        parser.add_argument("--country-missing", choices=["turkiye"], default="turkiye")
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--min-algeria-count", type=int, default=1)
        parser.add_argument("--format", choices=["table", "urls"], default="table")

    def handle(self, *args, **options):
        rows = []
        category = options["category"]
        if category in ("phones", "all"):
            rows.extend(self._phone_rows(options["min_algeria_count"]))
        if category in ("laptops", "all"):
            rows.extend(self._laptop_rows(options["min_algeria_count"]))
        if category in ("consoles", "all"):
            rows.extend(self._console_rows(options["min_algeria_count"]))
        rows.sort(key=lambda row: (row["algeria_min_eur"] or Decimal("0"), row["algeria_count"]), reverse=True)
        rows = rows[: options["limit"]]

        if options["format"] == "urls":
            for row in rows:
                self.stdout.write(row["url"])
            return

        self.stdout.write("Type | Query | DZ count | DZ min EUR | Sahibinden URL")
        self.stdout.write("-" * 140)
        for row in rows:
            self.stdout.write(
                f"{row['type']} | {row['query']} | {row['algeria_count']} | "
                f"{row['algeria_min_eur'] or '-'} | {row['url']}"
            )

    def _phone_rows(self, min_count):
        dz = (
            PhoneListing.objects.filter(country=Country.ALGERIA, phone_model__isnull=False, price_eur__isnull=False)
            .values("phone_model_id", "phone_model__brand__name", "phone_model__canonical_name", "storage_gb")
            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
            .filter(algeria_count__gte=min_count)
        )
        rows = []
        for item in dz:
            tr_exists = PhoneListing.objects.filter(
                country=Country.TURKIYE,
                phone_model_id=item["phone_model_id"],
                storage_gb=item["storage_gb"],
                price_eur__isnull=False,
            ).exists()
            if tr_exists:
                continue
            query = " ".join(
                part for part in [
                    item["phone_model__brand__name"],
                    item["phone_model__canonical_name"],
                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
                ]
                if part
            )
            rows.append(self._row("phone", query, item))
        return rows

    def _laptop_rows(self, min_count):
        dz = (
            LaptopListing.objects.filter(country=Country.ALGERIA, laptop_model__isnull=False, price_eur__isnull=False)
            .values("laptop_model_id", "laptop_model__brand__name", "laptop_model__canonical_name", "cpu", "gpu", "ram_gb", "storage_gb")
            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
            .filter(algeria_count__gte=min_count)
        )
        rows = []
        for item in dz:
            tr_filter = {
                "country": Country.TURKIYE,
                "laptop_model_id": item["laptop_model_id"],
                "price_eur__isnull": False,
            }
            if item["ram_gb"]:
                tr_filter["ram_gb"] = item["ram_gb"]
            if item["storage_gb"]:
                tr_filter["storage_gb"] = item["storage_gb"]
            if LaptopListing.objects.filter(**tr_filter).exists():
                continue
            query = " ".join(
                part for part in [
                    item["laptop_model__brand__name"],
                    item["laptop_model__canonical_name"],
                    item["cpu"],
                    item["gpu"],
                    f"{item['ram_gb']}GB" if item["ram_gb"] else "",
                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
                ]
                if part
            )
            rows.append(self._row("laptop", query, item))
        return rows

    def _console_rows(self, min_count):
        dz = (
            ConsoleListing.objects.filter(country=Country.ALGERIA, console_model__isnull=False, price_eur__isnull=False)
            .values("console_model_id", "console_model__brand__name", "console_model__canonical_name", "chipset", "ram_gb", "storage_gb")
            .annotate(algeria_count=Count("id"), algeria_min_eur=Min("price_eur"))
            .filter(algeria_count__gte=min_count)
        )
        rows = []
        for item in dz:
            tr_exists = ConsoleListing.objects.filter(
                country=Country.TURKIYE,
                console_model_id=item["console_model_id"],
                storage_gb=item["storage_gb"],
                price_eur__isnull=False,
            ).exists()
            if tr_exists:
                continue
            query = " ".join(
                part for part in [
                    item["console_model__brand__name"],
                    item["console_model__canonical_name"],
                    item["chipset"],
                    f"{item['ram_gb']}GB" if item["ram_gb"] else "",
                    f"{item['storage_gb']}GB" if item["storage_gb"] else "",
                ]
                if part
            )
            rows.append(self._row("console", query, item))
        return rows

    def _row(self, row_type, query, item):
        return {
            "type": row_type,
            "query": query,
            "algeria_count": item["algeria_count"],
            "algeria_min_eur": item["algeria_min_eur"],
            "url": sahibinden_url(query),
        }
