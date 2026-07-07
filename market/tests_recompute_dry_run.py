import io

from django.core.management import call_command
from django.test import TestCase

from market.models import (
    Brand,
    Category,
    Country,
    DeviceVariant,
    MarketListing,
    MarketListingSpecValue,
    ProductModel,
    ProductVariantSpecValue,
    Source,
    SourceType,
)
from market.services.catalog import get_or_create_product_type


class RecomputeDryRunMutationTests(TestCase):
    def setUp(self):
        out = io.StringIO()
        call_command("seed_product_types_and_specs", verbosity=0, stdout=out)
        phone_type = get_or_create_product_type("phone", name="Phone")
        brand, _ = Brand.objects.get_or_create(name="Samsung")
        category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        self.model = ProductModel.objects.create(
            brand=brand,
            category=category,
            product_type=phone_type,
            canonical_name="Galaxy S25 Ultra",
        )
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN,
            username="recompute-dry-run-test",
            defaults={"name": "Recompute Dry Run Test", "country": Country.TURKIYE},
        )

    def test_recompute_dry_run_does_not_create_variants_or_specs(self):
        listing = MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB",
            listing_url="https://example.com/recompute-dry-run-no-create",
            match_level=MarketListing.MatchLevel.UNMATCHED,
            match_confidence=0,
        )

        variant_count = DeviceVariant.objects.count()
        variant_spec_count = ProductVariantSpecValue.objects.count()
        listing_spec_count = MarketListingSpecValue.objects.count()

        out = io.StringIO()
        call_command(
            "recompute_listing_matches",
            "--product-type=phone",
            "--dry-run",
            "--limit=10",
            stdout=out,
        )

        listing.refresh_from_db()
        self.assertEqual(listing.match_level, MarketListing.MatchLevel.UNMATCHED)
        self.assertEqual(listing.match_confidence, 0)
        self.assertEqual(DeviceVariant.objects.count(), variant_count)
        self.assertEqual(ProductVariantSpecValue.objects.count(), variant_spec_count)
        self.assertEqual(MarketListingSpecValue.objects.count(), listing_spec_count)
        self.assertIn("WOULD UPDATE", out.getvalue())
