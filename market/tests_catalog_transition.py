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
from market.services.listing_matching import apply_match_to_listing, match_listing_to_catalog


class CatalogTransitionCommandTests(TestCase):
    def setUp(self):
        call_command("seed_product_types_and_specs", verbosity=0)
        self.phone_type = get_or_create_product_type("phone", name="Phone")
        self.brand, _ = Brand.objects.get_or_create(name="Samsung")
        self.category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        self.model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            product_type=self.phone_type,
            canonical_name="Samsung Galaxy S25 Ultra",
        )
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN,
            username="catalog-transition-test",
            defaults={"name": "Catalog Transition Test", "country": Country.TURKIYE},
        )

    def test_phone_storage_match_persists_exact_variant(self):
        result = match_listing_to_catalog(
            title="Samsung Galaxy S25 Ultra 256GB",
            product_type_slug="phone",
            brand_name="Samsung",
            model_text="Samsung Galaxy S25 Ultra",
            specs={"storage_gb": 256},
        )
        self.assertEqual(result.product_model, self.model)
        self.assertIsNotNone(result.variant)
        self.assertEqual(result.confidence, "exact")

        listing = MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB",
            listing_url="https://example.com/catalog-phone-exact",
        )
        apply_match_to_listing(listing, result, {"storage_gb": 256})
        listing.save()
        listing.refresh_from_db()

        self.assertEqual(listing.match_level, MarketListing.MatchLevel.EXACT_VARIANT)
        self.assertAlmostEqual(listing.match_confidence, 0.95)
        self.assertEqual(listing.storage_gb, 256)

    def test_backfill_variant_specs_writes_phone_variant_specs(self):
        variant = DeviceVariant.objects.create(
            product_model=self.model,
            storage_gb=256,
            sim_config="2sim",
            canonical_label="Samsung Galaxy S25 Ultra 256GB 2sim",
        )

        out = io.StringIO()
        call_command("backfill_variant_specs", "--product-type=phone", stdout=out)

        keys = set(
            ProductVariantSpecValue.objects.filter(variant=variant)
            .values_list("spec__key", flat=True)
        )
        self.assertIn("storage_gb", keys)
        self.assertIn("sim_config", keys)

    def test_backfill_listing_specs_writes_phone_listing_specs(self):
        listing = MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB Dual SIM",
            listing_url="https://example.com/catalog-listing-specs",
        )

        out = io.StringIO()
        call_command("backfill_listing_specs", "--product-type=phone", stdout=out)

        keys = set(
            MarketListingSpecValue.objects.filter(listing=listing)
            .values_list("spec__key", flat=True)
        )
        self.assertIn("storage_gb", keys)
        listing.refresh_from_db()
        self.assertEqual(listing.storage_gb, 256)

    def test_audit_catalog_transition_runs(self):
        out = io.StringIO()
        call_command("audit_catalog_transition", "--limit=5", stdout=out)
        self.assertIn("CATALOG TRANSITION AUDIT", out.getvalue())

    def test_inspect_phone_eligible_only_includes_legacy_phone_rows(self):
        legacy_model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            canonical_name="Samsung Galaxy A55",
        )
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=legacy_model,
            title_raw="Samsung Galaxy A55 256GB",
            listing_url="https://example.com/legacy-phone-row",
        )

        out = io.StringIO()
        call_command("inspect_listing_matches", "--product-type=phone", "--eligible-only", "--limit=5", stdout=out)
        self.assertIn("Galaxy A55", out.getvalue())

    def test_recompute_dry_run_reports_persisted_match_level_names(self):
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB",
            listing_url="https://example.com/recompute-phone-exact",
            match_level=MarketListing.MatchLevel.UNMATCHED,
            match_confidence=0,
        )

        out = io.StringIO()
        call_command("recompute_listing_matches", "--product-type=phone", "--dry-run", "--limit=10", stdout=out)
        output = out.getvalue()
        self.assertIn("unmatched -> exact_variant", output)
        self.assertNotIn("unmatched -> exact ", output)
