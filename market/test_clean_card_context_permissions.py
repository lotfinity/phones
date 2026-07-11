from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from market.clean_models import PhoneOpportunitySnapshot


class CleanCardContextPermissionTests(TestCase):
    def setUp(self):
        self.snapshot = PhoneOpportunitySnapshot.objects.create(
            brand="Samsung",
            model="Permission Test",
            storage_gb=256,
            algeria_min_eur=Decimal("500.00"),
            algeria_avg_eur=Decimal("520.00"),
            turkiye_min_eur=Decimal("700.00"),
            turkiye_avg_eur=Decimal("750.00"),
            gross_margin_eur=Decimal("250.00"),
            margin_percent=Decimal("50.00"),
            recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
            confidence_score=90,
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="card-context-superuser",
            email="card-context@example.com",
            password="test-password",
        )

    def test_public_context_has_placeholders_not_raw_gross_values(self):
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        row = response.context["rows"][0]
        self.assertEqual(row["gross_margin"], "-")
        self.assertNotIn("gross_margin_eur", row)
        self.assertNotIn("item", row)
        self.assertEqual(response.context["total_gross"], "-")
        self.assertEqual(response.context["avg_margin"], "-")

    def test_superuser_context_keeps_full_gross_values(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("ui_preview_card_opportunities"))

        self.assertEqual(response.status_code, 200)
        row = response.context["rows"][0]
        self.assertNotEqual(row["gross_margin"], "-")
        self.assertEqual(row["gross_margin_eur"], Decimal("250.00"))
        self.assertIn("item", row)
        self.assertNotEqual(response.context["total_gross"], "-")
