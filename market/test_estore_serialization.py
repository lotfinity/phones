import json

from django.core.serializers.json import DjangoJSONEncoder
from django.test import SimpleTestCase

from market.clean_models import PhoneOpportunitySnapshot
from market.views_estore_bagisto import _json_payload


class EstorePayloadSerializationTests(SimpleTestCase):
    def test_model_instances_are_removed_from_embedded_json_payload(self):
        snapshot = PhoneOpportunitySnapshot(
            brand="Samsung",
            model="Serialization Test",
        )

        payload = _json_payload(
            {
                "item": snapshot,
                "nested": [snapshot],
                "title": "Samsung Serialization Test",
            }
        )

        self.assertNotIn("item", payload)
        self.assertEqual(payload["nested"], [])
        self.assertEqual(payload["title"], "Samsung Serialization Test")

        # This is the same encoder used by the Bagisto source renderer.
        json.dumps(payload, cls=DjangoJSONEncoder)
