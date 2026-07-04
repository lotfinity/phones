from django.core.management.base import BaseCommand

from market.collectors.sahibinden_cdp import enrich_open_detail_from_cdp


class Command(BaseCommand):
    help = "Enrich an existing Sahibinden listing from the currently open CDP detail page."

    def add_arguments(self, parser):
        parser.add_argument("--cdp", default="http://127.0.0.1:9222")

    def handle(self, *args, **options):
        listing, detail = enrich_open_detail_from_cdp(options["cdp"])
        attrs = detail.get("attrs") or {}
        self.stdout.write(
            self.style.SUCCESS(
                "Updated listing "
                f"{listing.pk}: {listing.product_model} / {listing.variant} / "
                f"{listing.price_original} TRY / {listing.condition} / {listing.review_status}"
            )
        )
        if attrs:
            self.stdout.write(f"Detail attrs: {attrs}")
