from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from market.clean_models import (
    ConsoleOpportunitySnapshot,
    LaptopOpportunitySnapshot,
    PhoneOpportunitySnapshot,
)
from market.models import (
    Brand,
    ConsoleListing,
    ConsoleModel,
    LaptopListing,
    LaptopModel,
    PhoneListing,
    PhoneModel,
)


class EstoreOpportunityViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apple = Brand.objects.create(name="Apple")
        asus = Brand.objects.create(name="Asus")
        valve = Brand.objects.create(name="Valve")

        phone_model = PhoneModel.objects.create(
            brand=apple,
            canonical_name="iPhone 15 Pro",
        )
        laptop_model = LaptopModel.objects.create(
            brand=asus,
            canonical_name="ROG Zephyrus",
        )
        console_model = ConsoleModel.objects.create(
            brand=valve,
            canonical_name="Steam Deck OLED",
        )

        cls.phone_opportunity = PhoneOpportunitySnapshot.objects.create(
            phone_model=phone_model,
            brand="Apple",
            model="iPhone 15 Pro",
            storage_gb=256,
            algeria_min_eur="520",
            algeria_avg_eur="540",
            turkiye_min_eur="700",
            turkiye_avg_eur="760",
            gross_margin_eur="240",
            margin_percent="46.15",
            algeria_count=2,
            turkiye_count=4,
            recommendation="buy",
            confidence_score=88,
        )
        cls.laptop_opportunity = LaptopOpportunitySnapshot.objects.create(
            laptop_model=laptop_model,
            brand="Asus",
            model="ROG Zephyrus",
            cpu="Ryzen 9",
            gpu="RTX 4070",
            ram_gb=32,
            storage_gb=1024,
            algeria_min_eur="900",
            algeria_avg_eur="920",
            turkiye_min_eur="1200",
            turkiye_avg_eur="1280",
            gross_margin_eur="380",
            margin_percent="42.22",
            algeria_count=1,
            turkiye_count=3,
            recommendation="good_opportunity",
            confidence_score=82,
        )
        cls.console_opportunity = ConsoleOpportunitySnapshot.objects.create(
            console_model=console_model,
            brand="Valve",
            model="Steam Deck OLED",
            chipset="AMD Van Gogh",
            ram_gb=16,
            storage_gb=1024,
            algeria_min_eur="430",
            algeria_avg_eur="450",
            turkiye_min_eur="600",
            turkiye_avg_eur="650",
            gross_margin_eur="220",
            margin_percent="51.16",
            algeria_count=1,
            turkiye_count=2,
            recommendation="buy",
            confidence_score=79,
        )

        cls.phone_listing = PhoneListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            phone_model=phone_model,
            title="iPhone 15 Pro 256 GB gerçek ilan",
            price_original="145000",
            currency_original="DZD",
            price_eur="520",
            condition="used_a",
            storage_gb=256,
            battery_health=91,
            review_status="approved",
            listing_url="https://example.com/iphone-algeria",
            image_url="https://example.com/iphone.webp",
        )
        PhoneListing.objects.create(
            source_type="sahibinden",
            country="turkiye",
            phone_model=phone_model,
            title="iPhone 15 Pro Türkiye karşılaştırması",
            price_original="34200",
            currency_original="TRY",
            price_eur="760",
            condition="used_a",
            storage_gb=256,
            battery_health=89,
            review_status="approved",
            listing_url="https://example.com/iphone-turkiye",
        )
        LaptopListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            laptop_model=laptop_model,
            title="ROG Zephyrus gerçek ilan",
            price_eur="900",
            condition="used_a_plus",
            cpu="Ryzen 9",
            gpu="RTX 4070",
            ram_gb=32,
            storage_gb=1024,
            review_status="approved",
        )
        ConsoleListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            console_model=console_model,
            title="Steam Deck OLED gerçek ilan",
            price_eur="430",
            condition="used",
            chipset="AMD Van Gogh",
            ram_gb=16,
            storage_gb=1024,
            review_status="approved",
        )

        other_model = PhoneModel.objects.create(
            brand=apple,
            canonical_name="Unmatched Device",
        )
        cls.unmatched_listing = PhoneListing.objects.create(
            source_type="manual",
            country="other",
            phone_model=other_model,
            title="THIS RAW LISTING MUST NOT BE A CATALOG CARD",
            price_eur="100",
            condition="used",
            storage_gb=64,
            review_status="approved",
        )

        cls.superuser = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.com",
            password="test-password",
        )

    def test_estore_index_contains_all_opportunity_categories(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertContains(response, "Valve Steam Deck OLED")
        self.assertEqual(response.context["total_count"], 3)
        self.assertContains(response, "fırsat gösteriliyor")

    def test_raw_listing_without_opportunity_is_not_a_catalog_card(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.unmatched_listing.title)

    def test_category_filter_filters_opportunities(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"category": "phone"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertNotContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_search_filters_opportunities(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"q": "Zephyrus"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_phone_opportunity_detail_renders_pricing_status_and_proxy_image(self):
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, "Önerilen alım fiyatı")
        self.assertContains(response, "Tahmini mağaza kazancı")
        self.assertContains(response, "Batarya sağlığı")
        self.assertContains(response, "91%")
        self.assertContains(
            response,
            reverse(
                "clean_listing_image",
                kwargs={"category": "phone", "pk": self.phone_listing.pk},
            ),
        )
        self.assertContains(response, "iPhone 15 Pro Türkiye karşılaştırması")
        self.assertNotContains(response, "iPhone 15 Pro 256 GB gerçek ilan")

    def test_superuser_can_see_algeria_evidence_and_internal_gain(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cezayir alım kanıtları")
        self.assertContains(response, "iPhone 15 Pro 256 GB gerçek ilan")
        self.assertContains(response, "İç kazanç")

    def test_laptop_and_console_opportunity_details_render(self):
        for category, opportunity, title in (
            ("laptop", self.laptop_opportunity, "Asus ROG Zephyrus"),
            ("console", self.console_opportunity, "Valve Steam Deck OLED"),
        ):
            with self.subTest(category=category):
                response = self.client.get(
                    reverse(
                        "estore_opportunity_detail",
                        kwargs={"category": category, "pk": opportunity.pk},
                    )
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)

    def test_unknown_opportunity_category_returns_404(self):
        response = self.client.get("/estore/opportunity/tablet/1/")
        self.assertEqual(response.status_code, 404)

    def test_storefront_responses_are_private_and_vary_by_cookie(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
