from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from market.clean_models import PhoneOpportunitySnapshot
from market.models import Brand, Condition, Country, PhoneListing, PhoneModel, SourceType


class CleanCardCacheIsolationTests(TestCase):
    def setUp(self):
        self.snapshot = PhoneOpportunitySnapshot.objects.create(
            brand="Apple",
            model="Cache Test Phone",
            storage_gb=256,
            algeria_min_eur=Decimal("500.00"),
            turkiye_avg_eur=Decimal("750.00"),
            gross_margin_eur=Decimal("250.00"),
            margin_percent=Decimal("50.00"),
            recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
            confidence_score=90,
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="cache-superuser",
            email="cache@example.com",
            password="test-password",
        )

    def assert_private_no_store(self, response, viewer):
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", cache_control)
        self.assertIn("max-age=0", cache_control)
        self.assertIn("Cookie", response.headers.get("Vary", ""))
        self.assertEqual(response.headers.get("CDN-Cache-Control"), "no-store")
        self.assertEqual(response.headers.get("Cloudflare-CDN-Cache-Control"), "no-store")
        self.assertEqual(response.headers.get("Surrogate-Control"), "no-store")
        self.assertEqual(response.headers.get("X-PriceBridge-Viewer"), viewer)

    def test_public_and_superuser_card_responses_are_never_share_cacheable(self):
        public_response = self.client.get(reverse("ui_preview_card_opportunities"))
        self.assertEqual(public_response.status_code, 200)
        self.assert_private_no_store(public_response, "public")
        self.assertNotContains(public_response, "superuser pricing")

        self.client.force_login(self.superuser)
        private_response = self.client.get(reverse("ui_preview_card_opportunities"))
        self.assertEqual(private_response.status_code, 200)
        self.assert_private_no_store(private_response, "superuser")
        self.assertContains(private_response, "superuser pricing")

    def test_clean_detail_response_is_also_private_no_store(self):
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "phone", "pk": self.snapshot.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assert_private_no_store(response, "public")


class CleanListingImageProxyTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name="Apple")
        model = PhoneModel.objects.create(brand=brand, canonical_name="Image Test Phone")
        self.listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=model,
            title="Image proxy listing",
            price_original=Decimal("40000.00"),
            currency_original="TRY",
            price_eur=Decimal("750.00"),
            condition=Condition.SEALED,
            storage_gb=256,
            listing_url="https://example.com/listing",
            image_url="https://images.example.com/photo.webp",
            review_status=PhoneListing.ReviewStatus.APPROVED,
        )

    @patch("market.views_images._download_image")
    def test_proxy_returns_same_origin_cacheable_raster_image(self, download_image):
        download_image.return_value = (b"fake-webp-bytes", "image/webp")
        response = self.client.get(
            reverse(
                "clean_listing_image",
                kwargs={"category": "phone", "pk": self.listing.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/webp")
        self.assertEqual(response.content, b"fake-webp-bytes")
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=21600")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        download_image.assert_called_once_with(
            "https://images.example.com/photo.webp",
            referer="https://example.com/",
        )

    def test_proxy_rejects_unknown_category(self):
        response = self.client.get(
            reverse(
                "clean_listing_image",
                kwargs={"category": "legacy", "pk": self.listing.pk},
            )
        )
        self.assertEqual(response.status_code, 404)
