import unittest

from reporting.professional_builder import build_professional_post_close_report
from reporting.professional_schema import ProfessionalPostCloseReport, compute_content_sha256


class ProfessionalReportBuilderTests(unittest.TestCase):
    def _metadata(self):
        return {
            "schema_version": 2,
            "report_type": "post_close",
            "product_mode": "observation",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-17T10:30:00Z",
            "data_as_of": "2026-07-17",
            "source_manifest": "quant/v1/manifests/TW-20260717T091000Z-123456789abc.json",
            "source_manifest_sha256": "a" * 64,
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "content": {
                "market_observation": {
                    "return_1d_pct": -0.72,
                    "advancing_count": 520,
                    "declining_count": 812,
                    "ma20_breadth_pct": 39.7,
                    "realized_volatility_20d_pct": 18.2,
                },
                "industry_observations": [
                    {"name": "半導體製造", "available_count": 6, "component_count": 6, "relative_return_5d_pct": 4.31},
                    {"name": "航運", "available_count": 8, "component_count": 9, "relative_return_5d_pct": -3.20},
                ],
                "heatmap": [],
                "stock_events": [
                    {"symbol": "2330", "name": "台積電", "observation": "量能異常", "as_of": "2026-07-17", "metric_value": 1.4, "unit": "倍"}
                ],
                "etf_observations": [
                    {"symbol": "0050", "name": "元大台灣50", "price": 205.2, "return_1d_pct": -0.6, "return_5d_pct": 1.1}
                ],
                "daily_focus": ["市場廣度降至四成以下", "半導體相對大盤偏強"],
                "data_quality": {
                    "coverage": 0.982,
                    "symbol_count": 1332,
                    "failure_count": 24,
                },
            },
        }

    def test_builds_canonical_report_from_verified_observation_metadata(self):
        report = build_professional_post_close_report(
            self._metadata(), code_commit_sha="b" * 40
        )
        document = report.to_document()

        self.assertIsInstance(report, ProfessionalPostCloseReport)
        self.assertEqual(document["identity"]["product_tier"], "institutional")
        self.assertEqual(document["identity"]["product_mode"], "observation_with_research")
        self.assertEqual(document["executive_summary"]["market_state"], "提高防守")
        self.assertEqual(document["executive_summary"]["strongest_industries"], ["半導體製造"])
        self.assertEqual(document["executive_summary"]["weakest_industries"], ["航運"])
        self.assertEqual(document["industries"]["data"]["ranking"][0]["name"], "半導體製造")
        self.assertEqual(document["validation"]["data"]["gates"]["promotion"], "BLOCKED")
        self.assertEqual(document["validation"]["data"]["gates"]["ranking"], "UNAVAILABLE")
        self.assertFalse(document["validation"]["data"]["probability_allowed"])
        self.assertEqual(document["quantitative_research"]["status"], "unavailable")
        self.assertEqual(document["ai_reference"]["status"], "unavailable")
        self.assertEqual(document["identity"]["content_sha256"], compute_content_sha256(document))

    def test_preserves_missing_market_values_as_none(self):
        metadata = self._metadata()
        metadata["content"]["market_observation"]["realized_volatility_20d_pct"] = None
        report = build_professional_post_close_report(metadata, code_commit_sha="b" * 40)
        self.assertIsNone(report.market.data["realized_volatility_20d_pct"])

    def test_rejects_pre_market_metadata(self):
        metadata = self._metadata()
        metadata["report_type"] = "pre_market"
        with self.assertRaisesRegex(ValueError, "post_close"):
            build_professional_post_close_report(metadata, code_commit_sha="b" * 40)

    def test_rejects_probability_enabled_metadata(self):
        metadata = self._metadata()
        metadata["prediction_capability"]["probability_allowed"] = True
        with self.assertRaisesRegex(ValueError, "probability"):
            build_professional_post_close_report(metadata, code_commit_sha="b" * 40)


if __name__ == "__main__":
    unittest.main()
