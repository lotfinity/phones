"""Inspection command for the catalog spec system.

Usage:
    python manage.py inspect_catalog_specs

Prints:
- Product types
- Number of specs per type
- Sample spec definitions
- Count of listings with spec values
- Count of variants with spec values
"""

from django.core.management.base import BaseCommand

from market.models import (
    MarketListingSpecValue,
    ProductType,
    ProductVariantSpecValue,
    SpecDefinition,
)


class Command(BaseCommand):
    help = "Inspect catalog spec system state."

    def handle(self, *args, **options):
        product_types = ProductType.objects.all().order_by("name")
        if not product_types.exists():
            self.stdout.write(self.style.WARNING("No product types found. Run seed_product_types_and_specs first."))
            return

        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 60}"))
        self.stdout.write(self.style.SUCCESS(f"  CATALOG SPEC INSPECTION"))
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}\n"))

        for pt in product_types:
            specs = SpecDefinition.objects.filter(product_type=pt).order_by("sort_order", "key")
            spec_count = specs.count()
            variant_sv_count = ProductVariantSpecValue.objects.filter(spec__product_type=pt).count()
            listing_sv_count = MarketListingSpecValue.objects.filter(spec__product_type=pt).count()

            self.stdout.write(self.style.WARNING(f"  {pt.name} ({pt.slug})"))
            self.stdout.write(f"    Specs: {spec_count}")
            self.stdout.write(f"    Variants with spec values: {variant_sv_count}")
            self.stdout.write(f"    Listings with spec values: {listing_sv_count}")

            if specs.exists():
                self.stdout.write(f"    Sample definitions:")
                for spec in specs[:5]:
                    identity = " [identity]" if spec.is_variant_identity else ""
                    listing = " [listing]" if spec.is_listing_level else ""
                    unit = f" ({spec.unit})" if spec.unit else ""
                    self.stdout.write(
                        f"      - {spec.key}: {spec.label} ({spec.value_type}{unit}){identity}{listing}"
                    )
                if spec_count > 5:
                    self.stdout.write(f"      ... and {spec_count - 5} more")

            self.stdout.write("")

        total_variants = ProductVariantSpecValue.objects.count()
        total_listings = MarketListingSpecValue.objects.count()
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}"))
        self.stdout.write(f"  Total variant spec values: {total_variants}")
        self.stdout.write(f"  Total listing spec values: {total_listings}")
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}\n"))
