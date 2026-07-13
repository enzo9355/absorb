import unittest

import app as stock_app


COMPATIBILITY_EXPORTS = (
    "analyze",
    "fetch_market_insights",
    "fetch_published_quant_snapshot",
    "dashboard_sector_cards",
    "industry_map",
    "line_store",
    "_gcs_get_allowed_object",
    "_published_quant_manifest",
    "build_stock_flex_message",
    "build_watchlist_flex",
    "build_alerts_flex",
    "build_line_navigation_flex",
    "handle_message",
    "handle_postback",
    "run_alert_checks",
)


class AppCompatibilityTests(unittest.TestCase):
    def test_legacy_test_and_script_exports_remain_available(self):
        for name in COMPATIBILITY_EXPORTS:
            with self.subTest(name=name):
                self.assertTrue(hasattr(stock_app, name), name)


if __name__ == "__main__":
    unittest.main()
