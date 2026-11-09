import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from stock_papi.shared.validation import is_us_ticker
from stock_papi.web.routes.market import register_market_routes
from tests.test_stock_quote import NOW, document
from stock_papi.services.stock_quote import parse_quote


class QuoteRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        names = (
            "analyze stock_observation dashboard_sector_cards cached_opportunities "
            "build_market_heatmap dashboard_top_picks industry_map market_insights_payload "
            "find_industry_peers get_stock_name dashboard_snapshot us_securities_observation "
            "prediction_snapshot"
        ).split()
        self.dependencies = {name: Mock() for name in names}
        register_market_routes(
            self.app, **self.dependencies, is_us_ticker=is_us_ticker,
            twstock_codes=lambda: {"2330": SimpleNamespace(exchange="TWSE"), "6488": SimpleNamespace(exchange="TPEx")},
        )
        self.client = self.app.test_client()

    def test_quote_refresh_does_not_run_analysis_or_load_snapshots(self):
        with patch("stock_papi.web.routes.market.QuoteCache.get", return_value=parse_quote(document(), "2330.TW", NOW)) as get:
            response = self.client.get("/api/stock/2330/quote")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["code"], "2330")
        self.assertEqual(response.json["price"], 100.5)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        get.assert_called_once_with("2330.TW")
        for dependency in self.dependencies.values():
            dependency.assert_not_called()

    def test_invalid_symbol_never_reaches_provider(self):
        with patch("stock_papi.web.routes.market.QuoteCache.get") as get:
            self.assertEqual(self.client.get("/api/stock/1234/quote").status_code, 404)
            self.assertEqual(self.client.get("/api/stock/AAPL%3Fx/quote").status_code, 404)
        get.assert_not_called()

    def test_uppercase_us_and_otc_mapping(self):
        with patch("stock_papi.web.routes.market.QuoteCache.get", return_value={"status": "unavailable", "refresh_seconds": 300}) as get:
            self.client.get("/api/stock/aapl/quote")
            get.assert_called_with("AAPL")
            response = self.client.get("/api/stock/6488/quote")
            get.assert_called_with("6488.TWO")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "300")
