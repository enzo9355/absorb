import unittest

import app as stock_app
from stock_papi.integrations.line import flex


class LineFlexCompatibilityTests(unittest.TestCase):
    def test_root_exports_use_canonical_presentation_builders(self):
        for name in (
            "build_stock_flex_message",
            "build_watchlist_flex",
            "build_alerts_flex",
            "build_alert_menu_flex",
            "build_calculator_menu_flex",
            "build_strong_signals_flex",
            "build_alert_push_flex",
            "build_line_summary_card",
            "build_line_navigation_flex",
            "build_calculator_help_flex",
            "build_welcome_flex",
            "build_tutorial_flex",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(stock_app, name), getattr(flex, name))

    def test_representative_payloads_keep_existing_shape(self):
        empty = flex.build_watchlist_flex({"watchlist": []}, "https://example.com")
        self.assertEqual(empty["type"], "bubble")
        self.assertIn("尚未加入關注股票", str(empty))

        navigation = flex.build_line_navigation_flex("https://example.com/")
        self.assertEqual(navigation["type"], "carousel")
        self.assertEqual(len(navigation["contents"]), 6)


if __name__ == "__main__":
    unittest.main()
