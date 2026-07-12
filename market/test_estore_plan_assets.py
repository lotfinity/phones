from django.test import TestCase
from django.urls import reverse


class EstorePurchasePlanAssetsTests(TestCase):
    def test_opportunity_index_loads_local_plan_assets(self):
        response = self.client.get(reverse("estore_opportunity_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pricebridge-plan.css")
        self.assertContains(response, "pricebridge-plan.js")
        self.assertContains(response, 'id="pricebridge-opportunity-data"')

    def test_plan_script_uses_currency_scoped_local_storage(self):
        response = self.client.get(
            reverse("estore_opportunity_index"),
            {"currency": "TRY"},
        )

        self.assertContains(response, '"selected_currency":"TRY"')
        self.assertContains(response, "pricebridge-plan.js")
