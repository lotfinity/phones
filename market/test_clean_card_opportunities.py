from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot


class CleanCardOpportunityViewTests(TestCase):
    def setUp(self):
        self.phone = PhoneOpportunitySnapshot.objects.create(
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

    def test_card_page_uses_all_clean_snapshot_categories(self):
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "market/clean_card_opportunities.html")
        self.assertContains(response, "iPhone Test")
        self.assertContains(response, "MacBook Test")
        self.assertContains(response, "Steam Deck Test")

    def test_clean_detail_route_is_category_aware(self):
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "market/clean_opportunity_detail.html")
        self.assertContains(response, "iPhone Test")
        self.assertContains(response, "https://example.com/dz-phone")
        self.assertContains(response, "https://example.com/tr-phone")

    def test_unknown_category_returns_404(self):
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "legacy", "pk": self.phone.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
