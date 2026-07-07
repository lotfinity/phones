from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from market.models import (
    DeviceVariant,
    MarketListing,
    MarketListingSpecValue,
    ProductModel,
    ProductType,
    ProductVariantSpecValue,
    SpecDefinition,
)


class Command(BaseCommand):
    help = "Audit catalog/spec transition readiness and match quality coverage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-type",
            type=str,
            default="",
            help="Optional product type slug filter, e.g. phone or laptop.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Number of sample problematic rows to print per section.",
        )

    def handle(self, *args, **options):
        product_type_slug = options["product_type"].strip().lower()
        limit = max(1, min(options["limit"], 100))

        model_qs = ProductModel.objects.select_related("brand", "category", "product_type")
        listing_qs = MarketListing.objects.select_related("product_model", "product_model__product_type")
        variant_qs = DeviceVariant.objects.select_related("product_model", "product_model__product_type")

        if product_type_slug:
            model_qs = model_qs.filter(product_type__slug=product_type_slug)
            listing_qs = listing_qs.filter(product_model__product_type__slug=product_type_slug)
            variant_qs = variant_qs.filter(product_model__product_type__slug=product_type_slug)

        self.stdout.write(self.style.SUCCESS("\nCATALOG TRANSITION AUDIT"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Product type filter: {product_type_slug or 'all'}")
        self.stdout.write("")

        self._section("Product types")
        for pt in ProductType.objects.order_by("slug"):
            spec_count = SpecDefinition.objects.filter(product_type=pt).count()
            model_count = ProductModel.objects.filter(product_type=pt).count()
            self.stdout.write(f"  {pt.slug:16s} specs={spec_count:3d} models={model_count:5d}")

        self._section("Coverage")
        total_models = model_qs.count()
        typed_models = model_qs.filter(product_type__isnull=False).count()
        total_listings = listing_qs.count()
        listings_with_model = listing_qs.filter(product_model__isnull=False).count()
        listings_with_specs = listing_qs.filter(spec_values__isnull=False).distinct().count()
        total_variants = variant_qs.count()
        variants_with_specs = variant_qs.filter(spec_values__isnull=False).distinct().count()

        self.stdout.write(f"  Product models:        {typed_models}/{total_models} typed")
        self.stdout.write(f"  Market listings:       {listings_with_model}/{total_listings} with model")
        self.stdout.write(f"  Listing spec coverage: {listings_with_specs}/{total_listings}")
        self.stdout.write(f"  Variant spec coverage: {variants_with_specs}/{total_variants}")

        self._section("Match levels")
        rows = (
            listing_qs.values("match_level")
            .annotate(count=Count("id"))
            .order_by("match_level")
        )
        for row in rows:
            self.stdout.write(f"  {(row['match_level'] or '-'):18s} {row['count']:6d}")

        self._section("Opportunity-gate risk")
        typed_non_phone = listing_qs.exclude(product_model__product_type__isnull=True).exclude(
            product_model__product_type__slug="phone"
        )
        blocked = typed_non_phone.filter(
            Q(match_level__in=["", "unmatched", "conflict", "model_only"]) | Q(match_confidence__lt=0.70)
        )
        self.stdout.write(f"  Typed non-phone listings blocked by gates: {blocked.count()}")

        self._section("Samples: models missing product_type")
        for pm in model_qs.filter(product_type__isnull=True).order_by("brand__name", "canonical_name")[:limit]:
            brand = pm.brand.name if pm.brand else "-"
            cat = pm.category.slug if pm.category else "-"
            self.stdout.write(f"  #{pm.pk} {brand} / {pm.canonical_name} category={cat}")

        self._section("Samples: listings missing spec values")
        missing_spec_qs = listing_qs.filter(product_model__product_type__isnull=False).filter(spec_values__isnull=True)
        for listing in missing_spec_qs.order_by("-id")[:limit]:
            ptype = listing.product_model.product_type.slug if listing.product_model and listing.product_model.product_type else "-"
            self.stdout.write(f"  #{listing.pk} type={ptype} level={listing.match_level} title={listing.title_raw[:80]}")

        self._section("Samples: variants missing spec values")
        missing_variant_specs = variant_qs.filter(product_model__product_type__isnull=False).filter(spec_values__isnull=True)
        for variant in missing_variant_specs.order_by("-id")[:limit]:
            ptype = variant.product_model.product_type.slug if variant.product_model and variant.product_model.product_type else "-"
            self.stdout.write(f"  #{variant.pk} type={ptype} model={variant.product_model} label={variant.canonical_label}")

        self.stdout.write(self.style.SUCCESS("\nDone."))

    def _section(self, title: str):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(title))
        self.stdout.write("-" * len(title))
