import datetime
import unittest

from stock_papi.services.recommendation_engine import (
    RecommendationInput,
    build_recommendation,
    recommend_analysis,
)
from stock_papi.integrations.line.flex import build_stock_flex_message


TODAY = datetime.date(2026, 7, 13)


def stock_input(**changes):
    values = {
        "scope": "stock",
        "entity_id": "2330",
        "probability": 68.0,
        "trend": "多頭",
        "data_as_of": TODAY,
        "current_date": TODAY,
        "rsi": 58.0,
        "volume_ratio": 1.2,
        "foreign_net_5": 1200.0,
        "volatility": 0.02,
        "sample_count": 60,
        "industry_coverage": 0.9,
        "rotation": "leading",
        "near_rotation_boundary": False,
        "market_action": "積極選股",
        "data_quality_warning": False,
        "source_disagreement": False,
        "max_drawdown": -0.12,
        "strategy_return": 0.18,
        "buy_hold_return": 0.08,
    }
    values.update(changes)
    return RecommendationInput(**values)


class RecommendationEngineTests(unittest.TestCase):
    def test_strong_aligned_stock_signal_can_be_priority(self):
        result = build_recommendation(stock_input())

        self.assertEqual(result.action, "優先布局")
        self.assertEqual(result.confidence, "相對完整")
        self.assertIn("五日上漲機率 68%", result.supporting_reasons)
        self.assertIn("站上 MA20", result.supporting_reasons)
        self.assertEqual(result.source_metrics["probability"], 68.0)

    def test_overheated_stock_is_downgraded(self):
        result = build_recommendation(stock_input(rsi=72.0))

        self.assertEqual(result.action, "分批布局")
        self.assertIn("RSI 72，短線偏熱", result.risk_reasons)

    def test_model_and_trend_divergence_waits_for_confirmation(self):
        result = build_recommendation(stock_input(trend="空頭"))

        self.assertEqual(result.action, "等待確認")
        self.assertIn("模型機率與 MA20 趨勢分歧", result.risk_reasons)

    def test_low_sample_blocks_strong_action(self):
        result = build_recommendation(stock_input(sample_count=8))

        self.assertEqual(result.action, "等待確認")
        self.assertEqual(result.confidence, "可信度低")
        self.assertIn("相似歷史訊號少於 12 次", result.risk_reasons)

    def test_stale_data_blocks_strong_action_without_misclassifying_weekend(self):
        monday = datetime.date(2026, 7, 13)
        friday = datetime.date(2026, 7, 10)
        tuesday = datetime.date(2026, 7, 14)

        fresh = build_recommendation(
            stock_input(data_as_of=friday, current_date=monday)
        )
        stale = build_recommendation(
            stock_input(data_as_of=friday, current_date=tuesday)
        )

        self.assertEqual(fresh.action, "優先布局")
        self.assertEqual(stale.action, "等待確認")
        self.assertIn("資料已超過一個市場工作日", stale.risk_reasons)

    def test_defensive_market_downgrades_stock_action(self):
        result = build_recommendation(stock_input(market_action="提高防守"))

        self.assertEqual(result.action, "分批布局")
        self.assertIn("整體市場目前提高防守", result.risk_reasons)

    def test_industry_near_rotation_boundary_is_not_priority(self):
        result = build_recommendation(
            stock_input(
                scope="industry",
                entity_id="半導體",
                probability=65.0,
                trend="多頭",
                sample_count=30,
                industry_coverage=0.92,
                rotation="leading",
                near_rotation_boundary=True,
            )
        )

        self.assertEqual(result.action, "分批觀察")
        self.assertIn("產業接近輪動分界", result.risk_reasons)

    def test_market_scope_uses_market_labels(self):
        bullish = build_recommendation(
            stock_input(scope="market", entity_id="TAIEX", sample_count=60)
        )
        defensive = build_recommendation(
            stock_input(
                scope="market",
                entity_id="TAIEX",
                probability=42.0,
                trend="空頭",
                sample_count=60,
            )
        )

        self.assertEqual(bullish.action, "積極選股")
        self.assertEqual(defensive.action, "提高防守")

    def test_missing_probability_fails_closed(self):
        result = build_recommendation(
            stock_input(probability=None, trend=None, data_as_of=None)
        )

        self.assertEqual(result.action, "等待確認")
        self.assertEqual(result.level, "insufficient")
        self.assertEqual(result.confidence, "可信度低")
        self.assertIn("五日上漲機率缺失", result.risk_reasons)
        self.assertIn("資料截止日期缺失", result.risk_reasons)

    def test_same_input_is_deterministic_and_serializable(self):
        source = stock_input()

        first = build_recommendation(source).to_dict()
        second = build_recommendation(source).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(first["data_as_of"], "2026-07-13")
        self.assertIsInstance(first["supporting_reasons"], list)

    def test_analysis_adapter_and_line_flex_use_same_result(self):
        data = {
            "code": "2330",
            "name": "台積電",
            "price": 1000.0,
            "prob": 68,
            "trend": "多頭",
            "as_of": TODAY.isoformat(),
            "rsi": 58.0,
            "volume_ratio": 1.2,
            "volatility": 0.02,
            "data_quality_warning": False,
            "foreign_flow": {"net_5": 1200.0},
            "bt": {
                "trades": 60,
                "mdd": -12.0,
                "strat_cum": 18.0,
                "bh_cum": 8.0,
            },
            "s_score": 55.0,
            "s_status": "中性",
        }
        result = recommend_analysis(data, current_date=TODAY)
        data["recommendation"] = result.to_dict()

        flex = build_stock_flex_message(
            "2330", "台積電", data, "https://example.com/stock/2330"
        )
        serialized = str(flex)

        self.assertEqual(data["recommendation"], result.to_dict())
        self.assertIn(result.action, serialized)
        self.assertIn(result.headline, serialized)


if __name__ == "__main__":
    unittest.main()
