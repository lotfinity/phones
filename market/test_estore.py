from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
    ConsoleListing,
    ConsoleModel,
    LaptopListing,
    LaptopModel,
    PhoneListing,
    PhoneModel,
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
        LaptopListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            laptop_model=laptop_model,
            title="ROG Zephyrus gerçek ilan",
            price_eur=Decimal("900"),
            condition="used_a_plus",
            cpu="Ryzen 9",
            gpu="RTX 4070",
            ram_gb=32,
            storage_gb=1024,
            review_status="approved",
            observed_at=timezone.now(),
        )
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
        self.assertEqual(response["X-PriceBridge-Frontend"], "preserved-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/smartphones-preview.html",
        )
        self.assertContains(response, "Bagisto Headless")
        self.assertContains(response, "bagisto-opportunity-adapter.js")

    def test_rendered_navigation_does_not_keep_captured_vercel_targets(self):
        response = self.client.get(reverse("estore_bagisto_opportunity_index"))
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
        self.assertContains(response, '"total_count": 3')

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
        response = self.client.get(
            reverse(
                "estore_bagisto_opportunity_detail",
                kwargs={"category": "phone", "pk": self.phone_opportunity.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PriceBridge-Frontend"], "preserved-bagisto-port")
        self.assertEqual(
            response["X-PriceBridge-Bagisto-Source"],
            "pages/products/computer-monitor-preview.html",
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
                self.assertContains(response, title)
                self.assertEqual(
                    response["X-PriceBridge-Bagisto-Source"],
                    "pages/products/computer-monitor-preview.html",
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

    def test_adapter_repurposes_reviews_to_turkiye_comparables(self):
        adapter_js = Path(settings.BASE_DIR, "estoreui/assets/js/bagisto-opportunity-adapter.js").read_text()

        self.assertIn("Türkiye karşılaştırma ilanları", adapter_js)
        self.assertIn("confidenceStars", adapter_js)
        self.assertIn("suppressCapturedCommerceSemantics", adapter_js)

    def test_adapter_suppresses_captured_monitor_detail_copy(self):
        adapter_js = Path(settings.BASE_DIR, "estoreui/assets/js/bagisto-opportunity-adapter.js").read_text()

        self.assertIn("capturedDetailPattern", adapter_js)
        self.assertIn("VisionCraft", adapter_js)
        self.assertIn("suppressCapturedDetailCopy", adapter_js)
        self.assertIn("data-pb-detail-summary", adapter_js)

    def test_unknown_category_returns_404(self):
        response = self.client.get("/estore/opportunity/tablet/1/")
        self.assertEqual(response.status_code, 404)

    def test_storefront_responses_remain_private_and_vary_by_cookie(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
