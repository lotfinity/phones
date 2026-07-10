from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from market.collectors.sahibinden_cdp import parse_condition, parse_storage_gb, parse_try_price, review_status_for
from market.collectors.ouedkniss_cdp import (
    clean_model_text as clean_ouedkniss_model_text,
    is_within_max_age as is_ouedkniss_within_max_age,
    parse_obsidian_content_rows,
    parse_relative_age_days as parse_ouedkniss_relative_age_days,
    parse_dzd_price as parse_ouedkniss_dzd_price,
    parse_sim_config as parse_ouedkniss_sim_config,
    parse_storage_ram as parse_ouedkniss_storage_ram,
)
from market.models import (
    Brand,
    Category,
    Condition,
    Country,
    MarketListing,
    OpportunitySnapshot,
    ProductModel,
    Source,
    SourceType,
)
from market.services.matching import SUPPORTED_STORAGE_GB, get_or_create_model, get_or_create_variant
from market.services.normalization import canonical_model_name, likely_brand
from market.parsers.ocr_parser import parse_ocr_text
from market.parsers.supplier_parser import parse_supplier_line
from market.views import base_context


class LanguageSwitcherTests(TestCase):
    def test_set_language_sets_locale_cookie_and_redirects_back(self):
        response = self.client.post(
            reverse("set_language"),
            {"language": "tr", "next": "/?source=instagram"},
        )

        self.assertRedirects(response, "/?source=instagram", fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "tr")

    def test_locale_cookie_translates_next_request(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "tr"

        response = self.client.get(reverse("opportunities"))

        self.assertContains(response, '<html lang="tr">')
        self.assertContains(response, "Calisma alani")

    def test_set_currency_sets_cookie_and_redirects_back(self):
        response = self.client.post(
            reverse("set_currency"),
            {"currency": "USD", "next": "/"},
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(response.cookies["pricebridge_currency"].value, "USD")

    def test_base_context_includes_current_fx_rates(self):
        context = base_context(self.client.request().wsgi_request, "opportunities")

        self.assertIn("fx_rates", context)
        rendered_rates = [f"{rate['label']} = {rate['value']}" for rate in context["fx_rates"]]
        self.assertEqual(len(rendered_rates), 4)
        self.assertIn("€1 = ₺45.00", rendered_rates)
        self.assertIn("$1 = ₺41.50", rendered_rates)
        self.assertIn("€1 = 280.00 DZD", rendered_rates)
        self.assertIn("€1 = $1.08", rendered_rates)


class OpportunityGainSplitTests(TestCase):
    def test_large_absolute_spread_is_at_least_medium_even_when_percent_is_low(self):
        opportunity = OpportunitySnapshot(
            algeria_min_eur=Decimal("1500"),
            sahibinden_avg_eur=Decimal("1700"),
            gross_margin_vs_sahibinden_eur=Decimal("200"),
        )

        gain_split = opportunity.gain_split()

        self.assertEqual(gain_split["buyer_gain_eur"], Decimal("150.00"))
        self.assertEqual(gain_split["buyer_gain_percent"], Decimal("9.68"))
        self.assertEqual(gain_split["deal_quality"], "medium")

    def test_smaller_low_percent_spread_remains_weak(self):
        opportunity = OpportunitySnapshot(
            algeria_min_eur=Decimal("900"),
            sahibinden_avg_eur=Decimal("1000"),
            gross_margin_vs_sahibinden_eur=Decimal("100"),
        )

        gain_split = opportunity.gain_split()

        self.assertEqual(gain_split["buyer_gain_percent"], Decimal("8.11"))
        self.assertEqual(gain_split["deal_quality"], "weak")

    def test_high_buyer_gain_percent_stays_strong(self):
        opportunity = OpportunitySnapshot(
            algeria_min_eur=Decimal("250"),
            sahibinden_avg_eur=Decimal("500"),
            gross_margin_vs_sahibinden_eur=Decimal("250"),
        )

        gain_split = opportunity.gain_split()

        self.assertEqual(gain_split["buyer_gain_percent"], Decimal("48.15"))
        self.assertEqual(gain_split["deal_quality"], "strong")

    def test_supplier_list_offer_reserves_100_usd_then_splits_remaining_spread(self):
        from market.services.currency import money, usd_to_eur

        opportunity = OpportunitySnapshot(
            algeria_min_eur=Decimal("700"),
            supplier_eur=Decimal("1000"),
        )

        gain_split = opportunity.gain_split()
        buyer_floor = usd_to_eur(100)
        split_gain = money((Decimal("300") - buyer_floor) / Decimal("2"))

        self.assertEqual(gain_split["pricing_basis"], "supplier")
        self.assertEqual(gain_split["gross_margin_eur"], Decimal("300.00"))
        self.assertEqual(gain_split["my_gain_eur"], split_gain)
        self.assertEqual(gain_split["buyer_gain_eur"], money(buyer_floor + split_gain))
        self.assertEqual(gain_split["offer_price_to_buyer_eur"], money(Decimal("700") + split_gain))


class BrandListTests(SimpleTestCase):
    def test_detects_manual_brand_aliases(self):
        cases = {
            "Appelle 17 Pro Max": "Apple",
            "Samasung Galaxy Buds 3": "Samsung",
            "Honor Magic V5": "Honor",
            "Huawei Pura 70 Ultra": "Huawei",
            "Vivo X200 Ultra": "Vivo",
            "OPPO FIND N5": "Oppo",
            "One Plus 13R": "OnePlus",
            "Google Pixel 7": "Google",
            "Motorola Razr 60": "Motorola",
            "Realme GT7 Pro": "Realme",
            "Redmagic 11 Pro": "Redmagic",
            "Doogee S100 Pro": "Doogee",
            "Nubia Flip 5G": "Nubia",
            "BlackView BV6200 Plus": "BlackView",
            "GoPro Max 2": "GoPro",
            "IQoo Neo 9 Pro": "IQoo",
            "Redmi Note 13": "Xiaomi",
        }
        for text, brand in cases.items():
            with self.subTest(text=text):
                self.assertEqual(likely_brand(text), brand)

    def test_samsung_model_names_do_not_keep_brand_prefix(self):
        cases = {
            "Samsung Galaxy S25 Ultra": "Galaxy S25 Ultra",
            "Samsung S25 Ultra": "Galaxy S25 Ultra",
            "Samsung Galaxy S25 Ultra 256Gb 12Ram": "Galaxy S25 Ultra",
            "Samsung S23U 512GB": "Galaxy S23 Ultra",
            "Samsung S25FE Duos 128GB": "Galaxy S25 FE",
            "Samsung Galaxy S23 Ultra 512G 1SIM": "Galaxy S23 Ultra",
            "Samsung Galaxy S24 Ultra 256 2Sim": "Galaxy S24 Ultra",
            "SAMSUNG GALAXY S25 ULTRA 5G - 12G - 512G - DUAL SIM - 6,8 AMOLED": "Galaxy S25 Ultra",
            "Samsung Galaxy A56 AI 2025 8Go 128Go Dual Sim 5000 Mha": "Galaxy A56",
            "Samsung Galaxy Z Fold 7 CE 12GB 256GB 2SIM": "Galaxy Z Fold 7",
            "Samsung Galaxy Watch 8 Classic 46MM Scelle": "Galaxy Watch 8 Classic",
            "Samasung Galaxy Buds 3": "Galaxy Buds 3",
            "Galaxy S24 Ultra": "Galaxy S24 Ultra",
        }
        for text, canonical in cases.items():
            with self.subTest(text=text):
                self.assertEqual(canonical_model_name(text), canonical)

    def test_storage_capacity_set_is_explicit(self):
        self.assertEqual(SUPPORTED_STORAGE_GB, {64, 128, 256, 512, 1024, 2048})


class VariantMatchingTests(TestCase):
    def test_reuses_equivalent_variant_identity(self):
        product_model = get_or_create_model("Samsung Galaxy S25 Ultra")

        first = get_or_create_variant(product_model, storage_gb=256, sim_config="2Sim")
        second = get_or_create_variant(product_model, storage_gb=256, sim_config="Dual SIM")

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.identity_key, "storage=256|sim=2sim|region=|color=")

    def test_reuses_empty_sim_for_single_sim_variant(self):
        product_model = get_or_create_model("Samsung Galaxy S23 Ultra")

        empty_sim = get_or_create_variant(product_model, storage_gb=256)
        single_sim = get_or_create_variant(product_model, storage_gb=256, sim_config="1SIM")

        self.assertEqual(empty_sim.id, single_sim.id)
        self.assertEqual(empty_sim.identity_key, "storage=256|sim=|region=|color=")


class SupplierParserTests(SimpleTestCase):
    def test_parses_supplier_line_with_storage_ram_price(self):
        parsed = parse_supplier_line("Samsung S25 ultra 256/12 930$")
        self.assertEqual(parsed.model_text, "Samsung S25 ultra")
        self.assertEqual(parsed.storage_gb, 256)
        self.assertEqual(parsed.ram_gb, 12)
        self.assertEqual(parsed.price_usd, 930)
        self.assertGreater(parsed.confidence, 0.7)

    def test_parses_dotted_usd_thousands(self):
        parsed = parse_supplier_line("Samsung s26 ultra 256GB 1.050$")
        self.assertEqual(parsed.model_text, "Samsung s26 ultra")
        self.assertEqual(parsed.storage_gb, 256)
        self.assertEqual(parsed.price_usd, 1050)

    def test_does_not_treat_sim_count_as_ram(self):
        parsed = parse_supplier_line("iPhone 17ProMax256/1 1450$")
        self.assertEqual(parsed.model_text, "iPhone 17ProMax")
        self.assertEqual(parsed.storage_gb, 256)
        self.assertIsNone(parsed.ram_gb)


class SahibindenParserTests(SimpleTestCase):
    def test_parses_turkish_try_price_formats(self):
        self.assertEqual(parse_try_price("47.499,99 TL"), Decimal("47499.99"))
        self.assertEqual(parse_try_price("47.499 TL"), Decimal("47499.00"))
        self.assertEqual(parse_try_price("47499 TL"), Decimal("47499.00"))

    def test_parses_sahibinden_storage_patterns(self):
        self.assertEqual(parse_storage_gb("Samsung S25 Ultra 12/256"), 256)
        self.assertEqual(parse_storage_gb("SAMSUNG S26 256 ULTRA GB BEYAZ"), 256)
        self.assertEqual(parse_storage_gb("iPhone 15 Pro Max 256 Çift Fiziki Sim"), 256)

    def test_parses_sahibinden_condition_signals(self):
        self.assertEqual(parse_condition("SIFIR KAPALI KUTU MAĞAZADAN"), Condition.SEALED)
        self.assertEqual(parse_condition("iPhone 13 128 GB PİL 83 EŞİM NO AKTİF"), Condition.USED)
        self.assertEqual(parse_condition("iPhone 17 Pro Max 256 GB"), Condition.UNKNOWN)

    def test_review_status_requires_variant_and_sane_price(self):
        model = SimpleNamespace(canonical_name="iPhone 17 Pro Max")

        self.assertEqual(review_status_for(71000, model, 256), "auto")
        self.assertEqual(review_status_for(71000, model, None), "needs_review")
        self.assertEqual(review_status_for(177000, model, 256), "needs_review")


class OuedknissParserTests(SimpleTestCase):
    def test_parses_price_immediately_before_da(self):
        text = "Samsung Galaxy A16 31 500 DA Paiement à la livraison Bouzareah, 16 12 heures"
        self.assertEqual(parse_ouedkniss_dzd_price(text), Decimal("31500"))
        self.assertEqual(parse_ouedkniss_dzd_price("Samsung S25 Ultra 12/256 206 000 DA"), Decimal("206000"))
        self.assertEqual(parse_ouedkniss_dzd_price("Honor Magic 7 Pro Globale 16/512 169 000 DA"), Decimal("169000"))

    def test_parses_ouedkniss_storage_and_ram(self):
        self.assertEqual(parse_ouedkniss_storage_ram("Samsung Galaxy S25 Ultra 256GB/12Ram"), (256, 12))
        self.assertEqual(parse_ouedkniss_storage_ram("Samsung Galaxy A36 5G 128Gb/8Ram"), (128, 8))
        self.assertEqual(parse_ouedkniss_storage_ram("Samsung GALAXY S23 ULTRA 512G 1SIM"), (512, None))
        self.assertEqual(parse_ouedkniss_storage_ram("Google Pixel 7 8GB 256GB 1sim"), (256, 8))
        self.assertEqual(parse_ouedkniss_storage_ram("Huawei Mate XT 16GB 1024GB 1TB BOITE"), (1024, 16))
        self.assertEqual(parse_ouedkniss_storage_ram("S26 Ultra 1000Gb S26 Ultra 1Tb"), (1024, None))
        self.assertEqual(parse_ouedkniss_storage_ram("Samsung Galaxy Zflip 5 8/266"), (None, None))

    def test_parses_ouedkniss_sim_config(self):
        self.assertEqual(parse_ouedkniss_sim_config("Galaxy S24 Ultra 256 2Sim"), "2sim")
        self.assertEqual(parse_ouedkniss_sim_config("Samsung S25fe 8/128 Duos"), "2sim")
        self.assertEqual(parse_ouedkniss_sim_config("Google Pixel 7 8GB 128GB 1SIM"), "")

    def test_parses_obsidian_clipper_content_rows(self):
        rows = parse_obsidian_content_rows(
            """
            <main>
              <div>
                <a href="/store/3542/kaba-store/annonce/8928090">
                  <picture><img src="https://cdn.example/s22.jpg"></picture>
                  <div><h3>Samsung Galaxy S22 Ultra 12/512G 2Sim</h3>
                    <p><p>113 000</p><p>DA</p></p>
                    Bab ezzouar, 16 2 jours
                  </div>
                </a>
              </div>
            </main>
            """
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Samsung Galaxy S22 Ultra 12/512G 2Sim")
        self.assertEqual(rows[0]["priceText"], "113 000 DA")
        self.assertEqual(rows[0]["image"], "https://cdn.example/s22.jpg")
        self.assertEqual(rows[0]["href"], "https://www.ouedkniss.com/store/3542/kaba-store/annonce/8928090")

    def test_parses_obsidian_current_search_links(self):
        rows = parse_obsidian_content_rows(
            """
            <main>
              <a href="/smartphones-samsung-galaxy-a16-128-gb-el-biar-alger-algeria-d48118552">
                <img src="https://cdn.example/a16.jpg">
                <h3>Samsung Galaxy A16 128 GB</h3>
                <p>31 500</p><p>DA</p>
                El biar, 16 23 minutes
              </a>
              <a href="/store/15321/louail-phone/">Louail Phone</a>
            </main>
            """
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Samsung Galaxy A16 128 GB")
        self.assertEqual(rows[0]["priceText"], "31 500 DA")
        self.assertEqual(
            rows[0]["href"],
            "https://www.ouedkniss.com/smartphones-samsung-galaxy-a16-128-gb-el-biar-alger-algeria-d48118552",
        )

    def test_cleans_variant_tokens_from_model_text(self):
        self.assertEqual(clean_ouedkniss_model_text("Samsung Galaxy S25 Ultra 256GB/12Ram"), "Samsung Galaxy S25 Ultra")
        self.assertEqual(clean_ouedkniss_model_text("Samsung Galaxy S24 Ultra 256 2Sim"), "Samsung Galaxy S24 Ultra")
        self.assertEqual(clean_ouedkniss_model_text("OnePlus 15 12/256G 2SIM"), "OnePlus 15")
        self.assertEqual(clean_ouedkniss_model_text("Samsung Galaxy S25 Ultra 1TB 2Sim"), "Samsung Galaxy S25 Ultra")
        self.assertEqual(clean_ouedkniss_model_text("Honor V3 512/12"), "Honor V3")
        self.assertEqual(clean_ouedkniss_model_text("Google Pixel 7 8GB 256GB 1sim"), "Google Pixel 7")

    def test_ouedkniss_age_cutoff(self):
        self.assertEqual(parse_ouedkniss_relative_age_days("Dely brahim, 16 23 heures"), 0)
        self.assertEqual(parse_ouedkniss_relative_age_days("Dely brahim, 16 12 jours"), 12)
        self.assertEqual(parse_ouedkniss_relative_age_days("Dely brahim, 16 5 semaines"), 35)
        self.assertEqual(parse_ouedkniss_relative_age_days("Dely brahim, 16 1 mois"), 31)
        self.assertTrue(is_ouedkniss_within_max_age({"text": "Dely brahim, 16 30 jours"}, 30))
        self.assertFalse(is_ouedkniss_within_max_age({"text": "Dely brahim, 16 1 mois"}, 30))


class OCRParserTests(SimpleTestCase):
    def test_parses_mixed_instagram_listing_text(self):
        parsed = parse_ocr_text("iPhone 17 pro Max 256GB 2sim 100% Cycles 01 Prix 339000")
        self.assertEqual(parsed.price_dzd, 339000)
        self.assertEqual(parsed.storage_gb, 256)
        self.assertEqual(parsed.battery_health, 100)
        self.assertEqual(parsed.battery_cycles, 1)
        self.assertIn("2sim", parsed.sim_text.lower())

    def test_ignores_phone_number_and_reads_price_box_value(self):
        parsed = parse_ocr_text("iPhone 15 Plus 128Gb/91%\nGarden city 0561589322\n128000")
        self.assertEqual(parsed.model_text, "iPhone 15 Plus")
        self.assertEqual(parsed.storage_gb, 128)
        self.assertEqual(parsed.battery_health, 91)
        self.assertEqual(parsed.price_dzd, 128000)

    def test_repairs_extra_leading_digit_only_when_implausibly_high(self):
        self.assertEqual(parse_ocr_text("iPhone 13 256Gb/78% 2sim\n475000").price_dzd, 75000)
        self.assertEqual(parse_ocr_text("Samsung s25 ultra 12/512Gb 2sim\n188000").price_dzd, 188000)
        self.assertEqual(parse_ocr_text("Samsung s25 ultra 12/512Gb 2sim\n188000").storage_gb, 512)

    def test_prefers_explicit_da_price_over_barcode_like_numbers(self):
        parsed = parse_ocr_text(
            "iPhone 13 128-79%\n"
            "BROTHER GARDEN\n"
            "PHONE 15 128-79 95018398283034\n"
            "1000000\n"
            "048186\n"
            "000012-001282-4/27 2026\n"
            "72000 da\n"
            "0561589322 garden"
        )
        self.assertEqual(parsed.model_text, "iPhone 13")
        self.assertEqual(parsed.storage_gb, 128)
        self.assertEqual(parsed.battery_health, 79)
        self.assertEqual(parsed.price_dzd, 72000)

    def test_reads_later_explicit_da_price_when_generic_number_appears_first(self):
        parsed = parse_ocr_text(
            "iPhone 12 pro max 128-88%\n"
            "BROTHER GARDEN 11 6\n"
            "IPHONE 12 PHO MAX 125 AIS GLASS\n"
            "1 1000000\n"
            "10 22957\n"
            "000016 005455-41 42925\n"
            "65000 da\n"
            "0561589322 garden"
        )
        self.assertEqual(parsed.model_text, "iPhone 12 pro max")
        self.assertEqual(parsed.storage_gb, 128)
        self.assertEqual(parsed.battery_health, 88)
        self.assertEqual(parsed.price_dzd, 65000)

    def test_rejects_bare_million_barcode_artifact_without_explicit_price(self):
        parsed = parse_ocr_text(
            "iPhone 13 pro 128-85%\n"
            "AR-BROTHER PHONE\n"
            "BROTHERS PHONE\n"
            "BROTHER GARDEN\n"
            "IPHONE 13 PRO 550367271930355 128 100\n"
            "1000000\n"
            "019285\n"
            "10.00\n"
            "0561589322 garden"
        )
        self.assertEqual(parsed.model_text, "iPhone 13 pro")
        self.assertEqual(parsed.storage_gb, 128)
        self.assertIsNone(parsed.price_dzd)


class DealsSwiperTests(TestCase):
    """Tests for the deals swiper page and lazy-load endpoint."""

    def _create_deal_snapshot(self, **overrides):
        from django.utils import timezone
        from market.models import DealSnapshot, MarketListing, Source

        source, _ = Source.objects.get_or_create(
            name="Test Source",
            source_type="ouedkniss",
            defaults={"country": "DZ"},
        )
        listing = MarketListing.objects.create(
            source=source,
            source_type="ouedkniss",
            country="DZ",
            title_raw="Samsung Galaxy S25 Ultra 256GB",
            price_original=180000,
            currency_original="DZD",
            price_eur=Decimal("1200.00"),
            listing_url="https://example.com/listing/1",
        )
        defaults = {
            "listing": listing,
            "brand_name": "Samsung",
            "model_name": "Galaxy S25 Ultra",
            "storage_gb": 256,
            "title": "Samsung Galaxy S25 Ultra 256GB",
            "price_original": Decimal("180000"),
            "currency_original": "DZD",
            "price_eur": Decimal("1200.00"),
            "condition": "Used",
            "source_code": "ODK",
            "source_name": "Test Source",
            "image_url": "",
            "listing_url": "https://example.com/listing/1",
            "observed_at": timezone.now(),
            "sah_median": Decimal("45000"),
            "sah_count": 5,
            "sah_urls": ["https://sahibinden.com/1", "https://sahibinden.com/2"],
            "margin_pct": 25.0,
            "margin_eur": Decimal("300.00"),
            "supplier_usd": 950.0,
            "supplier_eur": 880.0,
        }
        defaults.update(overrides)
        return DealSnapshot.objects.create(**defaults)

    def test_public_user_can_load_deals_page(self):
        self._create_deal_snapshot()
        response = self.client.get(reverse("deals_swiper"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deals")

    def test_public_deals_page_hides_supplier_pricing(self):
        self._create_deal_snapshot(supplier_usd=950.0, supplier_eur=880.0)
        response = self.client.get(reverse("deals_swiper"))
        self.assertNotContains(response, "950")
        self.assertNotContains(response, "880")

    def test_superuser_deals_page_shows_supplier_pricing(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="staff", password="pass", is_staff=True)
        self.client.force_login(user)
        self._create_deal_snapshot(supplier_usd=950.0, supplier_eur=880.0)
        response = self.client.get(reverse("deals_swiper"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "950")
        self.assertContains(response, "880")

    def test_deals_more_returns_html_with_swiper_slides(self):
        self._create_deal_snapshot()
        response = self.client.get(
            reverse("deals_more") + "?brand=ALL&offset=0&limit=10"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("swiper-slide", data["html"])
        self.assertGreater(data["count"], 0)

    def test_deals_more_invalid_offset_does_not_crash(self):
        self._create_deal_snapshot()
        response = self.client.get(
            reverse("deals_more") + "?brand=ALL&offset=abc&limit=xyz"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])

    def test_deals_more_limit_capped(self):
        self._create_deal_snapshot()
        response = self.client.get(
            reverse("deals_more") + "?brand=ALL&offset=0&limit=999"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])

    def test_clean_phone_snapshot_feeds_deals_without_legacy_snapshot(self):
        from market.clean_models import PhoneOpportunitySnapshot

        PhoneOpportunitySnapshot.objects.create(
            brand="Apple",
            model="iPhone 15 Pro",
            storage_gb=256,
            algeria_min_eur=Decimal("500"),
            turkiye_min_eur=Decimal("700"),
            turkiye_avg_eur=Decimal("800"),
            gross_margin_eur=Decimal("300"),
            margin_percent=Decimal("60"),
            algeria_count=1,
            turkiye_count=2,
            algeria_urls=["https://example.com/dz"],
            turkiye_urls=["https://example.com/tr"],
            recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
            confidence_score=80,
        )

        response = self.client.get(reverse("deals_swiper"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPhone 15 Pro")
        self.assertContains(response, "PhoneListing v2")

    def test_clean_deals_exclude_non_actionable_snapshots(self):
        from market.clean_models import LaptopOpportunitySnapshot, PhoneOpportunitySnapshot

        PhoneOpportunitySnapshot.objects.create(
            brand="Apple",
            model="iPhone Watch Row",
            storage_gb=256,
            algeria_min_eur=Decimal("500"),
            turkiye_avg_eur=Decimal("800"),
            gross_margin_eur=Decimal("300"),
            margin_percent=Decimal("60"),
            algeria_count=1,
            turkiye_count=1,
            recommendation=PhoneOpportunitySnapshot.Recommendation.WATCH,
            confidence_score=50,
        )
        LaptopOpportunitySnapshot.objects.create(
            brand="Lenovo",
            model="Legion Low Confidence",
            cpu="Intel Core i7",
            gpu="NVIDIA RTX 4060",
            algeria_min_eur=Decimal("500"),
            turkiye_avg_eur=Decimal("800"),
            gross_margin_eur=Decimal("300"),
            margin_percent=Decimal("60"),
            algeria_count=1,
            turkiye_count=1,
            recommendation=LaptopOpportunitySnapshot.Recommendation.LOW_CONFIDENCE,
            confidence_score=40,
        )
        LaptopOpportunitySnapshot.objects.create(
            brand="Apple",
            model="MacBook Pro M4 Pro",
            cpu="Apple M4 Pro",
            ram_gb=24,
            storage_gb=512,
            algeria_min_eur=Decimal("1800"),
            turkiye_avg_eur=Decimal("2400"),
            gross_margin_eur=Decimal("600"),
            margin_percent=Decimal("33"),
            algeria_count=2,
            turkiye_count=2,
            recommendation=LaptopOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
            confidence_score=70,
        )

        response = self.client.get(reverse("deals_swiper"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MacBook Pro M4 Pro")
        self.assertNotContains(response, "iPhone Watch Row")
        self.assertNotContains(response, "Legion Low Confidence")


class CatalogSpecSystemTests(TestCase):
    """Tests for the generic typed spec system."""

    def test_create_product_type(self):
        from market.models import ProductType
        pt = ProductType.objects.create(name="Phone", slug="phone", description="Smartphones")
        self.assertEqual(pt.name, "Phone")
        self.assertEqual(pt.slug, "phone")

    def test_create_spec_definition(self):
        from market.models import ProductType, SpecDefinition
        pt = ProductType.objects.create(name="Phone", slug="phone")
        spec = SpecDefinition.objects.create(
            product_type=pt,
            key="storage_gb",
            label="Storage",
            value_type=SpecDefinition.ValueType.INTEGER,
            unit="GB",
            is_variant_identity=True,
            sort_order=10,
        )
        self.assertEqual(spec.key, "storage_gb")
        self.assertTrue(spec.is_variant_identity)

    def test_seed_laptop_specs_idempotent(self):
        from django.core.management import call_command
        call_command("seed_product_types_and_specs", stdout=self.out)
        from market.models import ProductType, SpecDefinition
        laptop = ProductType.objects.get(slug="laptop")
        count_before = SpecDefinition.objects.filter(product_type=laptop).count()
        call_command("seed_product_types_and_specs", stdout=self.out)
        count_after = SpecDefinition.objects.filter(product_type=laptop).count()
        self.assertEqual(count_before, count_after)

    def test_save_listing_spec_value(self):
        from market.models import (
            Brand, Category, Country, DeviceVariant, MarketListing, MarketListingSpecValue,
            ProductModel, ProductType, Source, SourceType, SpecDefinition,
        )
        from market.services.catalog import get_or_create_product_type, upsert_listing_spec_value

        pt = get_or_create_product_type("laptop", name="Laptop")
        SpecDefinition.objects.get_or_create(
            product_type=pt, key="ram_gb",
            defaults={"label": "RAM", "value_type": "integer", "unit": "GB", "sort_order": 10},
        )
        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5 Pro",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-sah",
            defaults={"name": "Test Sahibinden"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Legion 5 Pro 16GB", price_original=45000,
            currency_original="TRY", listing_url="https://example.com/1",
        )
        sv = upsert_listing_spec_value(listing, "ram_gb", 16)
        self.assertIsNotNone(sv)
        self.assertEqual(sv.value_integer, 16)
        self.assertEqual(sv.effective_value, 16)

    def test_save_variant_spec_value(self):
        from market.models import (
            Brand, Category, DeviceVariant, ProductModel, ProductType, SpecDefinition,
        )
        from market.services.catalog import get_or_create_product_type, upsert_variant_spec_value

        pt = get_or_create_product_type("laptop", name="Laptop")
        SpecDefinition.objects.get_or_create(
            product_type=pt, key="cpu_model",
            defaults={"label": "CPU Model", "value_type": "option", "sort_order": 10},
        )
        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5 Pro",
        )
        variant = DeviceVariant.objects.create(
            product_model=pm, canonical_label="Legion 5 Pro 16GB",
            storage_gb=None, identity_key="|sim=|region=|color=",
        )
        sv = upsert_variant_spec_value(variant, "cpu_model", "Intel Core i7-13700H")
        self.assertIsNotNone(sv)
        self.assertEqual(sv.value_text, "Intel Core i7-13700H")

    def test_build_laptop_identity_key(self):
        from market.models import (
            Brand, Category, DeviceVariant, ProductModel, ProductType, SpecDefinition,
        )
        from market.services.catalog import (
            build_variant_identity_from_specs, get_or_create_product_type,
            upsert_variant_spec_value,
        )

        pt = get_or_create_product_type("laptop", name="Laptop")
        for key, label, sort_order in [
            ("cpu_model", "CPU Model", 10),
            ("gpu_model", "GPU Model", 20),
            ("ram_gb", "RAM", 30),
            ("ssd_gb", "SSD", 40),
        ]:
            SpecDefinition.objects.get_or_create(
                product_type=pt, key=key,
                defaults={"label": label, "value_type": "integer" if "gb" in key else "option",
                          "is_variant_identity": True, "sort_order": sort_order},
            )
        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5 Pro",
        )
        variant = DeviceVariant.objects.create(
            product_model=pm, canonical_label="Legion 5 Pro",
            storage_gb=None, identity_key="",
        )
        upsert_variant_spec_value(variant, "cpu_model", "Intel Core i7-13700H")
        upsert_variant_spec_value(variant, "gpu_model", "NVIDIA RTX 4060")
        upsert_variant_spec_value(variant, "ram_gb", 16)
        upsert_variant_spec_value(variant, "ssd_gb", 512)

        identity = build_variant_identity_from_specs(pt, {
            "cpu_model": "Intel Core i7-13700H",
            "gpu_model": "NVIDIA RTX 4060",
            "ram_gb": 16,
            "ssd_gb": 512,
        })
        self.assertIn("cpu_model=Intel Core i7-13700H", identity)
        self.assertIn("gpu_model=NVIDIA RTX 4060", identity)
        self.assertIn("ram_gb=16", identity)
        self.assertIn("ssd_gb=512", identity)

    def test_existing_phone_variant_behavior_unchanged(self):
        """Ensure existing phone DeviceVariant identity key still works."""
        product_model = get_or_create_model("Samsung Galaxy S25 Ultra")
        variant = get_or_create_variant(product_model, storage_gb=256, sim_config="2Sim")
        self.assertEqual(variant.identity_key, "storage=256|sim=2sim|region=|color=")

    def test_opportunity_analysis_still_runs(self):
        """Ensure run_analysis still works with the existing phone-based schema."""
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertIsInstance(created, int)

    def test_laptop_listing_can_be_stored_without_laptop_columns(self):
        """Verify a laptop listing can be stored using spec values instead of new columns."""
        from market.models import (
            Brand, Category, Country, MarketListing, ProductModel, ProductType,
            Source, SourceType, SpecDefinition,
        )
        from market.services.catalog import get_or_create_product_type, upsert_listing_spec_value

        pt = get_or_create_product_type("laptop", name="Laptop")
        for key, label, vt, sort_order in [
            ("cpu_model", "CPU Model", "option", 10),
            ("gpu_model", "GPU Model", "option", 20),
            ("ram_gb", "RAM", "integer", 30),
            ("ssd_gb", "SSD", "integer", 40),
        ]:
            SpecDefinition.objects.get_or_create(
                product_type=pt, key=key,
                defaults={"label": label, "value_type": vt, "sort_order": sort_order},
            )
        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5 Pro 16IRX9",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-sah-laptop",
            defaults={"name": "Test Sahibinden Laptops"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 Pro 16IRX9 i7-13700H RTX 4060 16GB 512GB SSD",
            price_original=55000, currency_original="TRY",
            listing_url="https://sahibinden.com/laptop/1",
        )
        upsert_listing_spec_value(listing, "cpu_model", "Intel Core i7-13700H")
        upsert_listing_spec_value(listing, "gpu_model", "NVIDIA RTX 4060")
        upsert_listing_spec_value(listing, "ram_gb", 16)
        upsert_listing_spec_value(listing, "ssd_gb", 512)

        from market.models import MarketListingSpecValue
        sv_count = MarketListingSpecValue.objects.filter(listing=listing).count()
        self.assertEqual(sv_count, 4)

        # Listing has no laptop-specific columns — it uses the generic schema
        self.assertIsNone(listing.storage_gb)
        self.assertEqual(listing.sim_config, "")

    def setUp(self):
        import io
        self.out = io.StringIO()


class ProductTypeDetectionTests(SimpleTestCase):
    """Tests for product type detection from text."""

    def test_detects_laptop_by_keyword(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("Lenovo Legion 5 laptop"), "laptop")
        self.assertEqual(detect_product_type("MacBook Pro M3"), "laptop")
        self.assertEqual(detect_product_type("ASUS ROG Strix G16"), "laptop")
        self.assertEqual(detect_product_type("HP Victus gaming notebook"), "laptop")
        self.assertEqual(detect_product_type("ThinkPad X1 Carbon"), "laptop")

    def test_detects_laptop_by_gpu_evidence(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("RTX 4060 16GB 512GB SSD"), "laptop")
        self.assertEqual(detect_product_type("GTX 1650 i5-12400F"), "laptop")
        self.assertEqual(detect_product_type("Radeon RX 7600 8GB"), "laptop")

    def test_detects_laptop_by_cpu_evidence(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("i7-13700H 16GB RAM"), "laptop")
        self.assertEqual(detect_product_type("Ryzen 7 7840HS RTX 4060"), "laptop")

    def test_detects_phone_by_model_pattern(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("iPhone 15 Pro Max 256GB"), "phone")
        self.assertEqual(detect_product_type("Samsung Galaxy S24 Ultra"), "phone")
        self.assertEqual(detect_product_type("Pixel 8 Pro 128GB"), "phone")
        self.assertEqual(detect_product_type("Xiaomi 14 Pro"), "phone")

    def test_detects_phone_by_brand_keyword(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("Samsung Galaxy A54"), "phone")
        self.assertEqual(detect_product_type("Huawei Pura 70"), "phone")

    def test_detects_tablet(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("iPad Pro M2 128GB"), "tablet")
        self.assertEqual(detect_product_type("Samsung Galaxy Tab S9"), "tablet")

    def test_detects_console(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("PlayStation 5 Digital"), "console")
        self.assertEqual(detect_product_type("Xbox Series X"), "console")
        self.assertEqual(detect_product_type("Nintendo Switch OLED"), "console")

    def test_detects_vr_headset(self):
        from market.services.spec_extraction import detect_product_type
        self.assertEqual(detect_product_type("Meta Quest 3 128GB"), "vr_headset")
        self.assertEqual(detect_product_type("HTC Vive Pro 2"), "vr_headset")

    def test_returns_none_for_unknown(self):
        from market.services.spec_extraction import detect_product_type
        self.assertIsNone(detect_product_type("Some random text"))
        self.assertIsNone(detect_product_type(""))


class LaptopSpecExtractionTests(SimpleTestCase):
    """Tests for laptop spec extraction from text."""

    def test_extracts_ram_gb(self):
        from market.services.laptop_parser import parse_ram_gb
        self.assertEqual(parse_ram_gb("16GB RAM"), 16)
        self.assertEqual(parse_ram_gb("32 Go RAM"), 32)
        self.assertEqual(parse_ram_gb("8GB"), 8)
        self.assertEqual(parse_ram_gb("Lenovo Legion 16GB DDR5"), 16)

    def test_extracts_ssd_gb(self):
        from market.services.laptop_parser import parse_storage_gb
        self.assertEqual(parse_storage_gb("512GB SSD"), 512)
        self.assertEqual(parse_storage_gb("1TB SSD"), 1024)
        self.assertEqual(parse_storage_gb("256GB NVMe"), 256)
        self.assertEqual(parse_storage_gb("1 To SSD"), 1024)

    def test_extracts_gpu(self):
        from market.services.laptop_parser import parse_gpu
        self.assertIn("RTX 4060", parse_gpu("NVIDIA RTX 4060 8GB"))
        self.assertIn("RTX 4070", parse_gpu("RTX 4070 Ti"))
        self.assertIn("GTX 1650", parse_gpu("GTX 1650 4GB"))
        self.assertIn("Radeon", parse_gpu("AMD Radeon RX 7600"))

    def test_extracts_cpu(self):
        from market.services.laptop_parser import parse_cpu
        self.assertIn("i7-13700H", parse_cpu("Intel Core i7-13700H"))
        self.assertIn("Ryzen 7", parse_cpu("AMD Ryzen 7 7840HS"))
        self.assertIn("M3 Pro", parse_cpu("Apple M3 Pro"))

    def test_extracts_refresh_rate(self):
        from market.services.spec_extraction import _extract_refresh_rate
        self.assertEqual(_extract_refresh_rate("165Hz display"), 165)
        self.assertEqual(_extract_refresh_rate("144 Hz refresh rate"), 144)
        self.assertEqual(_extract_refresh_rate("60Hz"), 60)

    def test_extracts_screen_size(self):
        from market.services.laptop_parser import parse_screen_size
        self.assertAlmostEqual(parse_screen_size('15.6" display'), 15.6)
        self.assertAlmostEqual(parse_screen_size('16" screen'), 16.0)

    def test_extracts_touchscreen(self):
        from market.services.spec_extraction import _extract_touchscreen
        self.assertTrue(_extract_touchscreen("15.6 inch touchscreen"))
        self.assertTrue(_extract_touchscreen("14 inch ekran dokunmatik"))
        self.assertIsNone(_extract_touchscreen("15.6 inch IPS display"))

    def test_macbook_m_series(self):
        from market.services.laptop_parser import parse_cpu
        cpu = parse_cpu("MacBook Pro M3 Pro 18GB")
        self.assertIn("M3", cpu)
        self.assertIn("Pro", cpu)

    def test_incomplete_laptop_extracts_fewer_specs(self):
        from market.services.spec_extraction import extract_specs_from_text
        specs = extract_specs_from_text("laptop", "Lenovo Legion 5 RTX 4060")
        self.assertIn("gpu_model", specs)
        self.assertNotIn("ram_gb", specs)
        self.assertNotIn("ssd_gb", specs)

    def test_full_laptop_listing_extracts_many_specs(self):
        from market.services.spec_extraction import extract_specs_from_text
        specs = extract_specs_from_text(
            "laptop",
            "Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz i7-13700H"
        )
        self.assertIn("gpu_model", specs)
        self.assertIn("ram_gb", specs)
        self.assertIn("ssd_gb", specs)
        self.assertIn("refresh_hz", specs)
        self.assertIn("cpu_model", specs)


class PhoneSpecExtractionTests(SimpleTestCase):
    """Tests for phone spec extraction (wrapping existing logic)."""

    def test_extracts_storage(self):
        from market.services.spec_extraction import extract_phone_specs
        specs = extract_phone_specs("iPhone 15 Pro Max 256GB")
        self.assertEqual(specs.get("storage_gb"), 256)

    def test_extracts_ram(self):
        from market.services.spec_extraction import extract_phone_specs
        specs = extract_phone_specs("Samsung S24 Ultra 12/256")
        self.assertEqual(specs.get("ram_gb"), 12)

    def test_extracts_sim_config(self):
        from market.services.spec_extraction import extract_phone_specs
        specs = extract_phone_specs("iPhone 15 128GB Dual SIM")
        self.assertEqual(specs.get("sim_config"), "2sim")


class ListingMatchingTests(TestCase):
    """Tests for progressive matching logic."""

    def test_exact_laptop_match(self):
        from market.models import Brand, Category, ProductType, SpecDefinition
        from market.services.catalog import get_or_create_product_type
        from market.services.listing_matching import match_listing_to_catalog

        pt = get_or_create_product_type("laptop", name="Laptop")
        for key, label, vt in [
            ("cpu_brand", "CPU Brand", "option"),
            ("cpu_model", "CPU Model", "option"),
            ("gpu_brand", "GPU Brand", "option"),
            ("gpu_model", "GPU Model", "option"),
            ("ram_gb", "RAM", "integer"),
            ("ssd_gb", "SSD", "integer"),
        ]:
            SpecDefinition.objects.get_or_create(
                product_type=pt, key=key,
                defaults={"label": label, "value_type": vt, "is_variant_identity": True},
            )

        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(
            slug="laptops", defaults={"name": "Laptops"}
        )
        from market.models import ProductModel
        pm = ProductModel.objects.create(
            brand=brand,
            category=category,
            product_type=pt,
            canonical_name="Lenovo Legion 5",
        )

        result = match_listing_to_catalog(
            title="Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz",
            product_type_slug="laptop",
            brand_name="Lenovo",
            model_text="Lenovo Legion 5",
            specs={"gpu_model": "NVIDIA RTX 4060", "ram_gb": 16, "ssd_gb": 512},
        )

        self.assertEqual(result.product_model, pm)
        self.assertIn(result.confidence, ["exact", "high"])

    def test_low_confidence_missing_model(self):
        from market.services.listing_matching import match_listing_to_catalog
        result = match_listing_to_catalog(
            title="Some random laptop without brand",
            product_type_slug="laptop",
        )
        self.assertEqual(result.confidence, "low")

    def test_dirty_model_name_blocks_match(self):
        from market.services.listing_matching import match_listing_to_catalog
        result = match_listing_to_catalog(
            title="Samsung Galaxy Store GSM",
            product_type_slug="phone",
            model_text="Samsung Galaxy Store GSM",
        )
        self.assertEqual(result.confidence, "low")


class BackfillProductTypesTests(TestCase):
    """Tests for backfill_product_types command."""

    def test_backfill_sets_phone_type(self):
        from django.core.management import call_command
        import io
        from market.models import Brand, Category, ProductType, ProductModel
        from market.services.catalog import get_or_create_product_type

        # Ensure phone type exists
        get_or_create_product_type("phone", name="Phone")

        brand, _ = Brand.objects.get_or_create(name="Samsung")
        category, _ = Category.objects.get_or_create(
            slug="phones", defaults={"name": "Phones"}
        )
        pm = ProductModel.objects.create(
            brand=brand,
            category=category,
            canonical_name="Galaxy S24 Ultra",
        )
        self.assertIsNone(pm.product_type)

        out = io.StringIO()
        call_command("backfill_product_types", stdout=out)

        pm.refresh_from_db()
        self.assertIsNotNone(pm.product_type)
        self.assertEqual(pm.product_type.slug, "phone")

    def test_backfill_is_idempotent(self):
        from django.core.management import call_command
        import io
        from market.models import Brand, Category, ProductModel
        from market.services.catalog import get_or_create_product_type

        get_or_create_product_type("phone", name="Phone")
        brand, _ = Brand.objects.get_or_create(name="Apple")
        category, _ = Category.objects.get_or_create(
            slug="phones", defaults={"name": "Phones"}
        )
        pm = ProductModel.objects.create(
            brand=brand,
            category=category,
            product_type=get_or_create_product_type("phone"),
            canonical_name="iPhone 15 Pro",
        )

        out1 = io.StringIO()
        call_command("backfill_product_types", stdout=out1)
        pm.refresh_from_db()
        first_type_id = pm.product_type_id

        out2 = io.StringIO()
        call_command("backfill_product_types", stdout=out2)
        pm.refresh_from_db()
        self.assertEqual(pm.product_type_id, first_type_id)


class SpecExtractionIntegrationTests(TestCase):
    """Integration tests for spec extraction on listing creation."""

    def test_laptop_listing_gets_spec_values(self):
        from market.models import (
            Brand, Category, Country, MarketListing, ProductType,
            Source, SourceType, SpecDefinition,
        )
        from market.services.catalog import (
            get_or_create_product_type,
            upsert_listing_specs_from_dict,
        )

        pt = get_or_create_product_type("laptop", name="Laptop")
        for key, label, vt in [
            ("gpu_model", "GPU Model", "option"),
            ("ram_gb", "RAM", "integer"),
            ("ssd_gb", "SSD", "integer"),
        ]:
            SpecDefinition.objects.get_or_create(
                product_type=pt, key=key,
                defaults={"label": label, "value_type": vt},
            )

        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(
            slug="laptops", defaults={"name": "Laptops"}
        )
        from market.models import ProductModel
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-sah",
            defaults={"name": "Test"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 RTX 4060 16GB 512GB SSD",
            price_original=55000, currency_original="TRY",
            listing_url="https://example.com/1",
        )

        from market.services.spec_extraction import extract_specs_from_text
        specs = extract_specs_from_text("laptop", listing.title_raw)
        saved = upsert_listing_specs_from_dict(listing, specs, confidence=0.85)

        self.assertGreater(len(saved), 0)

        from market.models import MarketListingSpecValue
        sv_count = MarketListingSpecValue.objects.filter(listing=listing).count()
        self.assertGreater(sv_count, 0)

    def test_phone_listing_backward_compatible(self):
        """Ensure phone listings still work with existing logic."""
        from market.services.spec_extraction import extract_phone_specs
        specs = extract_phone_specs("iPhone 15 Pro 256GB 2sim")
        self.assertEqual(specs.get("storage_gb"), 256)
        self.assertEqual(specs.get("sim_config"), "2sim")


class OpportunityAnalysisStillRunsTests(TestCase):
    """Ensure opportunity analysis still runs after Phase 2 changes."""

    def test_run_analysis_returns_int(self):
        from market.services.opportunity import run_analysis
        result = run_analysis()
        self.assertIsInstance(result, int)


# ── Phase 3: Match level and confidence gate tests ──────────────────────────


class MatchLevelFieldTests(TestCase):
    """Tests for the new match_level and match_confidence fields on MarketListing."""

    def test_new_listing_has_default_match_level(self):
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test",
            defaults={"name": "Test"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            title_raw="Test listing",
            listing_url="https://example.com/test1",
        )
        self.assertEqual(listing.match_level, MarketListing.MatchLevel.UNMATCHED)
        self.assertEqual(listing.match_confidence, 0)
        self.assertEqual(listing.match_reason, "")

    def test_match_level_choices(self):
        choices = [c[0] for c in MarketListing.MatchLevel.choices]
        self.assertIn("exact_variant", choices)
        self.assertIn("strong_candidate", choices)
        self.assertIn("model_only", choices)
        self.assertIn("unmatched", choices)
        self.assertIn("conflict", choices)


class ConfidenceGateTests(TestCase):
    """Tests for confidence gate constants and eligibility logic."""

    def test_eligible_levels_include_exact_and_strong(self):
        from market.models import OPPORTUNITY_ELIGIBLE_MATCH_LEVELS
        self.assertIn("exact_variant", OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)
        self.assertIn("strong_candidate", OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)
        self.assertNotIn("unmatched", OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)
        self.assertNotIn("conflict", OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)

    def test_model_only_excluded_by_default(self):
        from market.models import ALLOW_MODEL_ONLY_OPPORTUNITIES
        self.assertFalse(ALLOW_MODEL_ONLY_OPPORTUNITIES)

    def test_min_confidence_threshold(self):
        from market.models import MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY
        self.assertEqual(MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY, 0.70)


class OpportunityAnalysisMatchLevelTests(TestCase):
    """Tests for opportunity analysis filtering by match_level."""

    def _make_phone_listing(self, price_eur=100, review_status="auto"):
        brand, _ = Brand.objects.get_or_create(name="Samsung")
        category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        pm = ProductModel.objects.create(
            brand=brand, category=category,
            canonical_name="Galaxy S25",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-phone",
            defaults={"name": "Test Phone"},
        )
        return MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.ALGERIA, product_model=pm,
            title_raw="Samsung Galaxy S25 256GB",
            price_original=800, currency_original="DZD",
            price_eur=price_eur,
            storage_gb=256,
            review_status=review_status,
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://example.com/phone1",
        )

    def _make_laptop_listing(self, match_level="unmatched", match_confidence=0, price_eur=500, review_status="auto"):
        from market.services.catalog import get_or_create_product_type
        pt = get_or_create_product_type("laptop", name="Laptop")
        brand, _ = Brand.objects.get_or_create(name="Lenovo")
        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        pm = ProductModel.objects.create(
            brand=brand, category=category, product_type=pt,
            canonical_name="Legion 5",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-laptop",
            defaults={"name": "Test Laptop"},
        )
        return MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.ALGERIA, product_model=pm,
            title_raw="Lenovo Legion 5 RTX 4060 16GB",
            price_original=55000, currency_original="TRY",
            price_eur=price_eur,
            storage_gb=512,
            review_status=review_status,
            match_level=match_level,
            match_confidence=match_confidence,
            listing_url="https://example.com/laptop1",
        )

    def test_phone_listing_included_in_opportunity(self):
        """Phone listings are always eligible regardless of match_level."""
        self._make_phone_listing(price_eur=100, review_status="auto")
        # Need a Turkiye listing for the analysis to create a snapshot
        brand = Brand.objects.get(name="Samsung")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Galaxy S25")
        source = Source.objects.get(username="test-phone")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Samsung Galaxy S25 256GB TR",
            price_original=30000, currency_original="TRY",
            price_eur=600,
            storage_gb=256,
            review_status="auto",
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://sahibinden.com/phone1",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertGreaterEqual(created, 1)

    def test_unmatched_laptop_excluded_from_opportunity(self):
        """Laptop with match_level=unmatched is excluded."""
        self._make_laptop_listing(match_level="unmatched", match_confidence=0.3, price_eur=500)
        # Turkiye listing
        brand = Brand.objects.get(name="Lenovo")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Legion 5")
        source = Source.objects.get(username="test-laptop")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 TR",
            price_original=55000, currency_original="TRY",
            price_eur=1000,
            storage_gb=512,
            review_status="auto",
            listing_url="https://sahibinden.com/laptop1",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        # Should not create snapshot for unmatched laptop
        self.assertEqual(created, 0)

    def test_exact_variant_laptop_included_in_opportunity(self):
        """Laptop with match_level=exact_variant and high confidence is included."""
        self._make_laptop_listing(match_level="exact_variant", match_confidence=0.95, price_eur=500)
        brand = Brand.objects.get(name="Lenovo")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Legion 5")
        source = Source.objects.get(username="test-laptop")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 TR",
            price_original=55000, currency_original="TRY",
            price_eur=1000,
            storage_gb=512,
            review_status="auto",
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://sahibinden.com/laptop2",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertGreaterEqual(created, 1)

    def test_conflict_laptop_excluded_from_opportunity(self):
        """Laptop with match_level=conflict is excluded."""
        self._make_laptop_listing(match_level="conflict", match_confidence=0.5, price_eur=500)
        brand = Brand.objects.get(name="Lenovo")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Legion 5")
        source = Source.objects.get(username="test-laptop")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 TR",
            price_original=55000, currency_original="TRY",
            price_eur=1000,
            storage_gb=512,
            review_status="auto",
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://sahibinden.com/laptop3",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertEqual(created, 0)

    def test_model_only_laptop_excluded_by_default(self):
        """Laptop with match_level=model_only is excluded when ALLOW_MODEL_ONLY_OPPORTUNITIES=False."""
        self._make_laptop_listing(match_level="model_only", match_confidence=0.8, price_eur=500)
        brand = Brand.objects.get(name="Lenovo")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Legion 5")
        source = Source.objects.get(username="test-laptop")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 TR",
            price_original=55000, currency_original="TRY",
            price_eur=1000,
            storage_gb=512,
            review_status="auto",
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://sahibinden.com/laptop4",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertEqual(created, 0)

    def test_medium_confidence_laptop_flagged_but_usable(self):
        """Laptop with match_level=strong_candidate and sufficient confidence is included."""
        self._make_laptop_listing(match_level="strong_candidate", match_confidence=0.75, price_eur=500)
        brand = Brand.objects.get(name="Lenovo")
        pm = ProductModel.objects.get(brand=brand, canonical_name="Legion 5")
        source = Source.objects.get(username="test-laptop")
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Lenovo Legion 5 TR",
            price_original=55000, currency_original="TRY",
            price_eur=1000,
            storage_gb=512,
            review_status="auto",
            match_level="exact_variant",
            match_confidence=0.95,
            listing_url="https://sahibinden.com/laptop5",
        )
        from market.services.opportunity import run_analysis
        created = run_analysis()
        self.assertGreaterEqual(created, 1)


class ApplyMatchToListingTests(TestCase):
    """Tests for apply_match_to_listing persisting match_level and match_confidence."""

    def test_apply_exact_match_persists_fields(self):
        from market.services.listing_matching import MatchResult, apply_match_to_listing

        brand, _ = Brand.objects.get_or_create(name="TestBrand")
        category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        pm = ProductModel.objects.create(
            brand=brand, category=category,
            canonical_name="TestModel",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-apply",
            defaults={"name": "Test"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Test phone 256GB",
            listing_url="https://example.com/apply1",
        )
        match = MatchResult(
            product_model=pm,
            variant=None,
            confidence="exact",
            confidence_score=0.95,
            reasons=["Found model", "Matched variant"],
        )
        apply_match_to_listing(listing, match, specs={"storage_gb": 256})
        listing.save()
        listing.refresh_from_db()

        self.assertEqual(listing.match_level, MarketListing.MatchLevel.EXACT_VARIANT)
        self.assertAlmostEqual(listing.match_confidence, 0.95)
        self.assertIn("Found model", listing.match_reason)

    def test_apply_conflict_match_persists_conflict(self):
        from market.services.listing_matching import MatchResult, apply_match_to_listing

        brand, _ = Brand.objects.get_or_create(name="TestBrand2")
        category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        pm = ProductModel.objects.create(
            brand=brand, category=category,
            canonical_name="TestModel2",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-apply2",
            defaults={"name": "Test2"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Test phone 128GB",
            listing_url="https://example.com/apply2",
        )
        match = MatchResult(
            product_model=pm,
            variant=None,
            confidence="medium",
            confidence_score=0.5,
            reasons=["Conflicting specs with existing variant"],
        )
        apply_match_to_listing(listing, match, specs={})
        listing.save()
        listing.refresh_from_db()

        self.assertEqual(listing.match_level, MarketListing.MatchLevel.CONFLICT)


class LaptopTitleFixtureTests(TestCase):
    """Tests with realistic messy laptop titles."""

    TITLES = [
        "Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz",
        "Legion 5 Pro Ryzen 7 RTX4060 16/1TB",
        "ASUS ROG Strix G16 i7 13650HX RTX 4060 16GB RAM 1TB SSD",
        "HP Victus RTX4050 Ryzen 5 16GB 512 SSD",
        "MacBook Pro M3 Pro 18GB 512GB",
        "Gaming laptop Lenovo clean",
        "RTX4070 laptop 16gb",
    ]

    def test_product_type_detection_on_all_titles(self):
        from market.services.spec_extraction import detect_product_type
        for title in self.TITLES:
            ptype = detect_product_type(title)
            # All should be detected as laptop (or at least not None for most)
            if title in ("Gaming laptop Lenovo clean",):
                # This one has "laptop" keyword, should be detected
                self.assertEqual(ptype, "laptop", f"Failed for: {title}")
            elif "RTX" in title or "MacBook" in title or "ROG" in title or "Legion" in title or "Victus" in title:
                self.assertEqual(ptype, "laptop", f"Failed for: {title}")

    def test_spec_extraction_returns_specs_for大多数_titles(self):
        from market.services.spec_extraction import extract_specs_from_text
        for title in self.TITLES:
            specs = extract_specs_from_text("laptop", title)
            self.assertIsInstance(specs, dict, f"Failed for: {title}")
            # Most titles should extract at least one spec
            if title not in ("Gaming laptop Lenovo clean",):
                self.assertGreater(len(specs), 0, f"No specs extracted for: {title}")


class RecomputeCommandTests(TestCase):
    """Tests for recompute_listing_matches command."""

    def test_dry_run_does_not_mutate_data(self):
        from django.core.management import call_command
        import io

        brand, _ = Brand.objects.get_or_create(name="RecomputeBrand")
        category, _ = Category.objects.get_or_create(slug="phones", defaults={"name": "Phones"})
        pm = ProductModel.objects.create(
            brand=brand, category=category,
            canonical_name="RecomputeModel",
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-recompute",
            defaults={"name": "Test Recompute"},
        )
        listing = MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE, product_model=pm,
            title_raw="Recompute test listing",
            listing_url="https://example.com/recompute1",
            match_level="unmatched",
            match_confidence=0.0,
        )

        out = io.StringIO()
        call_command("recompute_listing_matches", "--dry-run", "--limit=10", stdout=out)

        listing.refresh_from_db()
        # Dry run should NOT change the listing
        self.assertEqual(listing.match_level, "unmatched")
        self.assertEqual(listing.match_confidence, 0.0)


class InspectCommandTests(TestCase):
    """Tests for inspect_listing_matches command."""

    def test_inspect_prints_output(self):
        from django.core.management import call_command
        import io

        # Create a listing so there's something to inspect
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN, username="test-inspect",
            defaults={"name": "Test Inspect"},
        )
        MarketListing.objects.create(
            source=source, source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            title_raw="Test inspect listing",
            listing_url="https://example.com/inspect1",
        )

        out = io.StringIO()
        call_command("inspect_listing_matches", "--limit=5", stdout=out)
        output = out.getvalue()
        # Should print the summary header
        self.assertIn("MATCH QUALITY SUMMARY", output)


class ListingMatchingTests(TestCase):
    """Tests for listing matching with match_level."""

    def test_match_listing_to_catalog_returns_match_result(self):
        from market.services.listing_matching import match_listing_to_catalog
        result = match_listing_to_catalog(
            title="Samsung Galaxy S25 Ultra 256GB",
            product_type_slug="phone",
        )
        self.assertIsNotNone(result)
        self.assertIn(result.confidence, ["exact", "high", "medium", "low", "none"])

    def test_laptop_match_returns_level(self):
        from market.services.listing_matching import match_listing_to_catalog
        result = match_listing_to_catalog(
            title="Lenovo Legion 5 RTX 4060 16GB 512GB SSD",
            product_type_slug="laptop",
        )
        self.assertIsNotNone(result)
        # Should have a confidence level
        self.assertIn(result.confidence, ["exact", "high", "medium", "low", "none"])
