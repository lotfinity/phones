from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from market.bagisto_source import _captured_destination
from market.clean_models import (
    ConsoleOpportunitySnapshot,
    LaptopOpportunitySnapshot,
    PhoneOpportunitySnapshot,
)
from market.models import (
    Brand,
    Country,
    ConsoleListing,
    ConsoleModel,
    CurrencyRate,
    DealSnapshot,
    LaptopListing,
    LaptopModel,
    MarketListing,
    PhoneListing,
    PhoneModel,
    Source,
    SourceType,
)
from market.views_estore import (
    _acquisition_listing,
    _listing_availability,
    _opportunity_card,
    _supplier_pricing,
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
            algeria_min_eur=Decimal("520"),
            algeria_avg_eur=Decimal("540"),
            turkiye_min_eur=Decimal("700"),
            turkiye_avg_eur=Decimal("760"),
            gross_margin_eur=Decimal("240"),
            margin_percent=Decimal("46.15"),
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
            algeria_min_eur=Decimal("900"),
            algeria_avg_eur=Decimal("920"),
            turkiye_min_eur=Decimal("1200"),
            turkiye_avg_eur=Decimal("1280"),
            gross_margin_eur=Decimal("380"),
            margin_percent=Decimal("42.22"),
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
            algeria_min_eur=Decimal("430"),
            algeria_avg_eur=Decimal("450"),
            turkiye_min_eur=Decimal("600"),
            turkiye_avg_eur=Decimal("650"),
            gross_margin_eur=Decimal("220"),
            margin_percent=Decimal("51.16"),
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
            price_eur=Decimal("520"),
            condition="used_a",
            storage_gb=256,
            battery_health=91,
            review_status="approved",
            listing_url="https://example.com/iphone-algeria",
            image_url="https://example.com/iphone.webp",
            observed_at=timezone.now(),
        )
        cls.phone_opportunity.algeria_listing = cls.phone_listing
        cls.phone_opportunity.save(update_fields=["algeria_listing"])
        PhoneListing.objects.create(
            source_type="sahibinden",
            country="turkiye",
            phone_model=phone_model,
            title="iPhone 15 Pro Türkiye karşılaştırması",
            price_original="34200",
            currency_original="TRY",
            price_eur=Decimal("760"),
            condition="used_a",
            storage_gb=256,
            battery_health=89,
            review_status="approved",
            listing_url="https://example.com/iphone-turkiye",
            observed_at=timezone.now(),
        )
        cls.laptop_listing = LaptopListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            laptop_model=laptop_model,
            title="ROG Zephyrus gerçek ilan",
            price_original="265000",
            currency_original="DZD",
            price_eur=Decimal("900"),
            condition="used_a_plus",
            cpu="Ryzen 9",
            gpu="RTX 4070",
            ram_gb=32,
            storage_gb=1024,
            screen_size=Decimal("16.0"),
            resolution="2560x1600",
            refresh_rate_hz=165,
            panel_type="IPS",
            review_status="approved",
            observed_at=timezone.now(),
        )
        cls.laptop_opportunity.algeria_listing = cls.laptop_listing
        cls.laptop_opportunity.save(update_fields=["algeria_listing"])
        ConsoleListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            console_model=console_model,
            title="Steam Deck OLED gerçek ilan",
            price_eur=Decimal("430"),
            condition="used",
            chipset="AMD Van Gogh",
            ram_gb=16,
            storage_gb=1024,
            review_status="approved",
            observed_at=timezone.now(),
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
            price_eur=Decimal("100"),
            condition="used",
            storage_gb=64,
            review_status="approved",
        )

        instagram_source = Source.objects.create(
            name="Instagram @rd.phone35",
            source_type=SourceType.INSTAGRAM,
            country=Country.ALGERIA,
            username="rd.phone35",
        )
        legacy_listing = MarketListing.objects.create(
            source=instagram_source,
            source_type=SourceType.INSTAGRAM,
            country=Country.ALGERIA,
            title_raw="iPhone 14 Pro Max 128GB RDphone",
            price_original=Decimal("53000"),
            currency_original="DZD",
            price_eur=Decimal("179.66"),
            condition="used",
            storage_gb=128,
            review_status="auto",
            listing_url="https://www.instagram.com/reel/DaYilUguoLq/",
            image_path="media/instagram/rd.phone35/manual_images/DaYilUguoLq.jpg",
            observed_at=timezone.now(),
        )
        cls.legacy_instagram_deal = DealSnapshot.objects.create(
            listing=legacy_listing,
            brand_name="Apple",
            model_name="iPhone 14 Pro Max",
            storage_gb=128,
            title="Apple iPhone 14 Pro Max 128GB",
            price_original=Decimal("53000"),
            currency_original="DZD",
            price_eur=Decimal("179.66"),
            condition="used",
            source_code="IG",
            source_name="Instagram @rd.phone35",
            image_url="/media/instagram/rd.phone35/manual_images/DaYilUguoLq.jpg",
            listing_url="https://www.instagram.com/reel/DaYilUguoLq/",
            observed_at=timezone.now(),
            sah_median=Decimal("14500"),
            sah_median_eur=495.0,
            sah_count=10,
            sah_urls=["https://www.sahibinden.com/iphone-14-pro-max"],
            margin_eur=Decimal("315.34"),
            margin_pct=175.5,
        )

        cls.superuser = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.com",
            password="test-password",
        )

    def test_index_serves_server_rendered_opportunity_template(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "estore/listing_index.html")
        self.assertContains(response, "Tüm fırsatlar")
        self.assertContains(response, 'class="pb-product-grid"')
        self.assertContains(response, 'data-pb-opportunity-card')
        self.assertContains(response, "pricebridge-estore.css")
        self.assertNotContains(response, "Bagisto Headless")
        self.assertNotContains(response, "bagisto-opportunity-adapter.js")

    def test_bagisto_preview_route_stays_available(self):
        response = self.client.get(reverse("estore_bagisto_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "api-driven-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/smartphones-preview.html",
        )
        self.assertContains(response, "Bagisto Headless")
        self.assertContains(response, "pricebridge-opportunities.js")
        self.assertNotContains(response, "bagisto-opportunity-adapter.js")
        self.assertNotContains(response, "pricebridge-opportunity-data")

    def test_new_frontend_index_uses_preserved_bagisto_page(self):
        response = self.client.get(reverse("estore_frontend_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "api-driven-bagisto-port")
        self.assertContains(response, "Bagisto Headless")
        self.assertContains(response, "pricebridge-opportunities.js")
        self.assertContains(response, "/?category=phone")
        self.assertNotContains(response, "pricebridge-opportunity-data")
        self.assertNotContains(response, "bagisto-opportunity-adapter.js")
        self.assertNotContains(response, "/estore/products/")

    def test_legacy_new_frontend_redirects_to_root_frontend(self):
        index_response = self.client.get("/new/")
        detail_response = self.client.get(f"/new/phone/{self.phone_opportunity.pk}/")

        self.assertEqual(index_response.status_code, 302)
        self.assertEqual(index_response["Location"], "/")
        self.assertEqual(detail_response.status_code, 302)
        self.assertEqual(detail_response["Location"], f"/phone/{self.phone_opportunity.pk}/")

    def test_frontend_product_detail_route_uses_api_driven_bagisto_page(self):
        api_url = reverse(
            "estore_api_opportunity_detail",
            kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
        )
        response = self.client.get(
            reverse(
                "estore_frontend_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "api-driven-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/products/speakers-preview.html",
        )
        self.assertContains(response, "window.PriceBridgePage")
        self.assertContains(response, api_url)
        self.assertContains(response, "pricebridge-detail.js")
        self.assertNotContains(response, "pricebridge-opportunity-data")
        self.assertNotContains(response, "bagisto-opportunity-adapter.js")
        self.assertContains(response, "data-pb-detail-spec-table")
        self.assertContains(response, 'tbody class="divide-y divide-neutral-200')
        self.assertContains(response, 'td class="px-4 py-3')
        self.assertContains(response, "Battery Health")
        self.assertContains(response, "91%")
        self.assertContains(response, "Original Price")
        self.assertContains(response, "145000.00 DZD")
        self.assertContains(response, "PriceBridge Offer")
        self.assertContains(response, "Türkiye Average")
        self.assertContains(response, "Türkiye Comparables (1)")
        self.assertContains(response, "data-pb-comparables-panel")
        self.assertContains(response, "iPhone 15 Pro Türkiye karşılaştırması")
        self.assertNotContains(response, "SoundNova")

    def test_frontend_laptop_detail_template_renders_laptop_specs(self):
        response = self.client.get(
            reverse(
                "estore_frontend_opportunity_detail",
                kwargs={"category": "laptop", "pk": self.laptop_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-pb-detail-spec-table")
        self.assertContains(response, "CPU")
        self.assertContains(response, "Ryzen 9")
        self.assertContains(response, "GPU")
        self.assertContains(response, "RTX 4070")
        self.assertContains(response, "Screen Size")
        self.assertContains(response, "16.0&quot;")
        self.assertContains(response, "Panel Type")
        self.assertContains(response, "IPS")

    def test_rendered_navigation_does_not_keep_captured_vercel_targets(self):
        response = self.client.get(reverse("estore_bagisto_opportunity_index"))
        html = response.content.decode("utf-8")

        self.assertNotIn('href="https://bagisto-headless-electronic.vercel.app', html)
        self.assertNotIn("href='https://bagisto-headless-electronic.vercel.app", html)
        self.assertNotIn('href="https://nextjs.bagisto.com', html)
        self.assertNotIn('action="https://bagisto-headless-electronic.vercel.app', html)
        self.assertIn("/?category=phone", html)

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

    def test_index_payload_contains_only_clean_opportunity_categories(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertContains(response, "Valve Steam Deck OLED")
        self.assertNotContains(response, "legacy-")
        self.assertNotContains(response, "https://www.instagram.com/reel/DaYilUguoLq/")
        self.assertContains(response, '"total_count": 3')

    def test_api_index_serves_clean_opportunity_cards_for_frontends(self):
        response = self.client.get(
            reverse("estore_api_opportunity_index"),
            {"currency": "EUR"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["api_version"], "estore-opportunities-v1")
        self.assertEqual(payload["selected_currency"], "EUR")
        self.assertEqual(payload["pagination"]["total"], 3)
        self.assertEqual(payload["counts"], {"phone": 1, "laptop": 1, "console": 1})
        self.assertEqual(len(payload["cards"]), 3)
        self.assertTrue(all(card["api_url"] for card in payload["cards"]))
        self.assertTrue(all(card["frontend_detail_url"] for card in payload["cards"]))
        self.assertIn("/phone/", str(payload))
        self.assertNotIn("/new/phone/", str(payload))
        self.assertFalse(any(str(card["pk"]).startswith("legacy-") for card in payload["cards"]))
        self.assertNotIn(
            "https://www.instagram.com/reel/DaYilUguoLq/",
            str(payload),
        )

    def test_api_index_supports_frontend_filters_and_pagination(self):
        response = self.client.get(
            reverse("estore_api_opportunity_index"),
            {"category": "phone", "brand": "Apple", "q": "15 Pro", "limit": 1, "offset": 0},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["filters"], {"category": "phone", "brand": "Apple", "q": "15 Pro"})
        self.assertEqual(payload["pagination"]["limit"], 1)
        self.assertEqual(payload["pagination"]["offset"], 0)
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(len(payload["cards"]), 1)
        self.assertEqual(payload["cards"][0]["category"], "phone")
        self.assertEqual(payload["cards"][0]["brand"], "Apple")
        self.assertEqual(payload["cards"][0]["source_listing_id"], self.phone_listing.pk)

    def test_api_detail_serves_stable_opportunity_contract(self):
        response = self.client.get(
            reverse(
                "estore_api_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            ),
            {"currency": "EUR"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        opportunity = payload["opportunity"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["api_version"], "estore-opportunities-v1")
        self.assertEqual(payload["selected_currency"], "EUR")
        self.assertEqual(opportunity["category"], "phone")
        self.assertEqual(opportunity["pk"], self.phone_opportunity.pk)
        self.assertEqual(opportunity["source_listing_id"], self.phone_listing.pk)
        self.assertEqual(
            opportunity["frontend_detail_url"],
            reverse(
                "estore_frontend_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            ),
        )
        self.assertEqual(opportunity["battery_health"], 91)
        self.assertIn(str(self.phone_listing.pk), opportunity["image_url"])
        self.assertEqual(payload["evidence"]["algeria"], [])
        self.assertEqual(len(payload["evidence"]["turkiye"]), 1)
        self.assertNotIn("my_gain", opportunity)

    def test_api_detail_includes_phone_detail_specs_table(self):
        response = self.client.get(
            reverse(
                "estore_api_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        specs = {
            row["label"]: row["value"]
            for row in response.json()["opportunity"]["detail_specs"]
        }
        self.assertEqual(specs["Storage"], "256 GB")
        self.assertEqual(specs["RAM"], "—")
        self.assertEqual(specs["SIM Configuration"], "—")
        self.assertEqual(specs["Battery Health"], "91%")
        self.assertEqual(specs["Battery Cycles"], "—")
        self.assertEqual(specs["Box Status"], "—")
        self.assertEqual(specs["Store Warranty"], "—")
        self.assertEqual(specs["Region"], "—")
        self.assertEqual(specs["Color"], "—")
        self.assertEqual(specs["Condition"], "used_a")
        self.assertEqual(specs["Original Price"], "145000.00 DZD")
        self.assertEqual(specs["Price in EUR"], "€520.00")

    def test_api_detail_includes_laptop_detail_specs_table(self):
        response = self.client.get(
            reverse(
                "estore_api_opportunity_detail",
                kwargs={"category": "laptop", "pk": self.laptop_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        specs = {
            row["label"]: row["value"]
            for row in response.json()["opportunity"]["detail_specs"]
        }
        self.assertEqual(specs["CPU"], "Ryzen 9")
        self.assertEqual(specs["GPU"], "RTX 4070")
        self.assertEqual(specs["RAM"], "32 GB")
        self.assertEqual(specs["Storage"], "1024 GB")
        self.assertEqual(specs["Screen Size"], '16.0"')
        self.assertEqual(specs["Resolution"], "2560x1600")
        self.assertEqual(specs["Refresh Rate"], "165 Hz")
        self.assertEqual(specs["Panel Type"], "IPS")
        self.assertEqual(specs["Condition"], "used_a_plus")
        self.assertEqual(specs["Original Price"], "265000.00 DZD")
        self.assertEqual(specs["Price in EUR"], "€900.00")

    def test_superuser_api_detail_includes_internal_algeria_evidence(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse(
                "estore_api_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["evidence"]["algeria"]), 1)
        self.assertIn("my_gain", payload["opportunity"])
        self.assertEqual(
            payload["evidence"]["algeria"][0]["title"],
            "iPhone 15 Pro 256 GB gerçek ilan",
        )

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
        self.assertContains(response, '"query": "Zephyrus"')
        self.assertContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Apple iPhone 15 Pro")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_brand_filter_filters_opportunity_payload_and_exposes_brand_options(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"brand": "Apple"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"active_brand": "Apple"')
        self.assertContains(response, '"brand_options"')
        self.assertContains(response, '"url": "/estore/?brand=Apple"')
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertNotContains(response, "Asus ROG Zephyrus")
        self.assertNotContains(response, "Valve Steam Deck OLED")

    def test_detail_serves_server_rendered_opportunity_template(self):
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "estore/listing_detail.html")
        self.assertContains(response, "Apple iPhone 15 Pro")
        self.assertContains(response, "Önerilen alım fiyatı")
        self.assertContains(response, "Batarya %91")
        self.assertContains(response, "iPhone 15 Pro Türkiye karşılaştırması")
        self.assertNotContains(response, "iPhone 15 Pro 256 GB gerçek ilan")

    def test_bagisto_detail_preview_route_stays_available(self):
        api_url = reverse(
            "estore_api_opportunity_detail",
            kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
        )
        response = self.client.get(
            reverse(
                "estore_bagisto_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "api-driven-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/products/speakers-preview.html",
        )
        self.assertContains(response, "window.PriceBridgePage")
        self.assertContains(response, api_url)
        self.assertContains(response, "pricebridge-detail.js")
        self.assertNotContains(response, "pricebridge-opportunity-data")
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
        self.assertContains(response, "Yalnızca süper kullanıcı")
        self.assertContains(response, "İç kazanç")

    def test_laptop_and_console_details_use_same_preserved_product_layout(self):
        for category, opportunity, title in (
            ("laptop", self.laptop_opportunity, "Asus ROG Zephyrus"),
            ("console", self.console_opportunity, "Valve Steam Deck OLED"),
        ):
            with self.subTest(category=category):
                response = self.client.get(
                    reverse(
                        "estore_bagisto_opportunity_detail",
                        kwargs={"category": category, "pk": opportunity.pk},
                    )
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "pricebridge-detail.js")
                self.assertEqual(
                    response["X-PriceBridge-Bagisto-Source"],
                    "pages/products/speakers-preview.html",
                )

    def test_bundle_source_is_no_longer_used_for_detail_pages(self):
        response = self.client.get(
            reverse(
                "estore_bagisto_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertNotEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/products/smartphone-earphone-bundle-preview.html",
        )
        self.assertNotContains(response, "smartphone-earphone-bundle")

    def test_card_payload_uses_exact_acquisition_listing_fields(self):
        stale_wrong_storage = PhoneListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            phone_model=self.phone_listing.phone_model,
            title="Wrong storage with image",
            price_eur=Decimal("500"),
            condition="used_b",
            storage_gb=128,
            battery_health=80,
            review_status="approved",
            listing_url="https://example.com/wrong-storage",
            image_url="https://example.com/wrong.webp",
            observed_at=timezone.now(),
        )

        selected = _acquisition_listing(self.phone_opportunity, "phone")
        card = _opportunity_card(self.phone_opportunity, "phone", "EUR")

        self.assertEqual(selected.pk, self.phone_listing.pk)
        self.assertNotEqual(selected.pk, stale_wrong_storage.pk)
        self.assertEqual(card["source_listing_id"], self.phone_listing.pk)
        self.assertEqual(card["condition"], "A Kalite")
        self.assertEqual(card["battery_health"], 91)
        self.assertEqual(card["availability_state"], "available")
        self.assertTrue(card["availability_is_actionable"])
        self.assertIn(str(self.phone_listing.pk), card["image_url"])

    def test_confidence_score_exposes_star_data_without_review_semantics(self):
        card = _opportunity_card(self.phone_opportunity, "phone", "EUR")

        self.assertEqual(card["confidence_score"], 88)
        self.assertEqual(card["confidence_stars"], 4)
        self.assertEqual(card["confidence_aria_label"], "Veri güveni 88 / 100")
        self.assertNotIn("review", card)

    def test_supplier_price_discount_only_when_real_supplier_beats_offer(self):
        transient = SimpleNamespace(supplier_eur=Decimal("1050"), buyer_offer_eur=Decimal("900"))
        pricing = _supplier_pricing(transient, "EUR")

        self.assertEqual(pricing["supplier_price"], "1,050.00 EUR")
        self.assertEqual(pricing["supplier_discount_percent"], 14)
        self.assertEqual(pricing["supplier_discount_label"], "%14 daha uygun")

    def test_no_supplier_price_means_no_old_price_or_discount(self):
        pricing = _supplier_pricing(SimpleNamespace(), "EUR")

        self.assertEqual(pricing["supplier_price"], "")
        self.assertIsNone(pricing["supplier_discount_percent"])
        self.assertEqual(pricing["supplier_discount_label"], "")

    def test_non_discount_supplier_price_has_no_discount_badge(self):
        transient = SimpleNamespace(supplier_eur=Decimal("900"), buyer_offer_eur=Decimal("950"))
        pricing = _supplier_pricing(transient, "EUR")

        self.assertEqual(pricing["supplier_price"], "900.00 EUR")
        self.assertIsNone(pricing["supplier_discount_percent"])
        self.assertEqual(pricing["supplier_discount_label"], "")

    def test_listing_availability_rules(self):
        self.phone_listing.observed_at = timezone.now() - timezone.timedelta(days=7)
        self.phone_listing.save(update_fields=["observed_at"])
        self.assertEqual(_listing_availability(self.phone_listing)["state"], "available")

        self.phone_listing.observed_at = timezone.now() - timezone.timedelta(days=8)
        self.phone_listing.save(update_fields=["observed_at"])
        availability = _listing_availability(self.phone_listing)
        self.assertEqual(availability["state"], "stale")
        self.assertFalse(availability["is_actionable"])

        missing = SimpleNamespace(review_status="approved")
        self.assertEqual(_listing_availability(missing)["state"], "verification_required")

    def test_public_payload_does_not_expose_private_algeria_evidence_or_internal_values(self):
        response = self.client.get(
            reverse(
                "estore_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertNotContains(response, "iPhone 15 Pro 256 GB gerçek ilan")
        self.assertNotContains(response, "my_gain")
        self.assertNotContains(response, "pricing_notes")

    def test_unavailable_opportunity_payload_disables_acquisition_actions(self):
        self.phone_listing.observed_at = timezone.now() - timezone.timedelta(days=9)
        self.phone_listing.save(update_fields=["observed_at"])

        card = _opportunity_card(self.phone_opportunity, "phone", "EUR")

        self.assertEqual(card["availability_state"], "stale")
        self.assertFalse(card["availability_is_actionable"])

    def test_plan_script_has_no_quantity_or_checkout_behavior(self):
        plan_js = Path(settings.BASE_DIR, "estoreui/assets/js/pricebridge-plan.js").read_text()

        self.assertIn("pricebridge_acquisition_plan_v1", plan_js)
        self.assertIn("MAX_PHONES = 6", plan_js)
        self.assertNotIn("data-pb-plan-increase", plan_js)
        self.assertNotIn("data-pb-plan-decrease", plan_js)
        self.assertNotIn("checkout", plan_js.lower())
        self.assertNotIn("quantity", plan_js.lower())

    def test_detail_adapter_repurposes_reviews_to_turkiye_comparables(self):
        adapter_js = Path(settings.BASE_DIR, "estoreui/assets/js/pricebridge-detail.js").read_text()

        self.assertIn("Türkiye karşılaştırma ilanları", adapter_js)
        self.assertIn("confidenceStars", adapter_js)
        self.assertIn("suppressCapturedDetailCopy", adapter_js)
        self.assertIn("rewriteComparableReviewsTab", adapter_js)
        self.assertIn("data-pb-comparables-panel", adapter_js)
        self.assertIn("Türkiye Comparables", adapter_js)

    def test_detail_adapter_suppresses_captured_product_detail_copy(self):
        adapter_js = Path(settings.BASE_DIR, "estoreui/assets/js/pricebridge-detail.js").read_text()

        self.assertIn("capturedDetailPattern", adapter_js)
        self.assertIn("VisionCraft", adapter_js)
        self.assertIn("suppressCapturedDetailCopy", adapter_js)
        self.assertIn("data-pb-detail-summary", adapter_js)
        self.assertIn("repurposeCapturedProductBlocks", adapter_js)
        self.assertIn("rewriteAttributesTable", adapter_js)
        self.assertIn("px-4 py-3", adapter_js)
        self.assertIn("divide-y divide-neutral-200", adapter_js)
        self.assertIn("detailSpecRows", adapter_js)
        self.assertIn("opportunity.detail_specs", adapter_js)
        self.assertIn("rewriteProductDescription", adapter_js)
        self.assertIn("data-pb-product-description", adapter_js)
        self.assertIn("Deal Math", adapter_js)
        self.assertIn("Türkiye piyasa değeri", adapter_js)

    def test_bridge_css_pins_captured_mobile_nav_to_bottom(self):
        bridge_css = Path(settings.BASE_DIR, "estoreui/assets/css/bagisto-django-bridge.css").read_text()
        shell_js = Path(settings.BASE_DIR, "estoreui/assets/js/pricebridge-shell.js").read_text()

        self.assertIn("header .fixed.inset-x-0.bottom-0.z-\\[60\\].lg\\:hidden", bridge_css)
        self.assertIn('[data-pb-mobile-bottom-nav="1"]', bridge_css)
        self.assertIn("top: auto !important", bridge_css)
        self.assertIn("bottom: env(safe-area-inset-bottom, 0) !important", bridge_css)
        self.assertIn("document.body.appendChild(shell)", shell_js)

    def test_unknown_category_returns_404(self):
        response = self.client.get("/estore/opportunity/tablet/1/")
        self.assertEqual(response.status_code, 404)

    def test_storefront_responses_remain_private_and_vary_by_cookie(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])


class EstoreFxApiTests(TestCase):
    def test_fx_rates_api_returns_rates_used_by_estore(self):
        observed_at = timezone.now()
        CurrencyRate.objects.create(
            base_currency="EUR",
            quote_currency="TRY",
            rate=Decimal("45.000000"),
            source="test",
            observed_at=observed_at,
        )
        CurrencyRate.objects.create(
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("1.100000"),
            source="test",
            observed_at=observed_at,
        )
        CurrencyRate.objects.create(
            base_currency="USD",
            quote_currency="TRY",
            rate=Decimal("40.909091"),
            source="test:derived",
            observed_at=observed_at,
        )
        CurrencyRate.objects.create(
            base_currency="EUR",
            quote_currency="DZD",
            rate=Decimal("295.000000"),
            source="manual:black_market",
            observed_at=observed_at,
        )

        response = self.client.get(reverse("estore_api_fx_rates"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rates"]["TRY"], "45.000000")
        self.assertEqual(payload["rates"]["DZD"], "295.000000")
        self.assertEqual(
            [pair["pair"] for pair in payload["pairs"]],
            ["EUR/TRY", "USD/TRY", "EUR/DZD", "EUR/USD"],
        )

    @patch("market.views_estore.call_command")
    def test_fx_refresh_api_runs_fetch_and_clean_recomputes(self, call_command_mock):
        response = self.client.post(reverse("estore_api_fx_refresh"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["refreshed"])
        self.assertEqual(
            [call.args[0] for call in call_command_mock.call_args_list],
            [
                "fetch_exchange_rates",
                "recompute_phone_opportunities_v2",
                "recompute_laptop_opportunities_v2",
                "recompute_console_opportunities_v1",
            ],
        )
        self.assertIn("--dzd-per-eur-black", call_command_mock.call_args_list[0].args)
        self.assertIn("295", call_command_mock.call_args_list[0].args)
