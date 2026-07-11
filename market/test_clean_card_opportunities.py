from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
from market.models import Brand, Condition, Country, PhoneListing, PhoneModel, SourceType


class CleanCardOpportunityViewTests(TestCase):
    def setUp(self):
        self.apple = Brand.objects.create(name="Apple")
        self.phone_model = PhoneModel.objects.create(
            brand=self.apple,
            canonical_name="iPhone Test",
        )
        self.other_phone_model = PhoneModel.objects.create(
            brand=self.apple,
            canonical_name="Different iPhone",
        )

        self.phone = PhoneOpportunitySnapshot.objects.create(
            phone_model=self.phone_model,
            brand="Apple",
            model="iPhone Test",
            storage_gb=256,
            algeria_min_eur=Decimal("500.00"),
            algeria_avg_eur=Decimal("520.00"),
            turkiye_min_eur=Decimal("700.00"),
            turkiye_avg_eur=Decimal("750.00"),
            gross_margin_eur=Decimal("250.00"),
            margin_percent=Decimal("50.00"),
            algeria_count=2,
            turkiye_count=3,
            algeria_urls=["https://example.com/dz-phone"],
            turkiye_urls=["https://example.com/tr-phone"],
            recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
            confidence_score=90,
            source_label="phone-test-source",
        )
        self.laptop = LaptopOpportunitySnapshot.objects.create(
            brand="Apple",
            model="MacBook Test",
            cpu="M4",
            ram_gb=16,
            storage_gb=512,
            algeria_min_eur=Decimal("900.00"),
            turkiye_avg_eur=Decimal("1100.00"),
            gross_margin_eur=Decimal("200.00"),
            margin_percent=Decimal("22.22"),
            algeria_count=1,
            turkiye_count=2,
            recommendation=LaptopOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
            confidence_score=85,
        )
        self.console = ConsoleOpportunitySnapshot.objects.create(
            brand="Valve",
            model="Steam Deck Test",
            storage_gb=512,
            algeria_min_eur=Decimal("400.00"),
            turkiye_avg_eur=Decimal("500.00"),
            gross_margin_eur=Decimal("100.00"),
            margin_percent=Decimal("25.00"),
            algeria_count=1,
            turkiye_count=1,
            recommendation=ConsoleOpportunitySnapshot.Recommendation.WATCH,
            confidence_score=70,
        )

        self.algeria_listing = PhoneListing.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            phone_model=self.phone_model,
            title="Clean Algeria iPhone listing",
            price_original=Decimal("150000.00"),
            currency_original="DZD",
            price_eur=Decimal("500.00"),
            condition=Condition.USED_A,
            storage_gb=256,
            battery_health=94,
            listing_url="https://example.com/dz-phone",
            image_url="https://example.com/dz-phone.jpg",
            parsed_confidence=0.93,
            review_status=PhoneListing.ReviewStatus.APPROVED,
        )
        self.turkiye_listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.phone_model,
            title="Clean Türkiye iPhone listing",
            price_original=Decimal("40000.00"),
            currency_original="TRY",
            price_eur=Decimal("750.00"),
            condition=Condition.SEALED,
            storage_gb=256,
            listing_url="https://example.com/tr-phone",
            image_url="https://example.com/tr-phone.jpg",
            parsed_confidence=0.88,
            review_status=PhoneListing.ReviewStatus.AUTO,
        )
        PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.other_phone_model,
            title="Unrelated clean phone listing",
            price_original=Decimal("42000.00"),
            currency_original="TRY",
            price_eur=Decimal("780.00"),
            condition=Condition.SEALED,
            storage_gb=256,
            listing_url="https://example.com/unrelated-phone",
            review_status=PhoneListing.ReviewStatus.APPROVED,
        )

        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="clean-card-staff",
            password="test-password",
            is_staff=True,
        )
        self.superuser = user_model.objects.create_superuser(
            username="clean-card-superuser",
            email="superuser@example.com",
            password="test-password",
        )

    def detail_url(self):
        return reverse(
            "clean_opportunity_detail",
            kwargs={"category": "phone", "pk": self.phone.pk},
        )

    def test_card_page_uses_all_clean_snapshot_categories(self):
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "market/clean_card_opportunities.html")
        self.assertContains(response, "iPhone Test")
        self.assertContains(response, "MacBook Test")
        self.assertContains(response, "Steam Deck Test")

    def test_public_card_page_gets_buyer_pricing_but_not_internal_gain(self):
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Buyer offer")
        self.assertContains(response, "Buyer gain")
        self.assertNotContains(response, "Internal gain")
        self.assertFalse(response.context["can_view_internal_gain"])
        self.assertNotIn("my_gain", response.context["rows"][0])
        self.assertIn("buyer_offer", response.context["rows"][0])

    def test_superuser_card_page_gets_internal_gain(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Internal gain")
        self.assertContains(response, "Internal share")
        self.assertTrue(response.context["can_view_internal_gain"])
        self.assertIn("my_gain", response.context["rows"][0])
        self.assertIn("pricing_notes", response.context["rows"][0])

    def test_public_detail_uses_rich_layout_without_internal_algeria_evidence(self):
        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "market/clean_opportunity_detail.html")
        self.assertContains(response, "Buyer Offer")
        self.assertContains(response, "Clean Türkiye iPhone listing")
        self.assertContains(response, "Sealed")
        self.assertNotContains(response, "Raw Market Spread")
        self.assertNotContains(response, "Suggested Deal Split")
        self.assertNotContains(response, "Clean Algeria iPhone listing")
        self.assertNotContains(response, "Algeria Min")
        self.assertNotContains(response, "Gross Margin")
        self.assertNotContains(response, "Unrelated clean phone listing")
        self.assertEqual(response.context["algeria_rows"], [])
        self.assertEqual(len(response.context["turkiye_rows"]), 1)
        self.assertNotIn("algeria_min_eur", response.context["row"])
        self.assertNotIn("gross_margin_eur", response.context["row"])
        self.assertNotIn("item", response.context["row"])

    def test_staff_sees_operational_metadata_but_not_internal_algeria_evidence(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "phone-test-source")
        self.assertContains(response, "Snapshot ID")
        self.assertContains(response, "Auto")
        self.assertContains(response, "parse 88%")
        self.assertNotContains(response, "Approved")
        self.assertNotContains(response, "Clean Algeria iPhone listing")
        self.assertNotContains(response, "Raw Market Spread")
        self.assertNotContains(response, "Suggested Deal Split")
        self.assertTrue(response.context["can_view_operational_meta"])
        self.assertFalse(response.context["can_view_internal_gain"])
        self.assertEqual(response.context["algeria_rows"], [])
        self.assertNotIn("my_gain", response.context["row"])
        self.assertNotIn("algeria_min_eur", response.context["row"])

    def test_superuser_sees_old_style_internal_spread_deal_split_and_algeria_evidence(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Raw Market Spread")
        self.assertContains(response, "Suggested Deal Split")
        self.assertContains(response, "My Gain")
        self.assertContains(response, "of spread")
        self.assertContains(response, "Algeria Min")
        self.assertContains(response, "Clean Algeria iPhone listing")
        self.assertContains(response, "Used A")
        self.assertEqual(len(response.context["algeria_rows"]), 1)
        self.assertIn("my_gain", response.context["row"])
        self.assertIn("pricing_notes", response.context["row"])
        self.assertIn("algeria_min_eur", response.context["row"])

    def test_unknown_category_returns_404(self):
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "legacy", "pk": self.phone.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
