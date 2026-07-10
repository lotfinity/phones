"""Tests for the laptop pipeline v2: parser, canonicalization, merge, and opportunities."""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase

from market.models import (
    Brand,
    Country,
    LaptopListing,
    LaptopModel,
    LaptopVariant,
    ParsedListingCandidate,
    RawListing,
    Source,
    SourceType,
    build_laptop_variant_identity,
)
from market.services.parsing.laptop_parser_v2 import (
    detect_brand,
    detect_cpu,
    detect_gpu,
    detect_ram_gb,
    detect_storage_gb,
    parse_laptop,
)
from market.services.laptop_model_canonicalization import (
    build_laptop_signature,
    laptop_model_merge_key,
    normalize_cpu_family,
    normalize_gpu_family,
    normalize_laptop_model_name,
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class LaptopParserBrandTests(SimpleTestCase):
    def test_detect_lenovo(self):
        self.assertEqual(detect_brand("Lenovo ThinkPad X280"), "Lenovo")

    def test_detect_asus(self):
        self.assertEqual(detect_brand("ASUS TUF A15"), "ASUS")

    def test_detect_hp(self):
        self.assertEqual(detect_brand("HP Victus 15"), "HP")

    def test_does_not_detect_hp_inside_payload_noise(self):
        self.assertEqual(detect_brand('MacBook Air M3 image "https://example.com/a.webp"'), "Apple")

    def test_detect_apple(self):
        self.assertEqual(detect_brand("MacBook Air M1"), "Apple")

    def test_detect_dell(self):
        self.assertEqual(detect_brand("Dell XPS 13"), "Dell")

    def test_detect_unknown(self):
        self.assertEqual(detect_brand("Random text"), "")


class LaptopParserCpuTests(SimpleTestCase):
    """CPU detection with Apple Silicon context awareness."""

    def test_apple_m1_in_macbook_context(self):
        self.assertIn("M1", detect_cpu("MacBook Air M1 8GB 256GB"))

    def test_apple_m2_in_macbook_context(self):
        self.assertIn("M2", detect_cpu("Macbook Pro M2 16 RAM 1TB SSD"))

    def test_apple_m3_pro(self):
        result = detect_cpu("Apple MacBook Pro M3 Pro")
        self.assertIn("M3", result)
        self.assertIn("Pro", result)

    def test_m2_not_detected_as_cpu_in_lenovo(self):
        """M2 SSD in Lenovo context must NOT be detected as Apple M2 CPU."""
        cpu = detect_cpu("Lenovo ThinkPad X280 i5 8 RAM 256 M2 SSD")
        self.assertNotIn("M2", cpu)

    def test_m2_not_detected_as_cpu_in_dell(self):
        cpu = detect_cpu("Dell Latitude M.2 NVMe 256GB")
        self.assertNotIn("M2", cpu)

    def test_m2_not_detected_as_cpu_in_hp(self):
        cpu = detect_cpu("HP Elitebook 512 M2 SSD")
        self.assertNotIn("M2", cpu)

    def test_intel_i5(self):
        self.assertIn("i5", detect_cpu("Lenovo ThinkPad X280 i5 8GB"))

    def test_intel_i7_full(self):
        result = detect_cpu("Dell XPS 15 i7-12700H 16GB")
        self.assertIn("i7-12700H", result)

    def test_intel_i9(self):
        self.assertIn("i9", detect_cpu("ASUS ROG Strix i9 32GB"))

    def test_intel_core_ultra(self):
        result = detect_cpu("Lenovo Yoga Core Ultra 7 155H")
        self.assertIn("Ultra", result)

    def test_amd_ryzen_7(self):
        result = detect_cpu("ASUS TUF A15 Ryzen 7 5800H")
        self.assertIn("Ryzen 7", result)

    def test_amd_ryzen_5_short(self):
        result = detect_cpu("HP Victus Ryzen 5 8GB")
        self.assertIn("Ryzen 5", result)

    def test_snapdragon(self):
        result = detect_cpu("Lenovo ThinkPad X13s Snapdragon 8cx Gen 3")
        self.assertIn("Snapdragon", result)


class LaptopParserGpuTests(SimpleTestCase):
    def test_nvidia_rtx_3060(self):
        result = detect_gpu("ASUS TUF A15 RTX 3060 16GB")
        self.assertIn("RTX 3060", result)

    def test_nvidia_rtx_4050(self):
        result = detect_gpu("HP Victus i5 RTX 4050 16/512")
        self.assertIn("RTX 4050", result)

    def test_nvidia_gtx_1650(self):
        result = detect_gpu("Lenovo IdeaPad GTX 1650 8GB")
        self.assertIn("GTX 1650", result)

    def test_intel_iris_xe(self):
        result = detect_gpu("Lenovo ThinkPad X280 Iris Xe")
        self.assertIn("Iris Xe", result)

    def test_intel_uhd(self):
        result = detect_gpu("Dell Latitude Intel UHD 620")
        self.assertIn("UHD", result)

    def test_amd_radeon(self):
        result = detect_gpu("AMD Radeon RX 6600M")
        self.assertIn("Radeon", result)

    def test_no_gpu(self):
        self.assertEqual(detect_gpu("MacBook Air M1 8GB 256GB"), "")


class LaptopParserRamTests(SimpleTestCase):
    def test_16gb_ram(self):
        self.assertEqual(detect_ram_gb("16GB RAM 1TB SSD"), 16)

    def test_ram_16gb(self):
        self.assertEqual(detect_ram_gb("RAM 16GB SSD 512"), 16)

    def test_16gb_standalone(self):
        self.assertEqual(detect_ram_gb("16GB 512GB SSD"), 16)

    def test_8gb(self):
        self.assertEqual(detect_ram_gb("8 256 MacBook Air M1"), 8)

    def test_24gb(self):
        self.assertEqual(detect_ram_gb("24GB RAM 1TB SSD"), 24)

    def test_32gb(self):
        self.assertEqual(detect_ram_gb("32GB DDR5 1TB NVMe"), 32)

    def test_1tb_not_ram(self):
        """1TB must never become ram_gb=1."""
        ram = detect_ram_gb("1TB SSD")
        # Should not be 1
        if ram is not None:
            self.assertNotEqual(ram, 1)

    def test_512gb_not_ram(self):
        """512GB SSD must never become ram_gb=512."""
        ram = detect_ram_gb("512GB SSD")
        if ram is not None:
            self.assertNotEqual(ram, 512)

    def test_16_512_slash(self):
        self.assertEqual(detect_ram_gb("16/512"), 16)


class LaptopParserStorageTests(SimpleTestCase):
    def test_512gb_ssd(self):
        self.assertEqual(detect_storage_gb("512GB SSD"), 512)

    def test_1tb_ssd(self):
        self.assertEqual(detect_storage_gb("1TB SSD"), 1024)

    def test_2tb(self):
        self.assertEqual(detect_storage_gb("2TB NVMe"), 2048)

    def test_256gb(self):
        self.assertEqual(detect_storage_gb("256GB NVMe SSD"), 256)

    def test_16_512_slash(self):
        self.assertEqual(detect_storage_gb("16/512"), 512)

    def test_ssd_1tb(self):
        self.assertEqual(detect_storage_gb("SSD 1TB"), 1024)


class LaptopParserFullTests(SimpleTestCase):
    """Full parse_laptop tests matching the spec requirements."""

    def test_macbook_air_m1(self):
        result = parse_laptop("MacBook Air M1 8GB 256GB")
        self.assertEqual(result["brand_text"], "Apple")
        self.assertIn("M1", result["cpu"])
        self.assertEqual(result["ram_gb"], 8)
        self.assertEqual(result["storage_gb"], 256)

    def test_macbook_pro_m2(self):
        result = parse_laptop("Macbook Pro M2 16 RAM 1TB SSD")
        self.assertEqual(result["brand_text"], "Apple")
        self.assertIn("M2", result["cpu"])
        self.assertEqual(result["ram_gb"], 16)
        self.assertEqual(result["storage_gb"], 1024)

    def test_lenovo_thinkpad_x280(self):
        result = parse_laptop("Lenovo ThinkPad X280 i5 8 RAM 256 M2 SSD")
        self.assertEqual(result["brand_text"], "Lenovo")
        self.assertIn("i5", result["cpu"])
        self.assertEqual(result["ram_gb"], 8)
        self.assertEqual(result["storage_gb"], 256)
        # Must NOT detect Apple M2
        self.assertNotIn("M2", result["cpu"])

    def test_asus_tuf_a15(self):
        result = parse_laptop("ASUS TUF A15 Ryzen 7 RTX 3060 16GB 512SSD")
        self.assertEqual(result["brand_text"], "ASUS")
        self.assertIn("Ryzen 7", result["cpu"])
        self.assertIn("RTX 3060", result["gpu"])
        self.assertEqual(result["ram_gb"], 16)
        self.assertEqual(result["storage_gb"], 512)

    def test_hp_victus(self):
        result = parse_laptop("HP Victus i5 RTX 4050 16/512")
        self.assertEqual(result["brand_text"], "HP")
        self.assertIn("i5", result["cpu"])
        self.assertIn("RTX 4050", result["gpu"])
        self.assertEqual(result["ram_gb"], 16)
        self.assertEqual(result["storage_gb"], 512)

    def test_serialized_cdp_payload_does_not_pollute_model(self):
        raw = (
            'MacBook Pro M4 - Pil Devri 111 '
            '{"source": "sahibinden_cdp", "category": "laptops", '
            '"cell_cpu": "Apple M4", "cell_ram": "16 GB"}'
        )
        result = parse_laptop(raw, "MacBook Pro M4 - Pil Devri 111", {})
        self.assertEqual(result["brand_text"], "Apple")
        self.assertNotIn("cell", result["model_text"].lower())
        self.assertNotIn("source", result["model_text"].lower())
        self.assertEqual(result["ram_gb"], 16)


# ---------------------------------------------------------------------------
# Canonicalization tests
# ---------------------------------------------------------------------------

class LaptopCanonicalizationTests(SimpleTestCase):
    def test_macbook_air_casing(self):
        result = normalize_laptop_model_name("Apple", "MACBOOK AİR M1")
        self.assertEqual(result, "MacBook Air M1")

    def test_macbook_air_with_size(self):
        result = normalize_laptop_model_name("Apple", "Macbook Air 13 M1")
        self.assertEqual(result, "MacBook Air M1")

    def test_macbook_pro_m2(self):
        result = normalize_laptop_model_name("Apple", "MACBOOK PRO 13 M2")
        self.assertEqual(result, "MacBook Pro M2")

    def test_macbook_pro_m4_pro(self):
        result = normalize_laptop_model_name("Apple", "MacBook Pro M4 Pro")
        self.assertEqual(result, "MacBook Pro M4 Pro")

    def test_lenovo_legion_5(self):
        result = normalize_laptop_model_name("Lenovo", "LENOVO LEGION 5")
        self.assertEqual(result, "Legion 5")

    def test_legion5_no_space(self):
        result = normalize_laptop_model_name("Lenovo", "Legion5")
        self.assertEqual(result, "Legion 5")

    def test_lenovo_legion_5_with_specs(self):
        result = normalize_laptop_model_name("Lenovo", "Lenovo Legion 5 Ryzen 7")
        self.assertEqual(result, "Legion 5")

    def test_thinkpad_x280(self):
        result = normalize_laptop_model_name("Lenovo", "THINKPAD X280")
        self.assertEqual(result, "ThinkPad X280")

    def test_lenovo_thinkpad_x280(self):
        result = normalize_laptop_model_name("Lenovo", "Lenovo ThinkPad X280")
        self.assertEqual(result, "ThinkPad X280")

    def test_asus_tuf_a15(self):
        result = normalize_laptop_model_name("ASUS", "ASUS TUF A15")
        self.assertEqual(result, "TUF A15")

    def test_tuf_gaming_a15(self):
        result = normalize_laptop_model_name("ASUS", "TUF GAMING A15")
        self.assertEqual(result, "TUF A15")

    def test_rog_strix(self):
        result = normalize_laptop_model_name("ASUS", "ROG STRIX G15")
        self.assertEqual(result, "ROG Strix G15")

    def test_hp_victus(self):
        result = normalize_laptop_model_name("HP", "HP VICTUS")
        self.assertEqual(result, "Victus")

    def test_dell_xps_13(self):
        result = normalize_laptop_model_name("Dell", "DELL XPS 13")
        self.assertEqual(result, "XPS 13")

    def test_air_vs_pro_not_merged(self):
        air = normalize_laptop_model_name("Apple", "MacBook Air M1")
        pro = normalize_laptop_model_name("Apple", "MacBook Pro M1")
        self.assertNotEqual(air, pro)

    def test_apple_merge_key_preserves_chip_generation(self):
        key1 = laptop_model_merge_key("Apple", "MacBook Air")
        key2 = laptop_model_merge_key("Apple", "MacBook Air M1")
        self.assertNotEqual(key1, key2)

    def test_a15_vs_f15_not_merged(self):
        a15 = normalize_laptop_model_name("ASUS", "TUF A15")
        f15 = normalize_laptop_model_name("ASUS", "TUF F15")
        self.assertNotEqual(a15, f15)

    def test_legion5_vs_legion5pro_not_merged(self):
        l5 = normalize_laptop_model_name("Lenovo", "Legion 5")
        l5pro = normalize_laptop_model_name("Lenovo", "Legion 5 Pro")
        self.assertNotEqual(l5, l5pro)

    def test_thinkpad_x280_vs_t480_not_merged(self):
        x280 = normalize_laptop_model_name("Lenovo", "ThinkPad X280")
        t480 = normalize_laptop_model_name("Lenovo", "ThinkPad T480")
        self.assertNotEqual(x280, t480)

    def test_turkish_i_in_model_name(self):
        result = normalize_laptop_model_name("Lenovo", "THİNKPAD X280")
        self.assertEqual(result, "ThinkPad X280")

    def test_merge_key_ignores_brand_prefix(self):
        key1 = laptop_model_merge_key("Lenovo", "Lenovo Legion 5")
        key2 = laptop_model_merge_key("Lenovo", "Legion 5")
        self.assertEqual(key1, key2)

    def test_merge_key_turkish_i(self):
        key1 = laptop_model_merge_key("Lenovo", "Legion 5")
        key2 = laptop_model_merge_key("Lenovo", "LEGİON 5")
        self.assertEqual(key1, key2)


class LaptopCpuNormalizationTests(SimpleTestCase):
    def test_intel_i7_full(self):
        self.assertEqual(normalize_cpu_family("Intel Core i7-12700H"), "intel_core_i7")

    def test_intel_i5_short(self):
        self.assertEqual(normalize_cpu_family("i5"), "intel_core_i5")

    def test_amd_ryzen_7(self):
        self.assertEqual(normalize_cpu_family("AMD Ryzen 7 5800H"), "amd_ryzen_7")

    def test_apple_m2(self):
        self.assertEqual(normalize_cpu_family("Apple M2"), "apple_m2")

    def test_empty(self):
        self.assertEqual(normalize_cpu_family(""), "")


class LaptopGpuNormalizationTests(SimpleTestCase):
    def test_rtx_3060(self):
        self.assertEqual(normalize_gpu_family("NVIDIA RTX 3060"), "nvidia_rtx_3060")

    def test_gtx_1650(self):
        self.assertEqual(normalize_gpu_family("NVIDIA GTX 1650"), "nvidia_gtx_1650")

    def test_iris_xe(self):
        self.assertEqual(normalize_gpu_family("Intel Iris Xe"), "intel_iris_xe")

    def test_empty(self):
        self.assertEqual(normalize_gpu_family(""), "")


class LaptopSignatureTests(SimpleTestCase):
    def test_same_spec_same_signature(self):
        sig1 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7 5800H", "NVIDIA RTX 3060", 16, 512)
        sig2 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7 5800H", "NVIDIA RTX 3060", 16, 512)
        self.assertEqual(sig1, sig2)

    def test_different_ram_different_signature(self):
        sig1 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7", "NVIDIA RTX 3060", 16, 512)
        sig2 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7", "NVIDIA RTX 3060", 32, 512)
        self.assertNotEqual(sig1, sig2)

    def test_different_gpu_different_signature(self):
        sig1 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7", "NVIDIA RTX 3060", 16, 512)
        sig2 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7", "NVIDIA RTX 4060", 16, 512)
        self.assertNotEqual(sig1, sig2)

    def test_different_model_different_signature(self):
        sig1 = build_laptop_signature("Lenovo", "Legion 5", "AMD Ryzen 7", "NVIDIA RTX 3060", 16, 512)
        sig2 = build_laptop_signature("Lenovo", "Legion 5 Pro", "AMD Ryzen 7", "NVIDIA RTX 3060", 16, 512)
        self.assertNotEqual(sig1, sig2)


# ---------------------------------------------------------------------------
# Merge command tests
# ---------------------------------------------------------------------------

class MergeDuplicateLaptopModelsTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="Lenovo")

    def _create_model(self, name, listing_count=0):
        model = LaptopModel.objects.create(
            brand=self.brand,
            canonical_name=name,
        )
        for i in range(listing_count):
            LaptopListing.objects.create(
                source_type=SourceType.OUEDKNISS,
                country=Country.ALGERIA,
                laptop_model=model,
                title=f"Listing {i}",
                price_original=Decimal("500"),
                currency_original="EUR",
                price_eur=Decimal("500"),
                listing_url=f"https://example.com/{name}/{i}",
            )
        return model

    def test_dry_run_no_mutation(self):
        m1 = self._create_model("Legion 5", listing_count=2)
        m2 = self._create_model("LENOVO LEGION 5", listing_count=1)
        out = StringIO()

        call_command("merge_duplicate_laptop_models", stdout=out)

        self.assertEqual(LaptopModel.objects.count(), 2)
        self.assertIn("Dry-run only", out.getvalue())

    def test_apply_merges_models(self):
        m1 = self._create_model("Legion 5", listing_count=2)
        m2 = self._create_model("LENOVO LEGION 5", listing_count=1)
        out = StringIO()

        call_command("merge_duplicate_laptop_models", "--apply", stdout=out)

        self.assertEqual(LaptopModel.objects.count(), 1)
        remaining = LaptopModel.objects.first()
        self.assertEqual(remaining.canonical_name, "Legion 5")
        self.assertEqual(remaining.aliases, ["LENOVO LEGION 5"])

    def test_apply_moves_listings(self):
        m1 = self._create_model("Legion 5", listing_count=2)
        m2 = self._create_model("LENOVO LEGION 5", listing_count=1)
        out = StringIO()

        call_command("merge_duplicate_laptop_models", "--apply", stdout=out)

        remaining = LaptopModel.objects.first()
        self.assertEqual(LaptopListing.objects.filter(laptop_model=remaining).count(), 3)

    def test_apply_moves_variants(self):
        m1 = self._create_model("Legion 5")
        m2 = self._create_model("LENOVO LEGION 5")
        v1 = LaptopVariant.objects.create(
            laptop_model=m1,
            cpu="Ryzen 7",
            gpu="RTX 3060",
            ram_gb=16,
            storage_gb=512,
            canonical_label="Ryzen 7 RTX 3060 16GB 512GB",
        )
        out = StringIO()

        call_command("merge_duplicate_laptop_models", "--apply", stdout=out)

        remaining = LaptopModel.objects.first()
        v1.refresh_from_db()
        self.assertEqual(v1.laptop_model, remaining)

    def test_brand_filter(self):
        Brand.objects.create(name="Apple")
        self._create_model("MacBook Air M1")
        m2 = LaptopModel.objects.create(
            brand=Brand.objects.get(name="Apple"),
            canonical_name="MACBOOK AIR M1",
        )
        out = StringIO()

        call_command("merge_duplicate_laptop_models", "--brand=Apple", "--apply", stdout=out)

        self.assertEqual(LaptopModel.objects.filter(brand__name="Apple").count(), 1)

    def test_apple_merge_skips_noisy_family_fragments(self):
        apple = Brand.objects.create(name="Apple")
        LaptopModel.objects.create(brand=apple, canonical_name="MacBook Pro")
        LaptopModel.objects.create(brand=apple, canonical_name="Macbook Pro")
        LaptopModel.objects.create(brand=apple, canonical_name="Macbook Pro 14 M5 cip")
        LaptopModel.objects.create(brand=apple, canonical_name="Macbook Pro Max")
        out = StringIO()

        call_command("merge_duplicate_laptop_models", "--brand=Apple", "--apply", stdout=out)

        self.assertEqual(LaptopModel.objects.filter(brand=apple).count(), 3)
        self.assertTrue(LaptopModel.objects.filter(brand=apple, canonical_name="Macbook Pro 14 M5 cip").exists())
        self.assertTrue(LaptopModel.objects.filter(brand=apple, canonical_name="Macbook Pro Max").exists())

    def test_no_duplicates_shows_zero(self):
        self._create_model("Legion 5")
        out = StringIO()

        call_command("merge_duplicate_laptop_models", stdout=out)

        self.assertIn("Duplicate groups found: 0", out.getvalue())


class CleanupLaptopListingsTests(TestCase):
    def test_apply_repairs_garbage_model_from_clean_candidate(self):
        brand = Brand.objects.create(name="Apple")
        bad_model = LaptopModel.objects.create(
            brand=brand,
            canonical_name="gpu ram gb storage gb",
        )
        raw = RawListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            category_hint=RawListing.CategoryHint.LAPTOPS,
            title_raw="MacBook Air M2 8GB 256GB",
            raw_text="MacBook Air M2 8GB 256GB",
            listing_url="https://example.com/macbook-cleanup",
        )
        ParsedListingCandidate.objects.create(
            raw_listing=raw,
            detected_category=ParsedListingCandidate.DetectedCategory.LAPTOP,
            brand_text="Apple",
            model_text="MacBook Air M2",
            laptop_specs_json={
                "cpu": "Apple M2",
                "gpu": "Apple Integrated",
                "ram_gb": 8,
                "storage_gb": 256,
                "series": "Macbook Air",
            },
            confidence=0.85,
            status=ParsedListingCandidate.Status.PENDING,
            matched_brand=brand,
        )
        listing = LaptopListing.objects.create(
            raw_listing=raw,
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            laptop_model=bad_model,
            title="gpu ram gb storage gb",
            price_eur=Decimal("800"),
            review_status=LaptopListing.ReviewStatus.NEEDS_REVIEW,
        )

        out = StringIO()
        call_command("cleanup_laptop_listings", "--only-garbage", "--apply", "--no-backup", stdout=out)

        listing.refresh_from_db()
        self.assertEqual(listing.laptop_model.canonical_name, "MacBook Air M2")
        self.assertEqual(listing.ram_gb, 8)
        self.assertEqual(listing.storage_gb, 256)
        self.assertEqual(listing.review_status, LaptopListing.ReviewStatus.NEEDS_REVIEW)


# ---------------------------------------------------------------------------
# Opportunity tests
# ---------------------------------------------------------------------------

class RecomputeLaptopOpportunitiesV2Tests(TestCase):
    def setUp(self):
        self.lenovo = Brand.objects.create(name="Lenovo")
        self.legion5 = LaptopModel.objects.create(
            brand=self.lenovo,
            canonical_name="Legion 5",
        )
        self.legion5pro = LaptopModel.objects.create(
            brand=self.lenovo,
            canonical_name="Legion 5 Pro",
        )
        self.algeria_source = Source.objects.create(
            name="Ouedkniss",
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            username="ouedkniss-test-laptop",
        )
        self.tr_source = Source.objects.create(
            name="Sahibinden",
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            username="sahibinden-test-laptop",
        )

    def create_laptop(self, *, country, source_type, model, cpu, gpu, ram, storage, eur, status=None):
        source = self.algeria_source if country == Country.ALGERIA else self.tr_source
        return LaptopListing.objects.create(
            source=source,
            source_type=source_type,
            country=country,
            laptop_model=model,
            cpu=cpu,
            gpu=gpu,
            ram_gb=ram,
            storage_gb=storage,
            title=f"{model.canonical_name} {cpu} {gpu} {ram}GB {storage}GB",
            price_original=Decimal(str(eur)),
            currency_original="EUR",
            price_eur=Decimal(str(eur)),
            review_status=status or LaptopListing.ReviewStatus.NEEDS_REVIEW,
            listing_url=f"https://example.com/{country}/{model.pk}/{ram}/{storage}/{eur}",
        )

    def test_same_spec_creates_opportunity(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7 5800H",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7 5800H",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "Legion 5")
        self.assertEqual(rows[0]["margin_eur"], Decimal("300.00"))
        self.assertEqual(rows[0]["margin_percent"], Decimal("50.00"))

    def test_different_ram_no_match(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=32,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(len(rows), 0)

    def test_different_gpu_no_match(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 4060",
            ram=16,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(len(rows), 0)

    def test_different_model_no_match(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5pro,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(len(rows), 0)

    def test_missing_turkiye_side_skipped(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(rows, [])

    def test_min_margin_filter(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="800",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="850",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows(min_margin_eur=Decimal("100"))

        self.assertEqual(rows, [])

    def test_only_approved_excludes_needs_review(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
            status=LaptopListing.ReviewStatus.NEEDS_REVIEW,
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
            status=LaptopListing.ReviewStatus.NEEDS_REVIEW,
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows(only_approved=True)

        self.assertEqual(rows, [])

    def test_command_outputs_table(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )
        out = StringIO()

        call_command("recompute_laptop_opportunities_v2", stdout=out)

        text = out.getvalue()
        self.assertIn("Clean laptop opportunity rows: 1", text)
        self.assertIn("Legion 5", text)
        self.assertIn("300.00", text)

    def test_export_json(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )
        out = StringIO()

        call_command(
            "recompute_laptop_opportunities_v2",
            "--export-json=/tmp/test_laptop_opps.json",
            stdout=out,
        )

        import json
        from pathlib import Path
        data = json.loads(Path("/tmp/test_laptop_opps.json").read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["model"], "Legion 5")

    def test_write_snapshots(self):
        from market.clean_models import LaptopOpportunitySnapshot

        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )
        out = StringIO()

        call_command("recompute_laptop_opportunities_v2", "--write-snapshots", stdout=out)

        self.assertEqual(LaptopOpportunitySnapshot.objects.count(), 1)
        snapshot = LaptopOpportunitySnapshot.objects.first()
        self.assertEqual(snapshot.model, "Legion 5")
        self.assertEqual(snapshot.gross_margin_eur, Decimal("300.00"))

    def test_loose_matching(self):
        """Loose matching ignores CPU/GPU and only matches on model + RAM + storage."""
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="AMD Ryzen 7 5800H",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="Intel Core i7-12700H",
            gpu="NVIDIA RTX 4060",
            ram=16,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows(loose=True)

        self.assertEqual(len(rows), 1)

    def test_model_and_ram_without_storage_is_not_exported(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="",
            gpu="",
            ram=16,
            storage=None,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="",
            gpu="",
            ram=16,
            storage=None,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows(loose=True)

        self.assertEqual(rows, [])

    def test_garbage_model_name_is_not_exported(self):
        bad_model = LaptopModel.objects.create(
            brand=self.lenovo,
            canonical_name="gpu ram gb storage gb",
        )
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=bad_model,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=bad_model,
            cpu="AMD Ryzen 7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=512,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(rows, [])

    def test_nonstandard_storage_bucket_is_not_exported(self):
        self.create_laptop(
            country=Country.ALGERIA,
            source_type=SourceType.OUEDKNISS,
            model=self.legion5,
            cpu="Intel Core i7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=750,
            eur="600",
        )
        self.create_laptop(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            model=self.legion5,
            cpu="Intel Core i7",
            gpu="NVIDIA RTX 3060",
            ram=16,
            storage=750,
            eur="900",
        )

        from market.management.commands.recompute_laptop_opportunities_v2 import compute_laptop_opportunity_rows
        rows = compute_laptop_opportunity_rows()

        self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# Identity key tests
# ---------------------------------------------------------------------------

class LaptopIdentityKeyTests(SimpleTestCase):
    def test_identity_key_deterministic(self):
        k1 = build_laptop_variant_identity("i5-1235U", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        k2 = build_laptop_variant_identity("i5-1235U", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        self.assertEqual(k1, k2)

    def test_identity_key_differs_by_cpu(self):
        k1 = build_laptop_variant_identity("i5", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        k2 = build_laptop_variant_identity("i7", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        self.assertNotEqual(k1, k2)

    def test_identity_key_differs_by_gpu(self):
        k1 = build_laptop_variant_identity("i5", "RTX 3060", 8, 256, 15.6, "1920x1080", 60)
        k2 = build_laptop_variant_identity("i5", "RTX 4060", 8, 256, 15.6, "1920x1080", 60)
        self.assertNotEqual(k1, k2)

    def test_identity_key_differs_by_ram(self):
        k1 = build_laptop_variant_identity("i5", "RTX 3060", 8, 256, 15.6, "1920x1080", 60)
        k2 = build_laptop_variant_identity("i5", "RTX 3060", 16, 256, 15.6, "1920x1080", 60)
        self.assertNotEqual(k1, k2)


# ---------------------------------------------------------------------------
# Signal-based category detection tests
# ---------------------------------------------------------------------------

class DetectCategoryFromSignalsTests(SimpleTestCase):
    """Tests for URL/title-based category detection."""

    def test_ouedkniss_laptop_url(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/laptop-lenovo-legion-pro-5-16iax10h-intel-core-ultra-9-275hx-32go-1to-ssd-rtx-5070-ti-12go-16-qhd-oled-240hz-windows-11-kouba-alger-algeria-d56318119"
        self.assertEqual(detect_category_from_signals(url=url), "laptop")

    def test_ouedkniss_macbook_url(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/macbooks-macbook-air-m2-8g-512g-beni-messous-algeria-d53425136"
        self.assertEqual(detect_category_from_signals(url=url), "laptop")

    def test_ouedkniss_keyboard_mouse_url(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/keyboard-mouse-souris-gaming-lenovo-legion-m500-rgb"
        self.assertEqual(detect_category_from_signals(url=url), "accessory")

    def test_ouedkniss_consoles_url(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/consoles-lenovo-legion-go-z1-extreme-512gb"
        self.assertEqual(detect_category_from_signals(url=url), "portable_console")

    def test_ouedkniss_headphones_url(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/headphones-sony-wh1000xm5"
        self.assertEqual(detect_category_from_signals(url=url), "accessory")

    def test_title_laptop_keyword(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="Lenovo Legion Pro 5 laptop"), "laptop")

    def test_title_macbook_keyword(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="MacBook Air M2"), "laptop")

    def test_title_thinkpad_keyword(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="ThinkPad X280 i5"), "laptop")

    def test_title_rog_keyword(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="ASUS ROG Strix G15"), "laptop")

    def test_title_souris_is_accessory(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="Souris Gaming Lenovo Legion M500"), "accessory")

    def test_title_clavier_is_accessory(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="Clavier sans fil HP"), "accessory")

    def test_title_chargeur_is_accessory(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(title="Chargeur USB-C Dell"), "accessory")

    def test_no_signal_returns_empty(self):
        from market.services.parsing.candidate_builder import detect_category_from_signals
        self.assertEqual(detect_category_from_signals(url="", title=""), "")
        self.assertEqual(detect_category_from_signals(url="", title="Generic item"), "")

    def test_url_laptop_overrides_title_accessory(self):
        """URL /laptop- is definitive even if title has accessory words."""
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/laptop-lenovo-legion"
        title = "Clavier Lenovo Legion"
        self.assertEqual(detect_category_from_signals(url=url, title=title), "laptop")

    def test_url_accessor_overrides_title_laptop(self):
        """URL accessory pattern wins over title laptop keyword."""
        from market.services.parsing.candidate_builder import detect_category_from_signals
        url = "https://www.ouedkniss.com/keyboard-mouse-lenovo-legion"
        title = "Lenovo Legion laptop"
        self.assertEqual(detect_category_from_signals(url=url, title=title), "accessory")


# ---------------------------------------------------------------------------
# Build candidate signal override tests (integration)
# ---------------------------------------------------------------------------

class BuildCandidateSignalOverrideTests(TestCase):
    """Test that build_candidate properly overrides category_hint using signals."""

    def _make_raw(self, **kwargs):
        defaults = {
            "source_type": SourceType.OUEDKNISS,
            "country": Country.ALGERIA,
            "category_hint": RawListing.CategoryHint.PHONES,
            "listing_url": "",
            "title_raw": "",
            "raw_text": "",
            "content_hash=": "abc123",
        }
        defaults.update(kwargs)
        content_hash = defaults.pop("content_hash=", "abc123")
        raw = RawListing(**defaults)
        raw.content_hash = content_hash
        raw.save()
        return raw

    def test_ouedkniss_laptop_url_overrides_phone_hint(self):
        """Ouedkniss laptop URL with category_hint=phones should become laptop."""
        raw = self._make_raw(
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/laptop-lenovo-legion-pro-5-16iax10h-intel-core-ultra-9-275hx-32go-1to-ssd-rtx-5070-ti-12go-16-qhd-oled-240hz-windows-11-kouba-alger-algeria-d56318119",
            title_raw="LENOVO LEGION PRO 5 16IRX10 - INTEL i9-14900HX - 32GO DDR5 - 1TO SSD - 16\" WQXGA - RTX 5070",
            raw_text="LENOVO LEGION PRO 5 16IRX10 - INTEL i9-14900HX - 32GO DDR5 - 1TO SSD - RTX 5070 - 16 WQXGA 240Hz",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, created = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)
        self.assertEqual(candidate.brand_text, "Lenovo")

    def test_ouedkniss_macbook_url_overrides_phone_hint(self):
        """Ouedkniss MacBook URL with category_hint=phones should become laptop."""
        raw = self._make_raw(
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/macbooks-macbook-air-m2-8g-512g-beni-messous-algeria-d53425136",
            title_raw="MacBook Air M2 8G 512G",
            raw_text="MacBook Air M2 8GB 512GB SSD",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, created = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.LAPTOP)
        self.assertEqual(candidate.brand_text, "Apple")

    def test_ouedkniss_accessory_url_becomes_unknown(self):
        """Accessory URL should not be classified as laptop or phone."""
        raw = self._make_raw(
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/keyboard-mouse-souris-gaming-lenovo-legion-m500-rgb",
            title_raw="Souris Gaming Lenovo Legion M500 RGB",
            raw_text="Souris Gaming Lenovo Legion M500 RGB",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, created = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.UNKNOWN)

    def test_ouedkniss_console_url_becomes_portable_console(self):
        """Portable console URL should not be classified as laptop."""
        raw = self._make_raw(
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/consoles-lenovo-legion-go-z1-extreme-512gb",
            title_raw="Lenovo Legion Go Z1 Extreme 512gb",
            raw_text="Lenovo Legion Go Z1 Extreme 512gb",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, created = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE)
        self.assertEqual(candidate.brand_text, "Lenovo")
        self.assertEqual(candidate.model_text, "Legion Go")
        self.assertEqual(candidate.console_specs_json["storage_gb"], 512)

    def test_phone_hint_stays_phone_when_no_laptop_signal(self):
        """Normal phone listing with phone hint stays phone."""
        raw = self._make_raw(
            category_hint=RawListing.CategoryHint.PHONES,
            listing_url="https://www.ouedkniss.com/samsung-galaxy-s24",
            title_raw="Samsung Galaxy S24 256GB",
            raw_text="Samsung Galaxy S24 256GB Dual SIM",
        )
        from market.services.parsing.candidate_builder import build_candidate
        candidate, created = build_candidate(raw)
        self.assertEqual(candidate.detected_category, ParsedListingCandidate.DetectedCategory.PHONE)
