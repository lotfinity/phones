import json

from django.core.serializers.json import DjangoJSONEncoder
from django.test import SimpleTestCase

from market.bagisto_source import _safe_json


class EstorePayloadSerializationTests(SimpleTestCase):
    def test_runtime_config_json_is_html_safe(self):
        payload = _safe_json(
            {
                "page": "opportunity-detail",
                "api_url": "/estore/api/opportunities/phone/1/?q=<script>",
                "title": "Samsung & PriceBridge",
            }
        )

        self.assertNotIn("<script>", payload)
        self.assertIn("\\u003cscript\\u003e", payload)
        self.assertIn("\\u0026", payload)

        # This is the same encoder class used by the Bagisto source renderer.
        json.dumps(json.loads(payload), cls=DjangoJSONEncoder)
