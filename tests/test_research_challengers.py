from __future__ import annotations

import datetime
import unittest

import numpy as np
import pandas as pd

from stock_papi.research.challengers import (
    DIRECTION_FEATURES,
    run_baselines,
    run_direction_lightgbm,
    run_ranking_lightgbm,
)
from stock_papi.research.evaluation import build_split_plan


def frame():
    rng = np.random.default_rng(20260717)
    rows = []
    start = datetime.date(2025, 1, 1)
    for date_index in range(120):
        date = (start + datetime.timedelta(days=date_index)).isoformat()
        for symbol_index in range(12):
            momentum_5 = rng.normal(0, 0.03)
            momentum_20 = rng.normal(0, 0.08)
            return_1 = rng.normal(0, 0.015)
            volatility_20 = abs(rng.normal(0.02, 0.005))
            volume_ratio_20 = max(0.1, rng.normal(1.0, 0.2))
            latent = 2.0 * momentum_5 + 0.7 * momentum_20 - return_1
            future_return = latent + rng.normal(0, 0.03)
            rows.append(
                {
                    "symbol": f"{symbol_index:04d}",
                    "source_market_date": date,
                    "close": 50 + symbol_index,
                    "volume": 1_000_000 + date_index * 1000,
                    "return_1": return_1,
                    "momentum_5": momentum_5,
                    "momentum_20": momentum_20,
                    "volatility_20": volatility_20,
                    "volume_ratio_20": volume_ratio_20,
                    "future_return_5": future_return,
                    "direction_5": int(future_return > 0),
                    "AI_P": rng.uniform(0, 100),
                }
            )
    return pd.DataFrame(rows)


class FakeClassifier:
    fits = []

    def fit(self, values, target):
        self.__class__.fits.append((values.copy(), target.copy()))
        return self

    def predict_proba(self, values):
        score = 1.0 / (1.0 + np.exp(-values[:, 1] * 20.0))
        return np.column_stack((1.0 - score, score))


class FakeRanker:
    fits = []

    def fit(self, values, target, group):
        self.__class__.fits.append((values.copy(), target.copy(), group.copy()))
        return self

    def predict(self, values):
        return values[:, 1]


class ResearchChallengerTests(unittest.TestCase):
    def test_baselines_refit_from_explicit_dataset_features_only(self):
        source = frame()
        plan = build_split_plan(source["source_market_date"].unique())

        first = run_baselines(source, plan)
        source["AI_P"] = 100.0 - source["AI_P"]
        second = run_baselines(source, plan)

        self.assertEqual(
            set(first),
            {"constant_prior", "momentum_logistic", "mean_reversion_logistic"},
        )
        for name in first:
            with self.subTest(name=name):
                self.assertEqual(first[name]["fit_source"], "dataset_features")
                np.testing.assert_allclose(
                    first[name]["holdout"]["probability"],
                    second[name]["holdout"]["probability"],
                )
                self.assertNotIn("AI_P", first[name]["features"])

    def test_direction_lightgbm_uses_independent_factory_for_every_fit(self):
        source = frame()
        plan = build_split_plan(source["source_market_date"].unique())
        FakeClassifier.fits = []

        result = run_direction_lightgbm(
            source,
            plan,
            model_factory=FakeClassifier,
        )

        self.assertEqual(result["status"], "RUN")
        self.assertEqual(result["features"], list(DIRECTION_FEATURES))
        self.assertEqual(
            len(FakeClassifier.fits),
            len(plan["walk_forward_folds"]) + 1,
        )
        for values, target in FakeClassifier.fits:
            self.assertEqual(values.shape[1], len(DIRECTION_FEATURES))
            self.assertEqual(len(values), len(target))

    def test_ranking_challenger_is_not_run_without_pit_universe(self):
        source = frame()
        plan = build_split_plan(source["source_market_date"].unique())
        calls = []

        result = run_ranking_lightgbm(
            source,
            plan,
            {
                "requirements": {
                    "tradable_universe": {"status": "unavailable"},
                    "listing_delisting": {"status": "unavailable"},
                    "suspension": {"status": "unavailable"},
                }
            },
            model_factory=lambda: calls.append(True),
        )

        self.assertEqual(result["status"], "NOT_RUN")
        self.assertIn("tradable_universe", result["dependencies"])
        self.assertEqual(calls, [])

    def test_ranking_lightgbm_refits_when_all_pit_dependencies_exist(self):
        source = frame()
        plan = build_split_plan(source["source_market_date"].unique())
        FakeRanker.fits = []
        audit = {
            "requirements": {
                name: {"status": "available"}
                for name in (
                    "tradable_universe",
                    "listing_delisting",
                    "suspension",
                )
            }
        }

        result = run_ranking_lightgbm(
            source,
            plan,
            audit,
            model_factory=FakeRanker,
        )

        self.assertEqual(result["status"], "RUN")
        self.assertEqual(
            len(FakeRanker.fits),
            len(plan["walk_forward_folds"]) + 1,
        )
        for values, target, groups in FakeRanker.fits:
            self.assertEqual(values.shape[1], len(DIRECTION_FEATURES))
            self.assertEqual(len(values), len(target))
            self.assertEqual(int(groups.sum()), len(values))


if __name__ == "__main__":
    unittest.main()
