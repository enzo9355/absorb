import json
import sys
import types
import unittest

try:
    import linebot.models  # noqa: F401
except ModuleNotFoundError:
    linebot = types.ModuleType("linebot")
    models = types.ModuleType("linebot.models")
    for name in ("MessageAction", "QuickReply", "QuickReplyButton"):
        setattr(models, name, type(name, (), {}))
    linebot.models = models
    sys.modules["linebot"] = linebot
    sys.modules["linebot.models"] = models

from stock_papi.integrations.line.flex import (
    build_stock_flex_message,
    build_line_navigation_flex,
    build_tutorial_flex,
    build_welcome_flex,
)
from stock_papi.integrations.line.presentation import (
    build_industry_carousel,
    build_sector_signal_carousel,
)


class AbsorbLinePresentationTests(unittest.TestCase):
    def test_core_flex_fixtures_are_absorb_json(self):
        for fixture in (
            build_welcome_flex(),
            build_tutorial_flex(),
            build_line_navigation_flex("https://example.com"),
            build_industry_carousel("半導體", ["2330"], lambda _code: "台積電"),
            build_sector_signal_carousel("半導體", [{
                "code": "2330", "name": "台積電", "prob": 63,
                "trend": "多頭", "foreign_net_5": 1000,
                "score": 70.0, "as_of": "2026-07-15",
            }], 5),
        ):
            payload = json.dumps(fixture, ensure_ascii=False)
            with self.subTest(kind=fixture["type"]):
                self.assertIn("ABSORB", payload)
                self.assertNotRegex(payload, r"(?i)Stock[ -]?Papi|Papillon|AI QUANT|蝴蝶|老爸")
                self.assertNotIn("#39c6a3", payload.lower())
                payload_lower = payload.lower()
                self.assertTrue("#122643" in payload_lower or "#17151a" in payload_lower)

    def test_press_block_cards_use_press_palette_without_emoji(self):
        stock_data = {
            "price": 1000.0,
            "prob": 68,
            "trend": "多頭",
            "s_score": 55.0,
            "s_status": "中性",
            "as_of": "2026-07-15",
            "recommendation": {"action": "等待確認", "headline": "觀察後續訊號"},
        }
        payload = json.dumps(
            (
                build_stock_flex_message(
                    "2330", "台積電", stock_data, "https://example.com/stock/2330"
                ),
                build_welcome_flex(),
                build_tutorial_flex(),
                build_line_navigation_flex("https://example.com"),
            ),
            ensure_ascii=False,
        ).lower()

        self.assertIn("#17151a", payload)
        for legacy_color in ("#122643", "#64748b", "#0f172a", "#f8fafc"):
            self.assertNotIn(legacy_color, payload)
        for emoji in ("💰", "📈", "🌡", "🎯", "⚠️", "🎓", "1️⃣", "2️⃣", "3️⃣", "4️⃣"):
            self.assertNotIn(emoji, payload)


if __name__ == "__main__":
    unittest.main()
