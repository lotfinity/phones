from django.test import SimpleTestCase

from market.services.brand_logos import brand_logo_url


class BrandLogoHelperTests(SimpleTestCase):
    def test_known_simple_icon_brand_returns_cdn_url(self):
        self.assertEqual(brand_logo_url("Apple"), "https://cdn.simpleicons.org/apple")

    def test_missing_simple_icon_brand_uses_fallback(self):
        self.assertIsNone(brand_logo_url("Microsoft"))
