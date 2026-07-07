from django.core.management.base import BaseCommand

from market.models import MarketListing, MarketListingSpecValue


class Command(BaseCommand):
    help = "Recompute match_level and match_confidence for existing listings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-type",
            type=str,
            default="",
            help="Filter by product type slug (e.g. laptop, phone).",
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

    def handle(self, *args, **options):
        from market.services.listing_matching import MatchResult, apply_match_to_listing, match_listing_to_catalog
        from market.services.spec_extraction import extract_specs_from_text

        qs = MarketListing.objects.select_related(
            "product_model", "variant",
            "product_model__product_type",
        ).order_by("-id")

        product_type_slug = options["product_type"]
        if product_type_slug:
            qs = qs.filter(product_model__product_type__slug=product_type_slug)

        limit = options["limit"]
        dry_run = options["dry_run"]

        listings = list(qs[:limit])
        if not listings:
            self.stdout.write(self.style.WARNING("No listings found matching filters."))
            return

        updated = 0
        unchanged = 0
        errors = 0

        for listing in listings:
            try:
                old_level = listing.match_level
                old_confidence = listing.match_confidence

                # Extract specs from title/description
                text = f"{listing.title_raw or ''} {listing.description_raw or ''}".strip()
                product_type_slug_val = (
                    listing.product_model.product_type.slug
                    if listing.product_model and listing.product_model.product_type
                    else None
                )
                specs = extract_specs_from_text(product_type_slug_val, text) if text else {}

                # Run matching
                brand_name = None
                model_text = None
                if listing.product_model and listing.product_model.brand:
                    brand_name = listing.product_model.brand.name
                if listing.product_model:
                    model_text = listing.product_model.canonical_name

                match = match_listing_to_catalog(
                    title=listing.title_raw or "",
                    description=listing.description_raw or "",
                    product_type_slug=product_type_slug_val,
                    brand_name=brand_name,
                    model_text=model_text,
                    specs=specs,
                )

                if not dry_run:
                    # Clear old spec values
                    MarketListingSpecValue.objects.filter(listing=listing).delete()
                    # Apply new match
                    apply_match_to_listing(listing, match, specs, confidence=match.confidence_score)
                    listing.save()

                new_level = match.confidence if not dry_run else _compute_level(match)
                new_confidence = match.confidence_score

                if old_level != new_level or abs(old_confidence - new_confidence) > 0.01:
                    updated += 1
                    status = "WOULD UPDATE" if dry_run else "UPDATED"
                    self.stdout.write(
                        f"  #{listing.pk}: {old_level} -> {new_level} "
                        f"({old_confidence:.2f} -> {new_confidence:.2f}) [{status}]"
                    )
                else:
                    unchanged += 1

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  #{listing.pk}: ERROR {e}"))

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {verb} {updated}, unchanged {unchanged}, errors {errors} "
            f"(out of {len(listings)} listings)"
        ))


def _compute_level(match: MatchResult) -> str:
    """Compute match level string from MatchResult without persisting."""
    from market.models import MarketListing

    if any("conflict" in r.lower() for r in match.reasons):
        return MarketListing.MatchLevel.CONFLICT

    confidence_to_level = {
        "exact": MarketListing.MatchLevel.EXACT_VARIANT,
        "high": MarketListing.MatchLevel.STRONG_CANDIDATE,
        "medium": MarketListing.MatchLevel.STRONG_CANDIDATE,
        "low": MarketListing.MatchLevel.MODEL_ONLY if match.product_model and not match.variant else MarketListing.MatchLevel.UNMATCHED,
        "none": MarketListing.MatchLevel.UNMATCHED,
    }
    return confidence_to_level.get(match.confidence, MarketListing.MatchLevel.UNMATCHED)
