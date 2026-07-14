import datetime
import unittest

from stock_papi.batch.backtest_store import REQUIRED_PROMOTION_GATES
from stock_papi.batch.weekly_model import WeeklyModelReportError, build_weekly_model_report


UTC = datetime.timezone.utc


def promoted_backtest():
    return {
        "candidate_sha256": "c" * 64,
        "promoted_at": "2026-07-14T11:00:00Z",
        "gates": {gate: True for gate in REQUIRED_PROMOTION_GATES},
        "model_version": "lgbm-5d-v1",
        "dataset_manifest": "quant/v1/manifests/TW-20260714T090000Z-aaaaaaaaaaaa.json",
        "dataset_sha256": "a" * 64,
        "cutoff": "2026-07-14",
        "metrics": {
            "oos_direction_accuracy": 0.55,
            "brier_score": 0.24,
            "high_score_realized_rate": 0.61,
            "strategy_win_rate": 0.53,
            "expectancy": 0.008,
            "profit_factor": 1.25,
            "max_drawdown": -0.14,
            "longest_winning_streak": 4,
            "longest_losing_streak": 3,
        },
        "calibration": [{"lower": 0.5, "upper": 0.6, "observed": 0.54, "samples": 80}],
        "yearly": {"2025": 0.08, "2026": 0.03},
        "regimes": {"bull": 0.07, "bear": -0.02},
        "cost_sensitivity": {"base": 0.05, "double_cost": 0.03},
        "drift": {"probability_psi": 0.08, "feature_psi": 0.11},
        "data_quality": {"coverage": 0.98, "invalid_rate": 0.01},
    }


class Ledger:
    def __init__(self, matured=10):
        self.matured = matured

    def accuracy_summary(self):
        return {
            "matured": self.matured,
            "correct": 6 if self.matured else 0,
            "accuracy": 0.6 if self.matured else None,
            "invalid": 1,
        }


class WeeklyModelReportTests(unittest.TestCase):
    def test_requires_promoted_backtest_matured_ledger_and_new_candidate(self):
        raw = promoted_backtest()
        raw.pop("gates")
        with self.assertRaises(WeeklyModelReportError):
            build_weekly_model_report(raw, Ledger(), generated_at=datetime.datetime.now(UTC))
        with self.assertRaises(WeeklyModelReportError):
            build_weekly_model_report(
                promoted_backtest(), Ledger(0), generated_at=datetime.datetime.now(UTC)
            )
        with self.assertRaisesRegex(WeeklyModelReportError, "no new"):
            build_weekly_model_report(
                promoted_backtest(),
                Ledger(),
                generated_at=datetime.datetime.now(UTC),
                previous_candidate_sha256="c" * 64,
            )

    def test_report_keeps_probability_and_strategy_metrics_distinct(self):
        report = build_weekly_model_report(
            promoted_backtest(),
            Ledger(),
            generated_at=datetime.datetime(2026, 7, 18, 2, tzinfo=UTC),
        )

        self.assertEqual(report["report_type"], "weekly_model")
        probability = report["content"]["probability_model"]
        strategy = report["content"]["strategy"]
        self.assertEqual(probability["ledger_direction_accuracy"], 0.6)
        self.assertEqual(probability["oos_direction_accuracy"], 0.55)
        self.assertEqual(probability["high_score_realized_rate"], 0.61)
        self.assertEqual(probability["brier_score"], 0.24)
        self.assertEqual(strategy["win_rate"], 0.53)
        self.assertEqual(strategy["expectancy"], 0.008)
        self.assertIn("yearly", report["content"])
        self.assertIn("regimes", report["content"])
        self.assertIn("cost_sensitivity", report["content"])
        self.assertIn("drift", report["content"])
        self.assertIn("data_quality", report["content"])


if __name__ == "__main__":
    unittest.main()
