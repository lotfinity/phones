from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from market.models import MarketListing, MarketListingSpecValue
from market.services.catalog import get_or_create_product_type, upsert_listing_specs_from_dict
from market.services.spec_extraction import detect_product_type, extract_specs_from_text


class Command(BaseCommand):
    help = "Backfill MarketListingSpecValue rows from listing text."

    def add_arguments(self, parser):
        parser.add_argument("--product-type", type=str, default="")
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--replace", action="store_true")
        parser.add_argument("--only-missing", action="store_true")
        parser.add_argument("--set-product-type", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be >= 1")
        limit = min(limit, 10000)

        product_type_slug = options["product_type"].strip().lower()
        dry_run = options["dry_run"]
        replace = options["replace"]
        only_missing = options["only_missing"]
        set_product_type = options["set_product_type"]

        qs = MarketListing.objects.select_related(
            "product_model", "product_model__product_type"
        ).order_by("-id")
        if only_missing:
            qs = qs.filter(spec_values__isnull=True)
        if product_type_slug:
            qs = qs.filter(
                Q(product_model__product_type__slug=product_type_slug) |
                Q(product_model__product_type__isnull=True)
            )

        candidates = list(qs.distinct()[:limit])
        processed = 0
        written = 0
        skipped = 0
        typed = 0

        for listing in candidates:
            text = f"{listing.title_raw or ''} {listing.description_raw or ''}".strip()
            existing_type = (
                listing.product_model.product_type.slug
                if listing.product_model and listing.product_model.product_type
                else None
            )
            detected_type = existing_type or detect_product_type(listing.title_raw or "", listing.description_raw or "")
            if product_type_slug and detected_type != product_type_slug:
                continue
            if not detected_type or not text:
                skipped += 1
                continue

            specs = extract_specs_from_text(detected_type, text)
            if not specs:
                skipped += 1
                continue

            processed += 1
            if set_product_type and listing.product_model and not listing.product_model.product_type:
                if dry_run:
                    self.stdout.write(
                        f"  #{listing.pk} WOULD SET product_type={detected_type} on model #{listing.product_model_id}"
                    )
                else:
                    listing.product_model.product_type = get_or_create_product_type(detected_type)
                    listing.product_model.save(update_fields=["product_type"])
                    typed += 1

            if dry_run:
                self.stdout.write(f"  #{listing.pk} WOULD WRITE {detected_type}: {specs}")
                continue

            if replace:
                MarketListingSpecValue.objects.filter(listing=listing).delete()
            saved = upsert_listing_specs_from_dict(listing, specs, confidence=listing.parsed_confidence or 0)
            written += len(saved)

            storage = specs.get("storage_gb") or specs.get("ssd_gb")
            if storage and not listing.storage_gb:
                listing.storage_gb = storage
                listing.save(update_fields=["storage_gb"])

            self.stdout.write(
                f"  #{listing.pk} wrote {len(saved)} spec values ({detected_type}): {listing.title_raw[:70]}"
            )

        verb = "Would write" if dry_run else "Wrote"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Processed {processed}, skipped {skipped}, set product_type {typed}. "
            f"{verb} {written} spec rows."
        ))
