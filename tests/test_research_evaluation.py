from __future__ import annotations

import datetime
import unittest
import warnings

import numpy as np
import pandas as pd

from stock_papi.research.evaluation import (
    build_split_plan,
    classification_metrics,
    ranking_metrics,
    stability_metrics,
    transaction_metrics,
)


class ResearchEvaluationTests(unittest.TestCase):
    def test_split_plan_has_walk_forward_purge_embargo_and_untouched_holdout(self):
        start = datetime.date(2025, 1, 1)
        dates = [
            (start + datetime.timedelta(days=index)).isoformat()
            for index in range(120)
        ]

        plan = build_split_plan(dates, fold_count=3)

        self.assertEqual(plan["purge_sessions"], 5)
        self.assertEqual(plan["embargo_sessions"], 5)
        self.assertFalse(plan["selection_uses_final_holdout"])
        self.assertTrue(set(plan["development_dates"]).isdisjoint(plan["final_holdout_dates"]))
        self.assertEqual(len(plan["final_gap_dates"]), 10)
        for fold in plan["walk_forward_folds"]:
            train_end = dates.index(fold["train_dates"][-1])
            validation_start = dates.index(fold["validation_dates"][0])
            self.assertGreaterEqual(validation_start - train_end - 1, 5)

    def test_classification_metrics_include_calibration_and_baselines(self):
        target = np.array([0, 0, 1, 1, 0, 1, 0, 1], dtype=int)
        probability = np.array([0.1, 0.3, 0.7, 0.9, 0.4, 0.8, 0.2, 0.6])

        metrics = classification_metrics(target, probability)

        for key in (
            "brier",
            "log_loss",
            "roc_auc",
            "calibration_slope",
            "calibration_intercept",
            "ece_10",
            "positive_rate",
            "observations",
        ):
            self.assertIn(key, metrics)
        self.assertLess(metrics["brier"], 0.25)
        self.assertGreater(metrics["roc_auc"], 0.9)

    def test_ranking_transaction_and_stability_metrics_are_explicit(self):
        rng = np.random.default_rng(20260717)
        rows = []
        start = datetime.date(2025, 1, 1)
        for date_index in range(40):
            date = (start + datetime.timedelta(days=date_index)).isoformat()
            for symbol_index in range(20):
                score = symbol_index / 20 + rng.normal(0, 0.01)
                future_return = score * 0.02 + rng.normal(0, 0.005)
                rows.append(
                    {
                        "symbol": f"{symbol_index:04d}",
                        "source_market_date": date,
                        "score": score,
                        "future_return_5": future_return,
                        "direction_5": int(future_return > 0),
                        "close": 50 + symbol_index,
                        "volume": 1_000_000 + symbol_index * 100_000,
                    }
                )
        source = pd.DataFrame(rows)

        ranking = ranking_metrics(source, score_column="score")
        transaction = transaction_metrics(source, score_column="score")
        stability = stability_metrics(
            source,
            score_column="score",
            bootstrap_iterations=100,
        )

        for key in ("spearman_ic", "top_decile_spread", "turnover"):
            self.assertIn(key, ranking)
        self.assertGreater(ranking["spearman_ic"], 0)
        self.assertIn("slippage_scenarios", transaction)
        self.assertIn("capacity_scenarios", transaction)
        self.assertIn("monthly", stability)
        self.assertIn("bootstrap_ci", stability)
        self.assertEqual(stability["industry"]["status"], "NOT_RUN")
        self.assertEqual(stability["market_regime"]["status"], "NOT_RUN")

    def test_constant_ranking_scores_return_no_ic_without_runtime_warnings(self):
        source = pd.DataFrame(
            [
                {
                    "symbol": f"{symbol_index:04d}",
                    "source_market_date": "2026-01-02",
                    "score": 0.5,
                    "future_return_5": symbol_index / 100,
                }
                for symbol_index in range(20)
            ]
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ranking = ranking_metrics(source, score_column="score")

        self.assertEqual(caught, [])
        self.assertIsNone(ranking["spearman_ic"])
        self.assertIsNone(ranking["spearman_ic_std"])
        self.assertIsNone(ranking["top_decile_spread"])


if __name__ == "__main__":
    unittest.main()
