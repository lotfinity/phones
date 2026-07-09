"""Backfill existing MarketListing rows into RawListing for the new pipeline."""

from django.core.management.base import BaseCommand

from market.models import Country, MarketListing, RawListing, SourceType


class Command(BaseCommand):
    help = "Migrate existing MarketListing rows into RawListing without deleting old data."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--source-type", help="Filter by source type.")
        parser.add_argument(
            "--category", choices=["phones", "laptops"],
            help="Force category hint.",
        )

    def handle(self, *args, **options):
        qs = MarketListing.objects.select_related("source").order_by("-observed_at")

        if options["source_type"]:
            qs = qs.filter(source_type=options["source_type"])
        if options["category"]:
            pass

        qs = qs[: options["limit"]]

        created = 0
        skipped = 0
        for listing in qs.iterator():
            existing = RawListing.objects.filter(
                source_type=listing.source_type,
                listing_url=listing.listing_url,
            ).first()
            if existing:
                skipped += 1
                continue

            raw_text = " ".join(
                filter(None, [listing.title_raw, listing.description_raw])
            )

            category_hint = RawListing.CategoryHint.PHONES
            if options["category"]:
                category_hint = options["category"]
            elif listing.source_type == SourceType.SAHIBINDEN:
                title_lower = (listing.title_raw or "").lower()
                if any(kw in title_lower for kw in ("laptop", "notebook", "macbook")):
                    category_hint = RawListing.CategoryHint.LAPTOPS

            payload = {
                "legacy_market_listing_id": listing.pk,
                "legacy_price_original": str(listing.price_original) if listing.price_original else None,
                "legacy_currency": listing.currency_original,
            }

            if not options["dry_run"]:
                RawListing.objects.create(
                    source=listing.source,
                    source_type=listing.source_type,
                    country=listing.country,
                    category_hint=category_hint,
                    title_raw=listing.title_raw or "",
                    description_raw=listing.description_raw or "",
                    raw_text=raw_text,
                    price_text_raw=f"{listing.price_original} {listing.currency_original}" if listing.price_original else "",
                    listing_url=listing.listing_url or "",
                    image_url=listing.image_path or "",
                    raw_payload=payload,
                    observed_at=listing.observed_at,
                )
            created += 1

        action = "Would create" if options["dry_run"] else "Created"
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY RUN] ' if options['dry_run'] else ''}"
            f"{action} {created} RawListing rows, skipped {skipped} duplicates."
        ))
