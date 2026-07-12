from django.test import TestCase
from django.urls import reverse

from market.models import (
    Brand,
    ConsoleListing,
    ConsoleModel,
    LaptopListing,
    LaptopModel,
    PhoneListing,
    PhoneModel,
)


class EstoreListingViewsTests(TestCase):
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

        cls.phone = PhoneListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            phone_model=phone_model,
            title="iPhone 15 Pro 256 GB",
            price_original="145000",
            currency_original="DZD",
            price_eur="520",
            condition="used_a",
            storage_gb=256,
            battery_health=91,
            review_status="approved",
            listing_url="https://example.com/iphone",
            image_url="https://example.com/iphone.webp",
        )
        cls.laptop = LaptopListing.objects.create(
            source_type="ouedkniss",
            country="algeria",
            laptop_model=laptop_model,
            title="ROG Zephyrus 16",
            price_original="250000",
            currency_original="DZD",
            price_eur="900",
            condition="used_a_plus",
            cpu="Ryzen 9",
            gpu="RTX 4070",
            ram_gb=32,
            storage_gb=1024,
            review_status="approved",
        )
        cls.console = ConsoleListing.objects.create(
            source_type="sahibinden",
            country="turkiye",
            console_model=console_model,
            title="Steam Deck OLED 1 TB",
            price_original="32000",
            currency_original="TRY",
            price_eur="710",
            condition="used",
            storage_gb=1024,
            review_status="approved",
        )

    def test_new_estore_index_contains_all_listing_categories(self):
        response = self.client.get(reverse("estore_listing_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPhone 15 Pro 256 GB")
        self.assertContains(response, "ROG Zephyrus 16")
        self.assertContains(response, "Steam Deck OLED 1 TB")

    def test_estore_category_filter_is_isolated(self):
        response = self.client.get(
            reverse("estore_listing_index"),
            {"category": "phone"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPhone 15 Pro 256 GB")
        self.assertNotContains(response, "ROG Zephyrus 16")
        self.assertNotContains(response, "Steam Deck OLED 1 TB")

    def test_estore_search_filters_listing_cards(self):
        response = self.client.get(
            reverse("estore_listing_index"),
            {"q": "Zephyrus"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ROG Zephyrus 16")
        self.assertNotContains(response, "Steam Deck OLED 1 TB")

    def test_phone_detail_renders_real_fields_and_proxy_image(self):
        response = self.client.get(
            reverse(
                "estore_listing_detail",
                kwargs={"category": "phone", "pk": self.phone.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPhone 15 Pro 256 GB")
        self.assertContains(response, "Batarya")
        self.assertContains(response, "91%")
        self.assertContains(
            response,
            reverse(
                "clean_listing_image",
                kwargs={"category": "phone", "pk": self.phone.pk},
            ),
        )
        self.assertContains(response, "https://example.com/iphone")

    def test_laptop_and_console_detail_routes_render(self):
        for category, listing, title in (
            ("laptop", self.laptop, "ROG Zephyrus 16"),
            ("console", self.console, "Steam Deck OLED 1 TB"),
        ):
            with self.subTest(category=category):
                response = self.client.get(
                    reverse(
                        "estore_listing_detail",
                        kwargs={"category": category, "pk": listing.pk},
                    )
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)

    def test_unknown_detail_category_returns_404(self):
        response = self.client.get("/estore/listing/tablet/1/")
        self.assertEqual(response.status_code, 404)

    def test_rejected_listing_is_not_exposed(self):
        self.phone.review_status = "rejected"
        self.phone.save(update_fields=["review_status"])

        index_response = self.client.get(reverse("estore_listing_index"))
        detail_response = self.client.get(
            reverse(
                "estore_listing_detail",
                kwargs={"category": "phone", "pk": self.phone.pk},
            )
        )

        self.assertNotContains(index_response, self.phone.title)
        self.assertEqual(detail_response.status_code, 404)
