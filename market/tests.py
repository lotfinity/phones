from decimal import Decimal

from django.test import SimpleTestCase, TestCase

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
from market.models import Condition
from market.services.matching import SUPPORTED_STORAGE_GB, get_or_create_model, get_or_create_variant
from market.services.normalization import canonical_model_name, likely_brand
from market.parsers.ocr_parser import parse_ocr_text
from market.parsers.supplier_parser import parse_supplier_line


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
        self.assertEqual(SUPPORTED_STORAGE_GB, {64, 128, 256, 512, 1024})


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
        self.assertEqual(review_status_for(71000, object(), object()), "auto")
        self.assertEqual(review_status_for(71000, object(), None), "needs_review")
        self.assertEqual(review_status_for(177000, object(), object()), "needs_review")


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
