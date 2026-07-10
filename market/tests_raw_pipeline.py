"""Tests for the raw pipeline: RawListing dedupe, parsers, candidate builder, and export."""

import hashlib
import io
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase

from market.models import (
    Brand,
    Condition,
    ConsoleListing,
    ConsoleModel,
    ConsoleVariant,
    Country,
    LaptopListing,
    LaptopModel,
    LaptopVariant,
    MarketListing,
    ParsedListingCandidate,
    PhoneListing,
    PhoneModel,
    PhoneVariant,
    RawImportRun,
    RawListing,
    Source,
    SourceType,
    build_laptop_variant_identity,
    build_phone_variant_identity,
)


def _uid():
    return uuid.uuid4().hex[:12]


class RawListingDedupeTests(TestCase):
    """Test content-hash deduplication and unique constraints on RawListing."""

    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS, username=f"dedup-{_uid()}",
            defaults={"name": "Test Dedup"},
        )

    def _make_raw(self, **overrides):
        defaults = {
            "source": self.source,
            "source_type": SourceType.OUEDKNISS,
            "country": Country.ALGERIA,
            "category_hint": RawListing.CategoryHint.PHONES,
            "title_raw": "Samsung Galaxy S25 256GB",
            "listing_url": f"https://example.com/{_uid()}",
            "raw_text": "Samsung Galaxy S25 256GB 180000 DA",
            "price_text_raw": "180000 DA",
        }
        defaults.update(overrides)
        return RawListing.objects.create(**defaults)

    def test_content_hash_auto_computed(self):
        raw = self._make_raw()
        self.assertIsNotNone(raw.content_hash)
        self.assertEqual(len(raw.content_hash), 64)

    def test_content_hash_deterministic(self):
        url1 = f"https://example.com/{_uid()}"
        url2 = f"https://example.com/{_uid()}"
        raw1 = self._make_raw(listing_url=url1)
        raw2 = self._make_raw(listing_url=url2)
        # Same source_type + different URLs should produce different hashes
        self.assertNotEqual(raw1.content_hash, raw2.content_hash)
        # But same inputs produce same hash
        h1 = hashlib.sha256(f"ouedkniss|{url1}".encode()).hexdigest()[:64]
        h2 = hashlib.sha256(f"ouedkniss|{url2}".encode()).hexdigest()[:64]
        self.assertEqual(raw1.content_hash, h1)
        self.assertEqual(raw2.content_hash, h2)

    def test_content_hash_differs_for_different_url(self):
        raw1 = self._make_raw(listing_url=f"https://example.com/a-{_uid()}")
        raw2 = self._make_raw(listing_url=f"https://example.com/b-{_uid()}")
        self.assertNotEqual(raw1.content_hash, raw2.content_hash)

    def test_content_hash_uses_url_when_present(self):
        url = f"https://example.com/{_uid()}"
        raw = self._make_raw(listing_url=url, title_raw="Title A", price_text_raw="100")
        expected = hashlib.sha256(f"ouedkniss|{url}".encode()).hexdigest()[:64]
        self.assertEqual(raw.content_hash, expected)

    def test_content_hash_fallback_without_url(self):
        raw = self._make_raw(listing_url="", title_raw="Samsung Galaxy S25", price_text_raw="180000")
        expected = hashlib.sha256("ouedkniss||Samsung Galaxy S25|180000".encode()).hexdigest()[:64]
        self.assertEqual(raw.content_hash, expected)

    def test_unique_constraint_source_url(self):
        url = f"https://example.com/{_uid()}"
        self._make_raw(listing_url=url)
        with self.assertRaises(Exception):
            self._make_raw(listing_url=url)

    def test_different_source_same_url_allowed(self):
        source2, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username=f"dedup2-{_uid()}",
            defaults={"name": "Test Dedup 2"},
        )
        url = f"https://example.com/{_uid()}"
        self._make_raw(listing_url=url)
        raw2 = self._make_raw(source=source2, source_type=SourceType.SAHIBINDEN, listing_url=url)
        self.assertIsNotNone(raw2.pk)

    def test_empty_url_allows_same_source(self):
        self._make_raw(listing_url="", title_raw="Listing A")
        raw2 = self._make_raw(listing_url="", title_raw="Listing B")
        self.assertIsNotNone(raw2.pk)

    def test_parse_status_default_is_raw(self):
        raw = self._make_raw()
        self.assertEqual(raw.parse_status, RawListing.ParseStatus.RAW)

    def test_str_fallback(self):
        raw = self._make_raw(listing_url="", title_raw="")
        self.assertIn("RawListing", str(raw))


class PhoneParserV2Tests(SimpleTestCase):
    """Test phone_parser_v2 regex extraction from raw text."""

    def test_detect_brand_samsung(self):
        from market.services.parsing.phone_parser_v2 import detect_brand
        brand = detect_brand("Samsung Galaxy S25 Ultra 256GB")
        self.assertEqual(brand, "Samsung")

    def test_detect_brand_apple(self):
        from market.services.parsing.phone_parser_v2 import detect_brand
        brand = detect_brand("iPhone 16 Pro Max 512GB")
        self.assertEqual(brand, "Apple")

    def test_detect_brand_xiaomi(self):
        from market.services.parsing.phone_parser_v2 import detect_brand
        brand = detect_brand("Xiaomi Redmi Note 13 Pro 256GB")
        self.assertEqual(brand, "Xiaomi")

    def test_detect_brand_unknown(self):
        from market.services.parsing.phone_parser_v2 import detect_brand
        brand = detect_brand("Random text no brand name")
        self.assertEqual(brand, "")

    def test_detect_price_dzd(self):
        from market.services.parsing.phone_parser_v2 import detect_price
        price = detect_price("Samsung Galaxy S25 Ultra 180000 DA")
        self.assertEqual(price, Decimal("180000"))

    def test_detect_price_with_commas(self):
        from market.services.parsing.phone_parser_v2 import detect_price
        price = detect_price("180,000 DA")
        self.assertEqual(price, Decimal("180000"))

    def test_detect_price_eur(self):
        from market.services.parsing.phone_parser_v2 import detect_price
        price = detect_price("€499 Samsung phone")
        self.assertEqual(price, Decimal("499"))

    def test_detect_price_none(self):
        from market.services.parsing.phone_parser_v2 import detect_price
        price = detect_price("No price here")
        self.assertIsNone(price)

    def test_detect_price_ignores_multiline_barcode_noise(self):
        from market.services.parsing.phone_parser_v2 import detect_price
        text = "IPHONE 11 2677717722972\n000008-008271-22062026\n33000da"
        self.assertEqual(detect_price(text), Decimal("33000"))

    def test_detect_storage_gb(self):
        from market.services.parsing.phone_parser_v2 import detect_storage
        storage = detect_storage("Samsung Galaxy S25 256GB")
        self.assertEqual(storage, 256)

    def test_detect_storage_none(self):
        from market.services.parsing.phone_parser_v2 import detect_storage
        storage = detect_storage("Samsung Galaxy S25 no storage mentioned")
        self.assertIsNone(storage)

    def test_detect_ram_gb(self):
        from market.services.parsing.phone_parser_v2 import detect_ram
        ram = detect_ram("Samsung Galaxy S25 8GB RAM 256GB")
        self.assertEqual(ram, 8)

    def test_detect_sim_dual(self):
        from market.services.parsing.phone_parser_v2 import detect_sim
        sim = detect_sim("Samsung Galaxy S25 2SIM 256GB")
        self.assertEqual(sim, "2sim")

    def test_detect_condition_sealed(self):
        from market.services.parsing.phone_parser_v2 import detect_condition
        cond = detect_condition("Samsung Galaxy S25 sealed new in box")
        self.assertEqual(cond, "sealed")

    def test_detect_condition_used(self):
        from market.services.parsing.phone_parser_v2 import detect_condition
        cond = detect_condition("Samsung Galaxy S25 ikinci el")
        self.assertEqual(cond, "used")

    def test_parse_phone_returns_segments(self):
        from market.services.parsing.phone_parser_v2 import parse_phone
        result = parse_phone("Samsung Galaxy S25 256GB 8GB RAM 180000 DA", None, {})
        self.assertIn("segments", result)
        self.assertIsInstance(result["segments"], list)
        self.assertGreater(len(result["segments"]), 0)

    def test_parse_phone_brand_model(self):
        from market.services.parsing.phone_parser_v2 import parse_phone
        result = parse_phone("Samsung Galaxy S25 Ultra 256GB 180000 DA", None, {})
        self.assertEqual(result["brand_text"], "Samsung")
        self.assertIn("Galaxy S25", result["model_text"])

    def test_parse_phone_confidence(self):
        from market.services.parsing.phone_parser_v2 import parse_phone
        result = parse_phone("Samsung Galaxy S25 Ultra 256GB 8GB RAM 180000 DA", None, {})
        self.assertGreater(result["confidence"], 0.5)


class LaptopParserV2Tests(SimpleTestCase):
    """Test laptop_parser_v2 regex extraction from raw text."""

    def test_detect_brand_lenovo(self):
        from market.services.parsing.laptop_parser_v2 import detect_brand
        brand = detect_brand("Lenovo IdeaPad 3 15.6 i5 8GB")
        self.assertEqual(brand, "Lenovo")

    def test_detect_brand_apple_macbook(self):
        from market.services.parsing.laptop_parser_v2 import detect_brand
        brand = detect_brand("MacBook Pro M3 14 inch 16GB")
        self.assertEqual(brand, "Apple")

    def test_detect_cpu_intel(self):
        from market.services.parsing.laptop_parser_v2 import detect_cpu
        cpu = detect_cpu("Lenovo IdeaPad i5-1235U 8GB")
        self.assertIn("i5", cpu)

    def test_detect_gpu_nvidia(self):
        from market.services.parsing.laptop_parser_v2 import detect_gpu
        gpu = detect_gpu("Lenovo IdeaPad RTX 4060 8GB")
        self.assertIn("RTX", gpu)

    def test_detect_screen_size(self):
        from market.services.parsing.laptop_parser_v2 import detect_screen_size
        size = detect_screen_size("15.6 inch laptop")
        self.assertAlmostEqual(size, 15.6)

    def test_parse_laptop_basic(self):
        from market.services.parsing.laptop_parser_v2 import parse_laptop
        result = parse_laptop("Lenovo IdeaPad 3 i5-1235U 8GB RAM 256GB SSD 15.6 500000 DA", None, {})
        self.assertEqual(result["brand_text"], "Lenovo")
        self.assertIn("i5", result.get("cpu", ""))


class CandidateBuilderTests(TestCase):
    """Test candidate_builder routing and ParsedListingCandidate creation."""

    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS, username=f"candidate-{_uid()}",
            defaults={"name": "Test Candidate"},
        )

    def _make_raw(self, text, title=None, category="phones"):
        return RawListing.objects.create(
            source=self.source,
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=category,
            title_raw=title or text[:100],
            raw_text=text,
            listing_url=f"https://example.com/{_uid()}",
            price_text_raw="180000 DA",
        )

    def test_build_candidate_phone(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("Samsung Galaxy S25 Ultra 256GB 8GB RAM 180000 DA")
        candidate, created = build_candidate(raw)
        self.assertTrue(created)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.PHONE)
        self.assertEqual(candidate.brand_text, "Samsung")
        self.assertIsNotNone(candidate.price_original)

    def test_build_candidate_updates_existing(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("Samsung Galaxy S25 256GB 180000 DA")
        c1, created1 = build_candidate(raw)
        self.assertTrue(created1)
        c2, created2 = build_candidate(raw)
        self.assertFalse(created2)
        self.assertEqual(c1.pk, c2.pk)

    def test_build_candidate_sets_raw_parse_status(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("Samsung Galaxy S25 256GB 180000 DA")
        build_candidate(raw)
        raw.refresh_from_db()
        self.assertIn(raw.parse_status, [
            RawListing.ParseStatus.PARSED,
            RawListing.ParseStatus.NEEDS_REVIEW,
        ])

    def test_build_candidate_low_confidence_needs_review(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("random garbage text no brand no model")
        candidate, _ = build_candidate(raw)
        self.assertEqual(candidate.status, ParsedListingCandidate.Status.NEEDS_REVIEW)

    def test_build_candidate_phone_specs_populated(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("Samsung Galaxy S25 256GB 8GB RAM 180000 DA")
        candidate, _ = build_candidate(raw)
        specs = candidate.phone_specs_json
        self.assertIn("storage_gb", specs)
        self.assertEqual(specs["storage_gb"], 256)

    def test_build_candidate_laptop_category(self):
        from market.services.parsing.candidate_builder import build_candidate
        raw = self._make_raw("Lenovo IdeaPad 3 i5-1235U 8GB 256GB SSD 15.6 500000 DA", category="laptops")
        candidate, _ = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)


class IdentityKeyTests(SimpleTestCase):
    """Test variant identity key builders."""

    def test_phone_identity_key_basic(self):
        key = build_phone_variant_identity(256, 8, "2sim", "", "")
        self.assertIn("256", key)
        self.assertIn("8", key)

    def test_phone_identity_key_deterministic(self):
        k1 = build_phone_variant_identity(256, 8, "2sim", "", "black")
        k2 = build_phone_variant_identity(256, 8, "2sim", "", "black")
        self.assertEqual(k1, k2)

    def test_phone_identity_key_differs_by_storage(self):
        k1 = build_phone_variant_identity(128, 8, "", "", "")
        k2 = build_phone_variant_identity(256, 8, "", "", "")
        self.assertNotEqual(k1, k2)

    def test_laptop_identity_key_basic(self):
        key = build_laptop_variant_identity("i5-1235U", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        self.assertIn("i5", key)
        self.assertIn("rtx", key)

    def test_laptop_identity_key_deterministic(self):
        k1 = build_laptop_variant_identity("i5", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        k2 = build_laptop_variant_identity("i5", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        self.assertEqual(k1, k2)


class ParseRawListingsCommandTests(TestCase):
    """Test the parse_raw_listings management command."""

    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS, username=f"parse-{_uid()}",
            defaults={"name": "Test Parse Cmd"},
        )

    def _make_raw(self, text, category="phones"):
        return RawListing.objects.create(
            source=self.source,
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=category,
            title_raw=text[:100],
            raw_text=text,
            listing_url=f"https://example.com/{_uid()}",
            price_text_raw="180000 DA",
        )

    def test_parse_raw_listings_creates_candidates(self):
        self._make_raw("Samsung Galaxy S25 256GB 180000 DA")
        out = io.StringIO()
        call_command("parse_raw_listings", "--limit=10", stdout=out)
        self.assertEqual(ParsedListingCandidate.objects.count(), 1)

    def test_parse_raw_listings_updates_parse_status(self):
        raw = self._make_raw("Samsung Galaxy S25 256GB 180000 DA")
        call_command("parse_raw_listings", "--limit=10", stdout=io.StringIO())
        raw.refresh_from_db()
        self.assertNotEqual(raw.parse_status, RawListing.ParseStatus.RAW)

    def test_parse_raw_listings_with_category_filter(self):
        self._make_raw("Samsung Galaxy S25 256GB", category="phones")
        self._make_raw("Lenovo IdeaPad i5 8GB", category="laptops")
        out = io.StringIO()
        call_command("parse_raw_listings", "--category=phones", "--limit=10", stdout=out)
        self.assertEqual(ParsedListingCandidate.objects.filter(detected_category="phone").count(), 1)
        self.assertEqual(ParsedListingCandidate.objects.filter(detected_category="laptop").count(), 0)

    def test_parse_raw_listings_skips_already_parsed(self):
        self._make_raw("Samsung Galaxy S25 256GB 180000 DA")
        call_command("parse_raw_listings", "--limit=10", stdout=io.StringIO())
        count1 = ParsedListingCandidate.objects.count()
        call_command("parse_raw_listings", "--limit=10", stdout=io.StringIO())
        count2 = ParsedListingCandidate.objects.count()
        self.assertEqual(count1, count2)


class ExportCandidatesCommandTests(TestCase):
    """Test the export_candidates management command."""

    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS, username=f"export-{_uid()}",
            defaults={"name": "Test Export Cmd"},
        )

    def _make_approved_candidate(self, category="phone"):
        if category == "laptop":
            title = "Lenovo Legion 5 Ryzen 7 RTX 3060 16GB RAM 512GB SSD"
            raw_text = f"{title} 180000 DA"
        elif category == "console":
            title = "Lenovo Legion Go Z1 Extreme 512GB"
            raw_text = f"{title} 180000 DA"
        else:
            title = "Samsung Galaxy S25 256GB"
            raw_text = "Samsung Galaxy S25 256GB 8GB RAM 180000 DA"
        raw = RawListing.objects.create(
            source=self.source,
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=(
                "phones"
                if category == "phone"
                else "consoles"
                if category == "console"
                else "laptops"
            ),
            title_raw=title,
            raw_text=raw_text,
            listing_url=f"https://example.com/{_uid()}",
            price_text_raw="180000 DA",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, _ = build_candidate(raw)
        candidate.status = ParsedListingCandidate.Status.APPROVED
        candidate.save(update_fields=["status"])
        return candidate

    def test_export_phone_creates_phone_listing(self):
        self._make_approved_candidate("phone")
        out = io.StringIO()
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=out)
        self.assertEqual(PhoneListing.objects.count(), 1)

    def test_export_phone_sets_raw_listing_fk(self):
        candidate = self._make_approved_candidate("phone")
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        listing = PhoneListing.objects.first()
        self.assertEqual(listing.raw_listing, candidate.raw_listing)

    def test_export_phone_creates_model_and_variant(self):
        self._make_approved_candidate("phone")
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        self.assertGreater(PhoneModel.objects.count(), 0)
        self.assertGreater(PhoneVariant.objects.count(), 0)

    def test_export_phone_sets_exported_status(self):
        candidate = self._make_approved_candidate("phone")
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, ParsedListingCandidate.Status.EXPORTED)

    def test_export_phone_sets_raw_listing_exported(self):
        candidate = self._make_approved_candidate("phone")
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        candidate.raw_listing.refresh_from_db()
        self.assertEqual(candidate.raw_listing.parse_status, RawListing.ParseStatus.EXPORTED)

    def test_export_laptop_creates_laptop_listing(self):
        self._make_approved_candidate("laptop")
        out = io.StringIO()
        call_command("export_candidates", "--category=laptops", "--limit=10", stdout=out)
        self.assertEqual(LaptopListing.objects.count(), 1)

    def test_export_laptop_sets_raw_listing_fk(self):
        candidate = self._make_approved_candidate("laptop")
        call_command("export_candidates", "--category=laptops", "--limit=10", stdout=io.StringIO())
        listing = LaptopListing.objects.first()
        self.assertEqual(listing.raw_listing, candidate.raw_listing)

    def test_export_console_creates_console_listing(self):
        self._make_approved_candidate("console")
        call_command("export_candidates", "--category=consoles", "--limit=10", stdout=io.StringIO())
        self.assertEqual(ConsoleListing.objects.count(), 1)
        self.assertEqual(ConsoleModel.objects.count(), 1)
        self.assertEqual(ConsoleVariant.objects.count(), 1)

    def test_export_laptop_blocks_unsafe_candidate(self):
        raw = RawListing.objects.create(
            source=self.source,
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint="laptops",
            title_raw="Lenovo Legion",
            raw_text="Lenovo Legion 180000 DA",
            listing_url=f"https://example.com/{_uid()}",
            price_text_raw="180000 DA",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, _ = build_candidate(raw)
        candidate.status = ParsedListingCandidate.Status.APPROVED
        candidate.save(update_fields=["status"])

        call_command("export_candidates", "--category=laptops", "--limit=10", stdout=io.StringIO())

        self.assertEqual(LaptopListing.objects.count(), 0)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, ParsedListingCandidate.Status.NEEDS_REVIEW)

    def test_export_idempotent(self):
        self._make_approved_candidate("phone")
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        count1 = PhoneListing.objects.count()
        PhoneListing.objects.all().delete()
        candidate = ParsedListingCandidate.objects.filter(detected_category="phone").first()
        candidate.status = ParsedListingCandidate.Status.APPROVED
        candidate.save(update_fields=["status"])
        call_command("export_candidates", "--category=phones", "--limit=10", stdout=io.StringIO())
        count2 = PhoneListing.objects.count()
        self.assertEqual(count1, count2)


class BackfillCommandTests(TestCase):
    """Test the backfill_raw_from_market_listings management command."""

    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS, username=f"backfill-{_uid()}",
            defaults={"name": "Test Backfill"},
        )

    def _make_listing(self, url=None):
        if url is None:
            url = f"https://example.com/{_uid()}"
        return MarketListing.objects.create(
            source=self.source,
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            title_raw="Samsung Galaxy S25 256GB",
            description_raw="Test description",
            price_original=Decimal("180000"),
            currency_original="DZD",
            listing_url=url,
            price_eur=Decimal("1200.00"),
        )

    def test_backfill_creates_raw_listings(self):
        self._make_listing()
        out = io.StringIO()
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=out)
        self.assertEqual(RawListing.objects.count(), 1)

    def test_backfill_preserves_legacy_id(self):
        listing = self._make_listing()
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=io.StringIO())
        raw = RawListing.objects.first()
        self.assertEqual(raw.raw_payload.get("legacy_market_listing_id"), listing.pk)

    def test_backfill_dry_run_no_changes(self):
        self._make_listing()
        out = io.StringIO()
        call_command("backfill_raw_from_market_listings", "--dry-run", "--limit=10", stdout=out)
        self.assertEqual(RawListing.objects.count(), 0)
        self.assertIn("DRY RUN", out.getvalue())

    def test_backfill_skips_duplicates(self):
        url = f"https://example.com/{_uid()}"
        self._make_listing(url)
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=io.StringIO())
        self.assertEqual(RawListing.objects.count(), 1)
        out = io.StringIO()
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=out)
        self.assertEqual(RawListing.objects.count(), 1)
        self.assertIn("skipped 1", out.getvalue())

    def test_backfill_sets_category_hint_phones(self):
        self._make_listing()
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=io.StringIO())
        raw = RawListing.objects.first()
        self.assertEqual(raw.category_hint, RawListing.CategoryHint.PHONES)

    def test_backfill_sets_category_hint_laptops(self):
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username=f"backfill-laptop-{_uid()}",
            defaults={"name": "Test Backfill Laptop"},
        )
        listing = MarketListing.objects.create(
            source=source,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            title_raw="MacBook Pro M3 laptop 16GB",
            description_raw="Test description",
            price_original=Decimal("50000"),
            currency_original="TRY",
            listing_url=f"https://example.com/{_uid()}",
            price_eur=Decimal("1200.00"),
        )
        call_command("backfill_raw_from_market_listings", "--limit=10", stdout=io.StringIO())
        raw = RawListing.objects.first()
        self.assertEqual(raw.category_hint, RawListing.CategoryHint.LAPTOPS)


class SegmentTests(SimpleTestCase):
    """Test segment helpers."""

    def test_make_segment(self):
        from market.services.parsing.segments import make_segment
        seg = make_segment("brand", "Samsung", 0, 7, 0.9)
        self.assertEqual(seg["label"], "brand")
        self.assertEqual(seg["text"], "Samsung")
        self.assertEqual(seg["start"], 0)
        self.assertEqual(seg["end"], 7)
        self.assertAlmostEqual(seg["confidence"], 0.9)

    def test_find_regex_segments(self):
        from market.services.parsing.segments import find_regex_segments
        segs = find_regex_segments("Samsung Galaxy S25 256GB", r"\d+GB", "storage")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"], "256GB")

    def test_merge_segments_removes_contained(self):
        from market.services.parsing.segments import merge_segments
        segs = [
            {"label": "a", "text": "ab", "start": 0, "end": 2, "confidence": 0.8},
            {"label": "b", "text": "b", "start": 1, "end": 2, "confidence": 0.9},
        ]
        merged = merge_segments(segs)
        self.assertEqual(len(merged), 1)

    def test_segments_to_html(self):
        from market.services.parsing.segments import segments_to_html
        segs = [{"label": "brand", "text": "Samsung", "start": 0, "end": 7, "confidence": 0.9}]
        html = segments_to_html("Samsung Galaxy S25", segs)
        self.assertIn("Samsung", html)
        self.assertIn("background-color", html)

    def test_segments_to_html_empty(self):
        from market.services.parsing.segments import segments_to_html
        html = segments_to_html("Hello", [])
        self.assertIn("Hello", html)


class AgentReviewCandidatesTests(TestCase):
    def _raw(self, title, category_hint=RawListing.CategoryHint.UNKNOWN):
        return RawListing.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=category_hint,
            title_raw=title,
            raw_text=title,
            listing_url=f"https://example.com/{_uid()}",
        )

    def _candidate(self, title, detected_category, **overrides):
        defaults = {
            "raw_listing": self._raw(title),
            "detected_category": detected_category,
            "brand_text": "",
            "model_text": "",
            "confidence": 0.4,
            "status": ParsedListingCandidate.Status.NEEDS_REVIEW,
        }
        defaults.update(overrides)
        return ParsedListingCandidate.objects.create(**defaults)

    def test_default_queryset_excludes_accessories_and_unknowns(self):
        from market.management.commands.agent_review_candidates import candidate_queryset

        phone = self._candidate(
            "iPhone 15 Pro 256GB",
            ParsedListingCandidate.DetectedCategory.PHONE,
            brand_text="Apple",
            model_text="iPhone 15 Pro",
        )
        laptop = self._candidate(
            "MacBook Air M1 8GB 256GB",
            ParsedListingCandidate.DetectedCategory.LAPTOP,
            brand_text="Apple",
            model_text="MacBook Air M1",
        )
        self._candidate(
            "Lenovo laptop bag",
            ParsedListingCandidate.DetectedCategory.UNKNOWN,
            brand_text="Lenovo",
            model_text="",
        )

        qs = candidate_queryset({
            "candidate_id": None,
            "flagged_only": False,
            "status": ParsedListingCandidate.Status.NEEDS_REVIEW,
            "categories": ("phone", "laptop"),
            "bucket": "",
        })

        self.assertEqual(set(qs.values_list("id", flat=True)), {phone.id, laptop.id})

    def test_laptop_ai_approval_downgrades_without_export_identity(self):
        from market.management.commands.agent_review_candidates import validate_decision

        candidate = self._candidate(
            "Lenovo Legion",
            ParsedListingCandidate.DetectedCategory.LAPTOP,
            brand_text="Lenovo",
            model_text="Legion",
            confidence=0.9,
            laptop_specs_json={},
        )
        decision = {
            "candidate_id": candidate.id,
            "detected_category": "laptop",
            "brand_text": "Lenovo",
            "model_text": "Legion",
            "model_id": None,
            "condition": Condition.UNKNOWN,
            "status": ParsedListingCandidate.Status.APPROVED,
            "confidence": 0.9,
            "laptop_specs": {},
            "reason": "Only generic family is visible.",
            "evidence": "title",
        }

        validated = validate_decision(candidate, decision)

        self.assertEqual(validated["status"], ParsedListingCandidate.Status.NEEDS_REVIEW)
        self.assertIn("Export blocked", validated["reason"])

    def test_laptop_ai_approval_kept_with_model_ram_storage(self):
        from market.management.commands.agent_review_candidates import validate_decision

        candidate = self._candidate(
            "MacBook Air M1 8GB 256GB",
            ParsedListingCandidate.DetectedCategory.LAPTOP,
            brand_text="Apple",
            model_text="MacBook Air M1",
            confidence=0.9,
            laptop_specs_json={"ram_gb": 8, "storage_gb": 256},
        )
        decision = {
            "candidate_id": candidate.id,
            "detected_category": "laptop",
            "brand_text": "Apple",
            "model_text": "MacBook Air M1",
            "model_id": None,
            "condition": Condition.UNKNOWN,
            "status": ParsedListingCandidate.Status.APPROVED,
            "confidence": 0.9,
            "laptop_specs": {"ram_gb": 8, "storage_gb": 256},
            "reason": "Model and storage/RAM are explicit.",
            "evidence": "title",
        }

        validated = validate_decision(candidate, decision)

        self.assertEqual(validated["status"], ParsedListingCandidate.Status.APPROVED)
