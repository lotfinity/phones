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
        self.assertIn('"no_sale_data_reason": ""', prompt)
        self.assertIn('"scene_description": ""', prompt)
        self.assertIn("Return ONLY strict JSON", prompt)
        self.assertIn("Classify the main sale item only", prompt)
        self.assertIn("set no_sale_data_reason", prompt)

    @override_settings(NVIDIA_API_KEY="test-key")
    def test_json_response_is_flattened_for_existing_parser(self):
        backend = NvidiaVisionBackend()

        text = backend._clean_text(
            '{"category":"phone","brand":"Apple","model":"iPhone 17 Pro","storage":"256GB","battery_health":91,'
            '"condition":"used clean","color":"black","price_text":"185000 DA",'
            '"no_sale_data_reason":"","scene_description":"","visible_text":"Garantie 6 mois"}'
        )

        self.assertIn("Category: phone", text)
        self.assertIn("Brand: Apple", text)
        self.assertIn("Model: iPhone 17 Pro", text)
        self.assertIn("Storage: 256GB", text)
        self.assertIn("Battery: 91", text)
        self.assertIn("Condition: used clean", text)
        self.assertIn("Color: black", text)
        self.assertIn("Price: 185000 DA", text)
        self.assertNotIn("No sale data reason:", text)

    @override_settings(NVIDIA_API_KEY="test-key")
    def test_no_sale_json_is_flattened_with_reason_and_description(self):
        backend = NvidiaVisionBackend()

        text = backend._clean_text(
            '{"category":"unknown","brand":"","model":"","storage_gb":null,"ram_gb":null,'
            '"price":{"amount":null,"currency":"DZD","raw":""},'
            '"no_sale_data_reason":"many devices, no single priced item",'
            '"scene_description":"Store shelf with multiple boxed phones and no clear listing.",'
            '"visible_text":["GTD DEGHOUL GROUP TELECOM"]}'
        )

        self.assertIn("Category: unknown", text)
        self.assertIn("No sale data reason: many devices, no single priced item", text)
        self.assertIn("Scene description: Store shelf with multiple boxed phones", text)

    @override_settings(NVIDIA_API_KEY="test-key")
    def test_json_response_preserves_structured_payload(self):
        backend = NvidiaVisionBackend()

        data = backend._json_to_data(
            '{"category":"phone","brand":"Apple","model":"iPhone 15",'
            '"storage_gb":128,"ram_gb":null,"price":{"amount":77000,"currency":"DZD"}}'
        )

        self.assertEqual(data["storage_gb"], 128)
        self.assertIsNone(data["ram_gb"])
