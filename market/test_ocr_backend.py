from django.test import SimpleTestCase, override_settings

from market.parsers.ocr_backend import NvidiaVisionBackend, get_ocr_backend


class OCRBackendSelectionTests(SimpleTestCase):
    @override_settings(NVIDIA_API_KEY="test-key")
    def test_get_ocr_backend_uses_nvidia(self):
        self.assertIsInstance(get_ocr_backend("nvidia"), NvidiaVisionBackend)

    def test_deprecated_ocr_backend_names_fail(self):
        with self.assertRaisesMessage(RuntimeError, "deprecated"):
            get_ocr_backend("tesseract")


class NvidiaVisionBackendCleanupTests(SimpleTestCase):
    @override_settings(NVIDIA_API_KEY="test-key")
    def test_prompt_requests_main_sale_category(self):
        backend = NvidiaVisionBackend()

        prompt = backend._build_prompt()

        self.assertIn('"category": "phone|laptop|console|accessory|unknown"', prompt)
        self.assertIn('"ram_gb": null', prompt)
        self.assertIn("Return ONLY strict JSON", prompt)
        self.assertIn("Classify the main sale item only", prompt)

    @override_settings(NVIDIA_API_KEY="test-key")
    def test_json_response_is_flattened_for_existing_parser(self):
        backend = NvidiaVisionBackend()

        text = backend._clean_text(
            '{"category":"phone","brand":"Apple","model":"iPhone 17 Pro","storage":"256GB","battery_health":91,'
            '"condition":"used clean","color":"black","price_text":"185000 DA",'
            '"visible_text":"Garantie 6 mois"}'
        )

        self.assertIn("Category: phone", text)
        self.assertIn("Brand: Apple", text)
        self.assertIn("Model: iPhone 17 Pro", text)
        self.assertIn("Storage: 256GB", text)
        self.assertIn("Battery: 91", text)
        self.assertIn("Condition: used clean", text)
        self.assertIn("Color: black", text)
        self.assertIn("Price: 185000 DA", text)

    @override_settings(NVIDIA_API_KEY="test-key")
    def test_json_response_preserves_structured_payload(self):
        backend = NvidiaVisionBackend()

        data = backend._json_to_data(
            '{"category":"phone","brand":"Apple","model":"iPhone 15",'
            '"storage_gb":128,"ram_gb":null,"price":{"amount":77000,"currency":"DZD"}}'
        )

        self.assertEqual(data["storage_gb"], 128)
        self.assertIsNone(data["ram_gb"])
