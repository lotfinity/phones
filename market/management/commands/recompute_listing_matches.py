from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from market.models import MarketListing, MarketListingSpecValue
from market.services.spec_extraction import detect_product_type


class Command(BaseCommand):
    help = "Recompute match_level and match_confidence for existing listings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-type",
            type=str,
            default="",
            help="Filter by product type slug (e.g. laptop, phone). Untyped rows are detected from title text.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Max listings to recompute (default 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only recompute rows with unmatched/empty match data.",
        )

    def handle(self, *args, **options):
        from market.services.listing_matching import (
            apply_match_to_listing,
            match_listing_to_catalog,
            match_result_to_level,
        )
        from market.services.spec_extraction import extract_specs_from_text

        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be >= 1")
        limit = min(limit, 5000)

        qs = MarketListing.objects.select_related(
            "source", "product_model", "variant",
            "product_model__brand", "product_model__product_type",
        ).order_by("-id")

        if options["only_missing"]:
            qs = qs.filter(
                Q(match_level="") |
                Q(match_level=MarketListing.MatchLevel.UNMATCHED) |
                Q(match_confidence=0)
            )

        product_type_slug = options["product_type"].strip().lower()
        if product_type_slug:
            # First-pass DB narrowing for typed rows. Untyped rows are detected
            # row-by-row below so commands like --product-type phone still cover
            # legacy phone rows whose ProductModel.product_type is blank.
            qs = qs.filter(
                Q(product_model__product_type__slug=product_type_slug) |
                Q(product_model__product_type__isnull=True)
            )

        dry_run = options["dry_run"]
        candidates = list(qs[:limit])
        if product_type_slug:
            listings = []
            for listing in candidates:
                existing_slug = (
                    listing.product_model.product_type.slug
                    if listing.product_model and listing.product_model.product_type
                    else None
                )
                detected_slug = existing_slug or detect_product_type(listing.title_raw or "", listing.description_raw or "")
                if detected_slug == product_type_slug:
                    listings.append(listing)
        else:
            listings = candidates

        if not listings:
            self.stdout.write(self.style.WARNING("No listings found matching filters."))
            return

        updated = 0
        unchanged = 0
        errors = 0

        for listing in listings:
            try:
                old_level = listing.match_level or MarketListing.MatchLevel.UNMATCHED
                old_confidence = listing.match_confidence or 0

                text = f"{listing.title_raw or ''} {listing.description_raw or ''}".strip()
                product_type_slug_val = (
                    listing.product_model.product_type.slug
                    if listing.product_model and listing.product_model.product_type
                    else detect_product_type(listing.title_raw or "", listing.description_raw or "")
                )
                specs = extract_specs_from_text(product_type_slug_val, text) if text else {}

                brand_name = listing.product_model.brand.name if listing.product_model and listing.product_model.brand else None
                model_text = listing.product_model.canonical_name if listing.product_model else None

                match = match_listing_to_catalog(
                    title=listing.title_raw or "",
                    description=listing.description_raw or "",
                    product_type_slug=product_type_slug_val,
                    brand_name=brand_name,
                    model_text=model_text,
                    specs=specs,
                )
                new_level = match_result_to_level(match)
                new_confidence = match.confidence_score

                if not dry_run:
                    MarketListingSpecValue.objects.filter(listing=listing).delete()
                    apply_match_to_listing(listing, match, specs, confidence=match.confidence_score)
                    listing.save()

                if old_level != new_level or abs(old_confidence - new_confidence) > 0.01:
                    updated += 1
                    status = "WOULD UPDATE" if dry_run else "UPDATED"
                    self.stdout.write(
                        f"  #{listing.pk}: {old_level} -> {new_level} "
                        f"({old_confidence:.2f} -> {new_confidence:.2f}) [{status}]"
                    )
                else:
                    unchanged += 1

            except Exception as exc:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  #{listing.pk}: ERROR {exc}"))

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {verb} {updated}, unchanged {unchanged}, errors {errors} "
            f"(out of {len(listings)} listings)"
        ))
