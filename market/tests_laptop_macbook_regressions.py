"""Regression tests for MacBook parsing in the raw-first laptop pipeline."""

from django.test import TestCase, SimpleTestCase

from market.models import Country, ParsedListingCandidate, RawListing, SourceType
from market.services.parsing.candidate_builder import (
    _extract_macbook_model_from_text,
    build_candidate,
)


class MacBookModelExtractionTests(SimpleTestCase):
    def test_extracts_macbook_air_m1_from_ouedkniss_slug(self):
        text = "https://www.ouedkniss.com/macbooks-macbook-air-m1-2020-icloud-a2337-birkhadem-alger-algeria-d45677974"
        self.assertEqual(_extract_macbook_model_from_text(text), "MacBook Air M1")

    def test_extracts_macbook_air_m3_with_screen_size_noise(self):
        text = "macbooks-macbook-air-13-inch-m3-2024-icloud-constantine-algeria-d56173186"
        self.assertEqual(_extract_macbook_model_from_text(text), "MacBook Air M3")

    def test_extracts_macbook_pro_m3_pro(self):
        text = "Apple MacBook Pro 14 inch M3 Pro 18GB 512GB"
        self.assertEqual(_extract_macbook_model_from_text(text), "MacBook Pro M3 Pro")


class MacBookCandidateRepairTests(TestCase):
    def test_repairs_garbage_model_text_for_macbook_raw_listing(self):
        raw = RawListing.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/macbooks-macbook-air-m1-2020-icloud-a2337-birkhadem-alger-algeria-d45677974",
            title_raw="gpu ram gb storage gb",
            raw_text="gpu ram gb storage gb",
            price_text_raw="65000 DA",
            raw_payload={"legacy_price_original": "65000", "legacy_currency": "DZD"},
        )

        candidate, _created = build_candidate(raw)

        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)
        self.assertEqual(candidate.brand_text, "Apple")
        self.assertEqual(candidate.model_text, "MacBook Air M1")
        self.assertNotEqual(candidate.model_text.lower(), "gpu ram gb storage gb")
        self.assertEqual(candidate.laptop_specs_json["cpu"], "Apple M1")

    def test_generic_legion_without_specs_needs_review(self):
        raw = RawListing.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/laptop-lenovo-legion-bab-ezzouar-alger-algeria-d56390368",
            title_raw="Lenovo Legion",
            raw_text="Lenovo Legion",
            price_text_raw="105000 DA",
            raw_payload={"legacy_price_original": "105000", "legacy_currency": "DZD"},
        )

        candidate, _created = build_candidate(raw)

        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)
        self.assertEqual(candidate.brand_text, "Lenovo")
        self.assertEqual(candidate.model_text, "Legion")
        self.assertLess(candidate.confidence, 0.65)
        self.assertEqual(candidate.status, ParsedListingCandidate.Status.NEEDS_REVIEW)

    def test_garbage_model_tokens_are_needs_review(self):
        raw = RawListing.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=RawListing.CategoryHint.LAPTOPS,
            listing_url="https://www.ouedkniss.com/laptop-unknown-algeria-d999",
            title_raw="Apple gpu ram gb storage gb",
            raw_text="Apple gpu ram gb storage gb",
            price_text_raw="65000 DA",
            raw_payload={"legacy_price_original": "65000", "legacy_currency": "DZD"},
        )

        candidate, _created = build_candidate(raw)

        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)
        self.assertEqual(candidate.status, ParsedListingCandidate.Status.NEEDS_REVIEW)
        self.assertLess(candidate.confidence, 0.65)
