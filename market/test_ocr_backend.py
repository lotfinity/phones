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
    def test_json_response_is_flattened_for_existing_parser(self):
        backend = NvidiaVisionBackend()

        text = backend._clean_text(
            '{"model":"iPhone 17 Pro","storage":"256GB","battery_health":91,'
            '"condition":"used clean","color":"black","price_text":"185000 DA",'
            '"visible_text":"Garantie 6 mois"}'
        )

        self.assertIn("Model: iPhone 17 Pro", text)
        self.assertIn("Storage: 256GB", text)
        self.assertIn("Battery: 91", text)
        self.assertIn("Condition: used clean", text)
        self.assertIn("Color: black", text)
        self.assertIn("Price: 185000 DA", text)
