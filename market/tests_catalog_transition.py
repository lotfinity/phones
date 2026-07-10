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
from market.services.laptop_parser import parse_cpu, parse_resolution
from market.services.spec_extraction import (
    clean_extracted_specs,
    extract_specs_from_text,
    has_useful_specs,
)


class CatalogTransitionCommandTests(TestCase):
    def setUp(self):
        out = io.StringIO()
        call_command("seed_product_types_and_specs", verbosity=0, stdout=out)
        self.phone_type = get_or_create_product_type("phone", name="Phone")
        self.brand, _ = Brand.objects.get_or_create(name="Samsung")
        self.category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        self.model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            product_type=self.phone_type,
            canonical_name="Galaxy S25 Ultra",
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
            canonical_name="Galaxy A55",
        )
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=legacy_model,
            title_raw="Samsung Galaxy A55 256GB",
            listing_url="https://example.com/legacy-phone-row",
            match_level=MarketListing.MatchLevel.EXACT_VARIANT,
            match_confidence=0.95,
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


class CatalogTransitionHardeningTests(TestCase):
    """Tests for hardening of catalog transition backfill commands."""

    def setUp(self):
        out = io.StringIO()
        call_command("seed_product_types_and_specs", verbosity=0, stdout=out)
        self.phone_type = get_or_create_product_type("phone", name="Phone")
        self.brand, _ = Brand.objects.get_or_create(name="Samsung")
        self.category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        self.model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            product_type=self.phone_type,
            canonical_name="Galaxy S25 Ultra",
        )
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN,
            username="catalog-transition-hardening-test",
            defaults={"name": "Catalog Transition Hardening Test", "country": Country.TURKIYE},
        )

    def test_backfill_variant_specs_dry_run_counts_would_write_rows(self):
        """Dry-run should count how many spec rows would be written, not say 0."""
        DeviceVariant.objects.create(
            product_model=self.model,
            storage_gb=256,
            sim_config="2sim",
            canonical_label="Samsung Galaxy S25 Ultra 256GB 2sim",
        )

        out = io.StringIO()
        call_command("backfill_variant_specs", "--product-type=phone", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertNotIn("Would write 0 spec rows", text)
        self.assertIn("WOULD WRITE", text)

    def test_condition_unknown_alone_is_not_written_as_useful(self):
        """A spec dict with only condition=UNKNOWN should not be considered useful."""
        specs = {"condition": "unknown"}
        self.assertFalse(has_useful_specs(specs, "phone"))

        specs_cleaned = clean_extracted_specs(specs, "phone")
        self.assertNotIn("condition", specs_cleaned)

    def test_condition_unknown_filtered_from_laptop_specs(self):
        """extract_specs_from_text should filter out condition=UNKNOWN from laptop text."""
        specs = extract_specs_from_text("laptop", "Laptop ordinateur used")
        if "condition" in specs:
            self.assertNotEqual(specs["condition"], "unknown")

    def test_backfill_listing_specs_set_product_type_blocks_camera_console_tablet(self):
        """--set-product-type should not auto-set camera/console/tablet by default."""
        untyped_model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            canonical_name="Sony A7 Camera",
        )
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=untyped_model,
            title_raw="Sony A7 mirrorless camera body",
            listing_url="https://example.com/camera-test",
        )

        out = io.StringIO()
        call_command("backfill_listing_specs", "--set-product-type", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertNotIn("WOULD SET product_type=camera", output)

    def test_backfill_listing_specs_set_product_type_allows_phone(self):
        """--set-product-type should allow phone by default."""
        untyped_model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            canonical_name="Galaxy A16 128GB",
        )
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=untyped_model,
            title_raw="Samsung Galaxy A16 128GB Dual SIM",
            listing_url="https://example.com/phone-set-type-test",
        )

        out = io.StringIO()
        call_command("backfill_listing_specs", "--set-product-type", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("WOULD SET product_type=phone", output)

    def test_backfill_listing_specs_require_identity_spec_skips_panel_only_laptop(self):
        """--require-identity-spec should skip rows with only non-identity specs."""
        laptop_type = get_or_create_product_type("laptop", name="Laptop")
        laptop_category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        laptop_model = ProductModel.objects.create(
            brand=self.brand,
            category=laptop_category,
            product_type=laptop_type,
            canonical_name="Panel Only Laptop",
        )
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=laptop_model,
            title_raw="Samsung laptop IPS panel",
            listing_url="https://example.com/panel-only-laptop",
        )

        out = io.StringIO()
        call_command(
            "backfill_listing_specs",
            "--product-type=laptop",
            "--require-identity-spec",
            "--dry-run",
            stdout=out,
        )
        output = out.getvalue()
        self.assertNotIn("WOULD WRITE laptop", output)
        self.assertIn("Would write 0 spec rows", output)

    def test_resolution_va_is_not_treated_as_resolution(self):
        """parse_resolution should not return 'VA' as a resolution."""
        result = parse_resolution("Laptop IPS VA panel 1920x1080")
        self.assertNotEqual(result, "VA")
        self.assertNotEqual(result, "va")

    def test_resolution_ips_is_not_treated_as_resolution(self):
        """parse_resolution should not return panel types as resolution."""
        result = parse_resolution("15.6 inch IPS display FHD")
        self.assertNotEqual(result, "IPS")

    def test_apple_m0_is_rejected_as_cpu(self):
        """Apple M0 should not be matched as a valid CPU."""
        result = parse_cpu("Apple M0 chip laptop")
        self.assertNotEqual(result, "Apple M0")

    def test_apple_m9_is_rejected_as_cpu(self):
        """Apple M9 should not be matched as a valid CPU."""
        result = parse_cpu("Apple M9 Pro laptop")
        self.assertNotEqual(result, "Apple M9 Pro")

    def test_apple_m1_is_accepted_as_cpu(self):
        """Apple M1 should still be matched as a valid CPU."""
        result = parse_cpu("Apple M1 Pro laptop")
        self.assertEqual(result, "Apple M1 Pro")

    def test_apple_m4_is_accepted_as_cpu(self):
        """Apple M4 should be matched as a valid CPU."""
        result = parse_cpu("Apple M4 Max laptop")
        self.assertEqual(result, "Apple M4 Max")

    def test_recompute_dry_run_includes_legacy_phone_rows(self):
        """--product-type phone --dry-run should include untyped rows detected as phone."""
        legacy_model = ProductModel.objects.create(
            brand=self.brand,
            category=self.category,
            canonical_name="Galaxy A55 Untyped",
        )
        listing = MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=legacy_model,
            title_raw="Samsung Galaxy A55 256GB",
            listing_url="https://example.com/legacy-phone-recompute",
        )

        out = io.StringIO()
        call_command("recompute_listing_matches", "--product-type=phone", "--dry-run", "--limit=10", stdout=out)
        output = out.getvalue()
        self.assertIn(f"#{listing.pk}", output)

    def test_dry_run_does_not_mutate_db_for_backfill_variant_specs(self):
        """backfill_variant_specs --dry-run should not write any spec rows."""
        DeviceVariant.objects.create(
            product_model=self.model,
            storage_gb=256,
            sim_config="2sim",
            canonical_label="Samsung Galaxy S25 Ultra 256GB 2sim dry",
        )
        count_before = ProductVariantSpecValue.objects.count()

        out = io.StringIO()
        call_command("backfill_variant_specs", "--product-type=phone", "--dry-run", stdout=out)

        count_after = ProductVariantSpecValue.objects.count()
        self.assertEqual(count_before, count_after)

    def test_dry_run_does_not_mutate_db_for_backfill_listing_specs(self):
        """backfill_listing_specs --dry-run should not write any spec rows."""
        MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB Dual SIM dry",
            listing_url="https://example.com/listing-specs-dry",
        )
        count_before = MarketListingSpecValue.objects.count()

        out = io.StringIO()
        call_command("backfill_listing_specs", "--product-type=phone", "--dry-run", stdout=out)

        count_after = MarketListingSpecValue.objects.count()
        self.assertEqual(count_before, count_after)

    def test_dry_run_does_not_mutate_db_for_recompute(self):
        """recompute_listing_matches --dry-run should not change match_level."""
        listing = MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            product_model=self.model,
            title_raw="Samsung Galaxy S25 Ultra 256GB recompute dry",
            listing_url="https://example.com/recompute-dry",
            match_level=MarketListing.MatchLevel.UNMATCHED,
            match_confidence=0,
        )

        out = io.StringIO()
        call_command("recompute_listing_matches", "--product-type=phone", "--dry-run", "--limit=10", stdout=out)

        listing.refresh_from_db()
        self.assertEqual(listing.match_level, MarketListing.MatchLevel.UNMATCHED)
        self.assertEqual(listing.match_confidence, 0)
