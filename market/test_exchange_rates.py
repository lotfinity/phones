from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from market.models import CurrencyRate
from market.services.currency import dzd_to_eur, eur_to_try, usd_to_eur


class FetchExchangeRatesCommandTests(TestCase):
    @patch("market.management.commands.fetch_exchange_rates.requests.get")
    def test_saves_public_rates_and_manual_black_market_dzd_rate(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "base": "EUR",
            "date": "2026-07-09",
            "rates": {"TRY": "48.25", "USD": "1.1725"},
        }
        mock_get.return_value = response

        out = StringIO()
        call_command(
            "fetch_exchange_rates",
            "--dzd-per-eur-black",
            "295",
            stdout=out,
        )

        self.assertEqual(CurrencyRate.objects.count(), 4)
        self.assertEqual(
            CurrencyRate.objects.get(base_currency="EUR", quote_currency="TRY").rate,
            Decimal("48.250000"),
        )
        self.assertEqual(
            CurrencyRate.objects.get(base_currency="EUR", quote_currency="USD").rate,
            Decimal("1.172500"),
        )
        self.assertEqual(
            CurrencyRate.objects.get(base_currency="USD", quote_currency="TRY").rate,
            Decimal("41.151386"),
        )
        dzd_rate = CurrencyRate.objects.get(base_currency="EUR", quote_currency="DZD")
        self.assertEqual(dzd_rate.rate, Decimal("295.000000"))
        self.assertEqual(dzd_rate.source, "manual:black_market")
        self.assertIn("Saved 4 FX rate rows", out.getvalue())

    @patch("market.management.commands.fetch_exchange_rates.requests.get")
    def test_latest_db_rates_are_used_by_currency_helpers(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "base": "EUR",
            "date": "2026-07-09",
            "rates": {"TRY": "48.25", "USD": "1.1725"},
        }
        mock_get.return_value = response

        call_command("fetch_exchange_rates", "--dzd-per-eur-black", "295", stdout=StringIO())

        self.assertEqual(eur_to_try(Decimal("10")), Decimal("482.50"))
        self.assertEqual(usd_to_eur(Decimal("100")), Decimal("85.29"))
        self.assertEqual(dzd_to_eur(Decimal("29500")), Decimal("100.00"))

    @patch("market.management.commands.fetch_exchange_rates.requests.get")
    def test_dry_run_does_not_write_rows(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "base": "EUR",
            "date": "2026-07-09",
            "rates": {"TRY": "48.25", "USD": "1.1725"},
        }
        mock_get.return_value = response

        out = StringIO()
        call_command("fetch_exchange_rates", "--dry-run", stdout=out)

        self.assertEqual(CurrencyRate.objects.count(), 0)
        self.assertIn("Would save EUR/TRY", out.getvalue())
