import datetime
import json
import tempfile
import unittest
from pathlib import Path

from absorb.conversation.tools import normalize_stock_analysis
from stock_papi.batch.backtest_store import BacktestStore, BacktestStoreError
from stock_papi.batch.oos_diagnostics import (
    _calibration_challengers,
    _challenger_record,
    _partition_dates,
)
from stock_papi.integrations.line.flex import build_stock_flex_message
from stock_papi.services.model_evidence import (
    sanitize_analysis,
    sanitize_public_report,
)


def _all_text(value):
    if isinstance(value, dict):
        return " ".join(_all_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_all_text(item) for item in value)
    return str(value)


class BootstrapEvidenceTests(unittest.TestCase):
    def test_failed_calibration_or_quality_never_promotes(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BacktestStore(temporary, "TW")
            for gates in (
                {
                    "parity": True,
                    "leakage": True,
                    "calibration": False,
                    "schema": True,
                    "security": True,
                    "quality": True,
                },
                {
                    "parity": True,
                    "leakage": True,
                    "calibration": True,
                    "schema": True,
                    "security": True,
                    "quality": False,
                },
            ):
                with self.assertRaises(BacktestStoreError):
                    store.promote(
                        "a" * 64,
                        gates=gates,
                        promoted_at=datetime.datetime.now(datetime.timezone.utc),
                    )
            self.assertFalse(store.latest_path.exists())

    def test_bootstrap_analysis_has_score_low_confidence_and_no_performance(self):
        raw = {
            "code": "2330",
            "name": "台積電",
            "price": 100.0,
            "prob": 81,
            "as_of": "2026-07-15",
            "trend": "多頭",
            "s_score": 50.0,
            "s_status": "中性",
            "recommendation": {
                "action": "優先關注",
                "confidence": "可信度高",
                "supporting_reasons": ["五日上漲機率 81%"],
            },
            "bt": {"accuracy": 60.0, "win_rate": 58.0, "trades": 100},
        }
        safe = sanitize_analysis(
            raw, {"baseline_status": "initial_backtest_bootstrap"}
        )
        self.assertEqual(safe["model_output_label"], "模型方向分數")
        self.assertEqual(safe["direction_score"], 81)
        self.assertFalse(safe["strong_action_allowed"])
        self.assertFalse(safe["performance_endorsement_allowed"])
        self.assertEqual(safe["recommendation"]["action"], "等待確認")
        self.assertEqual(safe["recommendation"]["confidence"], "可信度低")
        self.assertEqual(safe["bt"]["trades"], 0)
        self.assertNotIn("%", safe["recommendation"]["supporting_reasons"][0])

    def test_validated_baseline_restores_probability(self):
        safe = sanitize_analysis(
            {"prob": 63, "recommendation": {"action": "分批觀察"}},
            {"baseline_status": "validated_compatible"},
        )
        normalized = normalize_stock_analysis(safe)
        self.assertEqual(safe["model_output_label"], "五日上漲機率")
        self.assertTrue(safe["strong_action_allowed"])
        self.assertEqual(normalized["five_day_probability"], 0.63)
        self.assertIsNone(normalized["model_direction_score"])

    def test_line_report_and_conversation_share_bootstrap_semantics(self):
        safe = sanitize_analysis(
            {
                "market": "TW",
                "code": "2330",
                "name": "台積電",
                "price": 100.0,
                "prob": 81,
                "as_of": "2026-07-15",
                "trend": "多頭",
                "s_score": 50.0,
                "s_status": "中性",
                "recommendation": {
                    "action": "優先關注",
                    "headline": "積極選股",
                    "supporting_reasons": ["五日上漲機率 81%"],
                },
            },
            {"baseline_status": "initial_backtest_bootstrap"},
        )
        line_text = _all_text(
            build_stock_flex_message(
                "2330", "台積電", safe, "https://example.com/stock/2330"
            )
        )
        report = sanitize_public_report(
            {
                "stocks": [
                    {
                        "symbol": "2330",
                        "probability": 81,
                        "action": "優先關注",
                        "supporting_reasons": ["五日上漲機率 81%"],
                    }
                ]
            },
            "initial_backtest_bootstrap",
        )
        conversation = normalize_stock_analysis(safe)
        self.assertIn("模型方向分數", line_text)
        self.assertIn("尚未完成機率校準驗證", line_text)
        self.assertNotIn("優先關注", line_text)
        self.assertEqual(report["stocks"][0]["action"], "等待確認")
        self.assertNotIn("probability", report["stocks"][0])
        self.assertIsNone(conversation["five_day_probability"])
        self.assertEqual(conversation["model_direction_score"], 0.81)
        self.assertFalse(conversation["strong_action_allowed"])

    def test_no_traffic_deployment_checklist_is_fail_closed(self):
        script = (
            Path(__file__).parents[1] / "scripts" / "deploy_preview.ps1"
        ).read_text(encoding="utf-8")
        for required in (
            "--no-traffic",
            "--tag",
            "ABSORB_PREVIEW_CANDIDATE_PREFIX",
            "--if-generation-match=0",
            "production_traffic_percent = 0",
            "gcs_production_latest_updated = $false",
            "line_production_updated = $false",
        ):
            self.assertIn(required, script)
        self.assertNotIn("latest-TW.json", script)
        self.assertNotIn("broadcast", script.lower())

    def test_calibration_selection_never_uses_final_holdout(self):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        rows = []
        for index, date in enumerate(
            pd.date_range("2025-01-01", periods=80, freq="B")
        ):
            target = rng.integers(0, 2, size=30)
            score = np.clip(0.2 + target * 0.55 + rng.normal(0, 0.12, 30), 0.01, 0.99)
            rows.extend(
                {
                    "source_market_date": date.date().isoformat(),
                    "direction": int(label),
                    "probability": float(probability),
                }
                for label, probability in zip(target, score)
            )
        frame = pd.DataFrame(rows)
        partitions = _partition_dates(frame)
        result = _calibration_challengers(frame, partitions)
        self.assertFalse(partitions["selection_uses_final_holdout"])
        self.assertEqual(result["selection_partition"], "validation")
        self.assertEqual(result["final_evaluation_partition"], "final_holdout")
        self.assertIn(result["selected_before_final_holdout"], {"platt", "isotonic", "beta"})

    def test_challenger_artifact_disables_automatic_promotion(self):
        partitions = {
            "calibration_train": ["2025-01-01", "2025-01-02"],
            "validation": ["2025-01-08", "2025-01-09"],
            "final_holdout": ["2025-01-15", "2025-01-16"],
            "purge_sessions": 5,
            "selection_uses_final_holdout": False,
        }
        candidate = {
            "model_version": "lgbm-5d-v1",
            "feature_schema_version": 1,
            "recommendation_policy_version": "recommendation-v1",
        }
        record = _challenger_record(
            candidate,
            partitions,
            name="relative_market_excess",
            target_definition="relative return > 0",
            metrics={"validation": {}, "final_holdout": {}},
            generated_at="2026-07-16T00:00:00Z",
        )
        self.assertFalse(record["gate_result"]["promotion_eligible"])
        self.assertEqual(record["gate_result"]["automatic_promotion"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
