from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from market.bagisto_source import _captured_destination
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


class EstoreBagistoOpportunityViewsTests(TestCase):
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

    def test_index_serves_preserved_bagisto_smartphones_page(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "preserved-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/smartphones-preview.html",
        )
        self.assertContains(response, 'name="pricebridge-bagisto-source"')
        self.assertContains(response, 'name="pricebridge-frontend"')
        self.assertContains(response, "pages/smartphones-preview.html")
        self.assertContains(response, "Bagisto Headless")
        self.assertContains(response, "bagisto-opportunity-adapter.js")
        self.assertContains(response, "bagisto-django-bridge.css")

    def test_rendered_navigation_does_not_keep_captured_vercel_targets(self):
        response = self.client.get(reverse("estore_opportunity_index"))
        html = response.content.decode("utf-8")

        self.assertNotIn('href="https://bagisto-headless-electronic.vercel.app', html)
        self.assertNotIn("href='https://bagisto-headless-electronic.vercel.app", html)
        self.assertNotIn('href="https://nextjs.bagisto.com', html)
        self.assertNotIn('action="https://bagisto-headless-electronic.vercel.app', html)
        self.assertIn("/estore/?category=phone", html)

    def test_captured_destination_maps_navigation_and_product_markers(self):
        self.assertEqual(
            _captured_destination("https://bagisto-headless-electronic.vercel.app/smartphones"),
            "/estore/?category=phone",
        )
        self.assertEqual(
            _captured_destination("https://bagisto-headless-electronic.vercel.app/laptops"),
            "/estore/?category=laptop",
        )
        self.assertEqual(
            _captured_destination("https://bagisto-headless-electronic.vercel.app/gaming-consoles"),
            "/estore/?category=console",
        )
        self.assertEqual(
            _captured_destination("https://bagisto-headless-electronic.vercel.app/product/example"),
            "#pb-product",
        )
        self.assertEqual(
            _captured_destination(
                "https://bagisto-headless-electronic.vercel.app/search",
                for_form=True,
            ),
            "/estore/",
        )

    def test_index_payload_contains_all_opportunity_categories(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertContains(response, "Valve Steam Deck OLED")
        self.assertContains(response, '"total_count":3')

    def test_raw_listing_without_snapshot_is_not_in_payload(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertNotContains(response, self.unmatched_listing.title)

    def test_category_filter_filters_opportunity_payload(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"category": "phone"},
        )

        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertNotContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_search_filters_opportunity_payload(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"q": "Zephyrus"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"query":"Zephyrus"')
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Apple iPhone 15 Pro")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_detail_serves_preserved_bagisto_product_page(self):
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "preserved-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/products/smartphone-earphone-bundle-preview.html",
        )
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, '"buyer_offer"')
        self.assertContains(response, '"buyer_gain"')
        self.assertContains(response, "Batarya sağlığı")
        self.assertContains(response, "iPhone 15 Pro Türkiye karşılaştırması")
        self.assertNotContains(response, "iPhone 15 Pro 256 GB gerçek ilan")

    def test_superuser_detail_includes_algeria_evidence_and_internal_values(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertContains(response, "iPhone 15 Pro 256 GB gerçek ilan")
        self.assertContains(response, '"can_view_internal_gain":true')
        self.assertContains(response, '"my_gain"')

    def test_laptop_and_console_details_use_same_preserved_product_layout(self):
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
                self.assertEqual(
                    response["X-PriceBridge-Bagisto-Source"],
                    "pages/products/smartphone-earphone-bundle-preview.html",
                )

    def test_unknown_category_returns_404(self):
        response = self.client.get("/estore/opportunity/tablet/1/")
        self.assertEqual(response.status_code, 404)

    def test_storefront_responses_remain_private_and_vary_by_cookie(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
