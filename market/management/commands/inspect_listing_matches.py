from django.core.management.base import BaseCommand

from market.models import (
    ALLOW_MODEL_ONLY_OPPORTUNITIES,
    MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
    OPPORTUNITY_ELIGIBLE_MATCH_LEVELS,
    MarketListing,
    MarketListingSpecValue,
)


class Command(BaseCommand):
    help = "Inspect listing match quality and opportunity eligibility."

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
            default=50,
            help="Max listings to print (default 50).",
        )
        parser.add_argument(
            "--level",
            type=str,
            default="",
            help="Filter by match_level (exact_variant, strong_candidate, model_only, unmatched, conflict).",
        )
        parser.add_argument(
            "--eligible-only",
            action="store_true",
            help="Show only listings eligible for opportunity analysis.",
        )

    def handle(self, *args, **options):
        qs = MarketListing.objects.select_related(
            "source", "product_model", "variant",
            "product_model__product_type",
        ).order_by("-id")

        product_type_slug = options["product_type"]
        if product_type_slug:
            qs = qs.filter(product_model__product_type__slug=product_type_slug)

        level = options["level"]
        if level:
            qs = qs.filter(match_level=level)

        if options["eligible_only"]:
            qs = qs.filter(
                match_level__in=list(OPPORTUNITY_ELIGIBLE_MATCH_LEVELS),
                match_confidence__gte=MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
            )

        limit = options["limit"]
        listings = list(qs[:limit])

        if not listings:
            self.stdout.write(self.style.WARNING("No listings found matching filters."))
            return

        # Summary
        total_qs = qs
        counts = {}
        for ml_value, ml_label in MarketListing.MatchLevel.choices:
            counts[ml_value] = total_qs.filter(match_level=ml_value).count()

        self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
        self.stdout.write(self.style.SUCCESS(f"MATCH QUALITY SUMMARY (showing {len(listings)} of {total_qs.count()} total)"))
        self.stdout.write(self.style.SUCCESS(f"{'='*80}"))
        self.stdout.write(f"  Eligible levels: {', '.join(OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)}")
        self.stdout.write(f"  Min match_confidence: {MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY}")
        self.stdout.write(f"  Allow model_only: {ALLOW_MODEL_ONLY_OPPORTUNITIES}")
        self.stdout.write("")
        for ml_value, ml_label in MarketListing.MatchLevel.choices:
            cnt = counts.get(ml_value, 0)
            eligible = ml_value in OPPORTUNITY_ELIGIBLE_MATCH_LEVELS
            marker = " [ELIGIBLE]" if eligible else ""
            self.stdout.write(f"  {ml_label:20s}: {cnt:5d}{marker}")
        self.stdout.write(self.style.SUCCESS(f"{'='*80}\n"))

        # Detail rows
        for listing in listings:
            # Get extracted specs
            spec_values = MarketListingSpecValue.objects.filter(
                listing=listing,
            ).select_related("spec", "option")
            specs_str = ", ".join(
                f"{sv.spec.key}={sv.effective_value}"
                for sv in spec_values
                if sv.effective_value
            ) or "-"

            # Eligibility check
            eligible = _is_eligible(listing)
            eligible_str = "YES" if eligible else "NO"

            self.stdout.write(f"Listing #{listing.pk}")
            self.stdout.write(f"  Source:       {listing.source_type} ({listing.country})")
            self.stdout.write(f"  Title:        {listing.title_raw[:80]}")
            self.stdout.write(f"  Product type: {listing.product_model.product_type.slug if listing.product_model and listing.product_model.product_type else '-'}")
            self.stdout.write(f"  Model:        {listing.product_model.canonical_name if listing.product_model else '-'}")
            self.stdout.write(f"  Variant:      {listing.variant.canonical_label if listing.variant else '-'}")
            self.stdout.write(f"  Specs:        {specs_str[:100]}")
            self.stdout.write(f"  Match level:  {listing.match_level}")
            self.stdout.write(f"  Match conf:   {listing.match_confidence:.2f}")
            self.stdout.write(f"  Review:       {listing.review_status}")
            self.stdout.write(f"  Eligible:     {eligible_str}")
            if listing.match_reason:
                self.stdout.write(f"  Reason:       {listing.match_reason[:100]}")
            self.stdout.write("")


def _is_eligible(listing: MarketListing) -> bool:
    """Check if a listing is eligible for opportunity analysis."""
    from market.models import (
        ALLOW_MODEL_ONLY_OPPORTUNITIES,
        MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
        OPPORTUNITY_ELIGIBLE_MATCH_LEVELS,
    )

    if not listing.product_model or not listing.product_model.product_type:
        return True
    if listing.product_model.product_type.slug == "phone":
        return True

    level = listing.match_level or MarketListing.MatchLevel.UNMATCHED
    if level in (MarketListing.MatchLevel.UNMATCHED, MarketListing.MatchLevel.CONFLICT):
        return False
    if level == MarketListing.MatchLevel.MODEL_ONLY and not ALLOW_MODEL_ONLY_OPPORTUNITIES:
        return False
    if level not in OPPORTUNITY_ELIGIBLE_MATCH_LEVELS:
        return False
    if listing.match_confidence < MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY:
        return False
    return True
