import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from stock_papi.batch.daily_products import build_daily_products, write_daily_candidate


class DailyProductsTests(unittest.TestCase):
    def test_candidate_persists_dashboard_sector_and_report_without_cutover(self):
        stock = SimpleNamespace(
            symbol="2330",
            name="台積電",
            latest={"AI_P": 63.5, "Close": 1000.0, "MA20": 980.0},
        )
        report = SimpleNamespace(
            source=SimpleNamespace(
                manifest=SimpleNamespace(market_as_of=datetime.date(2026, 7, 15)),
                stocks=[stock],
            ),
            industries=[SimpleNamespace(
                name="半導體",
                symbols=["2330"],
                average_probability=63.5,
                component_count=1,
                coverage=1.0,
                rotation="leading",
                near_boundary=False,
            )],
            backtests=[SimpleNamespace(industry="半導體", valid_signals=0)],
        )
        baseline = {
            "status": "validated_compatible",
            "backtest_as_of": "2026-07-09",
            "backtest_version": "b" * 64,
            "model_version": "lgbm-5d-v1",
            "feature_schema_version": 1,
            "recommendation_policy_version": "recommendation-v1",
            "mismatch_fields": [],
        }
        metadata = {
            "schema_version": 2,
            "report_type": "post_close",
            "market": "TW",
            "source_market_date": "2026-07-15",
            "applicable_trading_date": "2026-07-16",
            "published_at": "2026-07-15T10:00:00Z",
            "forecast_start_date": "2026-07-16",
            "forecast_end_date": "2026-07-22",
            "backtest_as_of": "2026-07-09",
            "data_as_of": "2026-07-15",
            "source_manifest": "quant/v1/manifests/TW-20260715T100000Z-aaaaaaaaaaaa.json",
            "source_manifest_sha256": "a" * 64,
            "model_versions": {"lgbm-5d-v1": 1},
            "title": "盤後報告",
            "summary": ["市場整理"],
            "warnings": [],
            "content": {"public_report": {}, "baseline": baseline},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dashboard = build_daily_products(report, metadata, baseline)
            candidate = write_daily_candidate(root, metadata, dashboard)

            self.assertEqual(json.loads((candidate / "dashboard-snapshot.json").read_text(encoding="utf-8"))["inference_as_of"], "2026-07-15")
            self.assertTrue((candidate / "sector-snapshot.json").is_file())
            self.assertTrue((candidate / "post-close-report-v2.json").is_file())
            self.assertFalse((root / "publish" / "dashboard" / "v1" / "latest-TW.json").exists())

    def test_bootstrap_candidate_uses_observation_language_and_no_endorsement(self):
        stock = SimpleNamespace(
            symbol="2330",
            name="台積電",
            latest={"AI_P": 81.2, "Close": 1000.0, "MA20": 980.0},
        )
        report = SimpleNamespace(
            source=SimpleNamespace(
                manifest=SimpleNamespace(market_as_of=datetime.date(2026, 7, 15)),
                stocks=[stock],
            ),
            industries=[
                SimpleNamespace(
                    name="半導體",
                    symbols=["2330"],
                    average_probability=81.2,
                    component_count=1,
                    coverage=1.0,
                    rotation="leading",
                    near_boundary=False,
                )
            ],
            backtests=[SimpleNamespace(industry="半導體", valid_signals=0)],
        )
        baseline = {
            "status": "initial_backtest_bootstrap",
            "backtest_as_of": None,
            "backtest_version": None,
            "model_version": "lgbm-5d-v1",
            "feature_schema_version": 1,
            "recommendation_policy_version": "recommendation-v1",
            "mismatch_fields": ["validated_backtest_baseline"],
        }
        metadata = {
            "schema_version": 2,
            "report_type": "post_close",
            "market": "TW",
            "source_market_date": "2026-07-15",
            "applicable_trading_date": "2026-07-16",
            "published_at": "2026-07-15T10:00:00Z",
            "forecast_start_date": "2026-07-16",
            "forecast_end_date": "2026-07-22",
            "backtest_as_of": None,
            "data_as_of": "2026-07-15",
            "source_manifest": "quant/v1/manifests/TW-20260715T100000Z-aaaaaaaaaaaa.json",
            "source_manifest_sha256": "a" * 64,
            "model_versions": {"lgbm-5d-v1": 1},
            "title": "盤後報告",
            "summary": ["機率變化 3 個百分點"],
            "warnings": [],
            "content": {
                "public_report": {
                    "stocks": [
                        {
                            "symbol": "2330",
                            "probability": 81.2,
                            "action": "優先關注",
                            "supporting_reasons": ["五日上漲機率 81.2%"],
                        }
                    ]
                },
                "baseline": baseline,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            dashboard = build_daily_products(report, metadata, baseline)
            candidate = write_daily_candidate(temporary, metadata, dashboard)
            saved_dashboard = json.loads(
                (candidate / "dashboard-snapshot.json").read_text(encoding="utf-8")
            )
            saved_report = json.loads(
                (candidate / "post-close-report-v2.json").read_text(encoding="utf-8")
            )
        self.assertEqual(
            saved_dashboard["presentation"]["top_picks_label"], "量化觀察名單"
        )
        self.assertFalse(saved_dashboard["presentation"]["strong_action_allowed"])
        self.assertEqual(
            saved_dashboard["top_picks"][0]["model_output_label"], "模型方向分數"
        )
        stock_report = saved_report["content"]["public_report"]["stocks"][0]
        self.assertNotIn("probability", stock_report)
        self.assertEqual(stock_report["direction_score"], 81.2)
        self.assertEqual(stock_report["action"], "等待確認")
        self.assertIsNone(
            saved_report["content"]["public_report"]["model_quality"]["direction_accuracy"]
        )


if __name__ == "__main__":
    unittest.main()
