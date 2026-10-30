import datetime
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_papi.integrations.market_data import us_market_data as market_data
from stock_papi.batch.us_official_post_close_cli import _fetch_and_classify_symbol


class UhaulIssuerHistoryTests(unittest.TestCase):
    target = datetime.date(2026, 10, 29)

    def setUp(self):
        self.fetch = getattr(market_data, "fetch_uhaul_historical_chart", None)
        self.assertTrue(callable(self.fetch), "issuer history fallback is missing")
        self.row = {
            "HistoricalDate": "10/29/2026 05:00:00", "Open": 49.27,
            "High": 50.11, "Low": 48.23, "Last": 50.11, "Volume": 448738,
        }

    def response(self, rows):
        return json.dumps({"GetStockQuoteHistoricalListResult": rows}).encode()

    def test_exact_share_class_and_complete_source_provenance(self):
        raw = self.response([self.row])
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as request:
            result = self.fetch("UHAL-B", target_market_date=self.target)
        self.assertIn("symbol=UHAL%2FB", request.call_args.args[0].full_url)
        self.assertIn("exchange=XNYS", request.call_args.args[0].full_url)
        self.assertEqual(result.loc[self.target, "Close"], 50.11)
        self.assertEqual(result.loc[self.target, "Volume"], 448738)
        self.assertEqual(result.attrs["payload_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result.attrs["provider_symbol"], "UHAL/B")

    def test_rejects_missing_invalid_future_and_stale_data(self):
        for changes in [
            {"Last": None}, {"High": 48.0}, {"Volume": -1},
            {"HistoricalDate": "10/30/2026 05:00:00"},
            {"HistoricalDate": "10/28/2026 05:00:00"},
        ]:
            with self.subTest(changes=changes), patch(
                "urllib.request.urlopen", return_value=io.BytesIO(self.response([{**self.row, **changes}]))
            ), self.assertRaises((market_data.USSchemaError, market_data.USIntegrityError)):
                self.fetch("UHAL-B", target_market_date=self.target)

    def test_other_share_class_never_uses_this_source(self):
        with patch("urllib.request.urlopen") as request, self.assertRaises(market_data.USSchemaError):
            self.fetch("UHAL", target_market_date=self.target)
        request.assert_not_called()

    def test_classifier_uses_issuer_only_after_existing_sources_fail(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_us_stock_history",
            side_effect=market_data.USSchemaError("missing Close"),
        ), patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_nasdaq_historical_chart",
            side_effect=market_data.USSchemaError("no Nasdaq data"),
        ), patch("urllib.request.urlopen", return_value=io.BytesIO(self.response([self.row]))):
            result = _fetch_and_classify_symbol(Path(root), "UHAL-B", self.target)
        self.assertEqual(result.kind, "R")
        source = result.provider_result["secondary_fallback"]
        self.assertEqual(source["source_id"], "uhaul:issuer-history")
        self.assertEqual(source["previous_fallback_failure"]["error_type"], "USSchemaError")

    def test_failed_issuer_data_still_blocks_publication(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_us_stock_history",
            side_effect=market_data.USSchemaError("missing Close"),
        ), patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_nasdaq_historical_chart",
            side_effect=market_data.USSchemaError("no Nasdaq data"),
        ), patch("urllib.request.urlopen", return_value=io.BytesIO(self.response([{**self.row, "Last": None}]))):
            result = _fetch_and_classify_symbol(Path(root), "UHAL-B", self.target)
        self.assertEqual(result.kind, "OP_FAIL")
        self.assertEqual(result.provider_result["issuer_failure"]["error_type"], "USSchemaError")

    def test_other_symbols_do_not_use_issuer_fallback(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_us_stock_history",
            side_effect=market_data.USSchemaError("missing Close"),
        ), patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_nasdaq_historical_chart",
            side_effect=market_data.USSchemaError("no Nasdaq data"),
        ), patch("stock_papi.batch.us_official_post_close_cli.fetch_uhaul_historical_chart") as issuer:
            result = _fetch_and_classify_symbol(Path(root), "UHAL", self.target)
        self.assertEqual(result.kind, "OP_FAIL")
        issuer.assert_not_called()
