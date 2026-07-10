from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from market.management.commands.recompute_phone_opportunities_v2 import compute_phone_opportunity_rows
from market.models import (
    Brand,
    Country,
    PhoneListing,
    PhoneModel,
    Source,
    SourceType,
)


class RecomputePhoneOpportunitiesV2Tests(TestCase):
    def setUp(self):
        self.apple = Brand.objects.create(name="Apple")
        self.iphone = PhoneModel.objects.create(
            brand=self.apple,
            canonical_name="iPhone 15 Pro Max",
        )
        self.other = PhoneModel.objects.create(
            brand=self.apple,
            canonical_name="iPhone 14",
        )
        self.algeria_source = Source.objects.create(
            name="Ouedkniss",
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            username="ouedkniss-test",
        )
        self.tr_source = Source.objects.create(
            name="Sahibinden",
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            username="sahibinden-test",
        )

    def create_phone(self, *, country, source_type, model, storage, eur, status=None):
        source = self.algeria_source if country == Country.ALGERIA else self.tr_source
        return PhoneListing.objects.create(
            source=source,
            source_type=source_type,
            country=country,
            phone_model=model,
            storage_gb=storage,
            title=f"{model.canonical_name} {storage}GB",
            price_original=Decimal(str(eur)),
            currency_original="EUR",
            price_eur=Decimal(str(eur)),
            review_status=status or PhoneListing.ReviewStatus.NEEDS_REVIEW,
            listing_url=f"https://example.com/{country}/{model.pk}/{storage}/{eur}",
        )

    def test_group_with_algeria_and_turkiye_creates_row(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=256,
            eur="500",
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=256,
            eur="800",
        )

        rows = compute_phone_opportunity_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "iPhone 15 Pro Max")
        self.assertEqual(rows[0]["storage_gb"], 256)
        self.assertEqual(rows[0]["gross_margin_eur"], Decimal("300.00"))
        self.assertEqual(rows[0]["margin_percent"], Decimal("60.00"))
        self.assertEqual(rows[0]["buyer_proposal"]["proposed_buyer_price_eur"], Decimal("605.00"))
        self.assertEqual(rows[0]["gain_split"]["buyer_gain_eur"], Decimal("195.00"))

    def test_group_missing_turkiye_side_is_skipped(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.other,
            storage=128,
            eur="300",
        )

        rows = compute_phone_opportunity_rows()

        self.assertEqual(rows, [])

    def test_storage_grouping_keeps_storage_separate(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=128,
            eur="400",
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=128,
            eur="500",
        )
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=256,
            eur="600",
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=256,
            eur="900",
        )

        rows = compute_phone_opportunity_rows(min_margin_eur=Decimal("0"), limit=10)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["storage_gb"] for row in rows}, {128, 256})

    def test_filters_work(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=256,
            eur="500",
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=256,
            eur="550",
        )

        rows = compute_phone_opportunity_rows(min_margin_eur=Decimal("100"))

        self.assertEqual(rows, [])

    def test_only_approved_excludes_needs_review(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=256,
            eur="500",
            status=PhoneListing.ReviewStatus.NEEDS_REVIEW,
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=256,
            eur="800",
            status=PhoneListing.ReviewStatus.NEEDS_REVIEW,
        )

        rows = compute_phone_opportunity_rows(only_approved=True)

        self.assertEqual(rows, [])

    def test_command_outputs_table(self):
        self.create_phone(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.iphone,
            storage=256,
            eur="500",
        )
        self.create_phone(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.iphone,
            storage=256,
            eur="800",
        )
        out = StringIO()

        call_command("recompute_phone_opportunities_v2", stdout=out)

        text = out.getvalue()
        self.assertIn("Clean phone opportunity rows: 1", text)
        self.assertIn("iPhone 15 Pro Max", text)
        self.assertIn("300.00", text)
