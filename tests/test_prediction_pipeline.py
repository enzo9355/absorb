import os
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app


class PredictionPipelineTests(unittest.TestCase):
    def test_last_five_rows_have_no_training_target(self):
        frame = pd.DataFrame({"Close": np.arange(1.0, 21.0)})

        result = stock_app.add_prediction_target(frame)

        horizon = stock_app.PREDICTION_HORIZON
        self.assertTrue(result["FUTURE_RET_5"].tail(horizon).isna().all())
        self.assertTrue(result["T"].tail(horizon).isna().all())
        self.assertEqual(int(result["T"].notna().sum()), 15)

    def test_walk_forward_splits_keep_five_row_gap(self):
        for train, test in stock_app.build_time_splits(120):
            self.assertLess(train[-1], test[0])
            self.assertGreaterEqual(
                test[0] - train[-1] - 1,
                stock_app.PREDICTION_HORIZON,
            )

    def test_backtest_uses_five_day_returns_and_cost(self):
        future = pd.Series([0.02] * 10)
        probabilities = pd.Series([0.7] * 10)

        metrics = stock_app.score_oos_predictions(future, probabilities)

        expected = (
            (1 + 0.02 - stock_app.ROUND_TRIP_COST) ** 2 - 1
        ) * 100
        self.assertAlmostEqual(metrics["strat_cum"], expected, places=8)
        self.assertEqual(metrics["trades"], 2)

    def test_missing_chip_data_falls_back_to_neutral_features(self):
        close = np.linspace(50, 80, 100) + np.sin(np.arange(100))
        frame = pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 0.5,
                "Low": close - 0.5,
                "Close": close,
                "Volume": np.linspace(1000, 2000, 100),
            }
        )

        result = stock_app.calc_all(frame)

        columns = ["VOL_RATIO", "INST_NET_RATIO", "MARGIN_CHG", "SHORT_CHG"]
        self.assertFalse(result[columns].isna().any().any())
        self.assertTrue(np.isfinite(result[columns].to_numpy()).all())
        self.assertTrue((result[["INST_NET_RATIO", "MARGIN_CHG", "SHORT_CHG"]] == 0).all().all())

    def test_chip_data_is_aggregated_by_trading_date(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
        price = pd.DataFrame({"Date": dates, "Close": [100.0, 101.0]})
        institutional = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-02"],
                "buy": [1000, 500],
                "sell": [200, 100],
            }
        )
        margin = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-05"],
                "MarginPurchaseTodayBalance": [3000, 3300],
                "ShortSaleTodayBalance": [100, 120],
            }
        )

        result = stock_app.merge_chip_data(price, institutional, margin)

        self.assertEqual(result.loc[0, "InstitutionalNet"], 1200)
        self.assertEqual(result.loc[1, "InstitutionalNet"], 0)
        self.assertEqual(result.loc[1, "MarginBalance"], 3300)
        self.assertEqual(result.loc[1, "ShortBalance"], 120)

    @patch("app.requests.get")
    def test_finmind_dataset_fetch_uses_existing_token(self, get):
        get.return_value = Mock(json=lambda: {"data": [{"value": 1}]})
        previous_token = stock_app.finmind_token
        stock_app.finmind_token = "token"
        self.addCleanup(setattr, stock_app, "finmind_token", previous_token)

        result = stock_app.fetch_finmind_dataset(
            "DatasetName",
            "2330",
            "2026-01-01",
            "2026-01-31",
        )

        self.assertEqual(result.to_dict("records"), [{"value": 1}])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["dataset"], "DatasetName")
        self.assertEqual(params["token"], "token")

    @patch("app.requests.get", side_effect=AssertionError("legacy request path"))
    @patch("app.fetch_finmind_dataset")
    def test_get_data_preserves_volume_and_chip_columns(self, fetch, _get):
        fetch.side_effect = [
            pd.DataFrame(
                {
                    "date": ["2026-01-02", "2026-01-05"],
                    "open": [100, 101],
                    "max": [102, 103],
                    "min": [99, 100],
                    "close": [101, 102],
                    "Trading_Volume": [10000, 12000],
                }
            ),
            pd.DataFrame(
                {
                    "date": ["2026-01-02"],
                    "buy": [2000],
                    "sell": [500],
                }
            ),
            pd.DataFrame(
                {
                    "date": ["2026-01-02", "2026-01-05"],
                    "MarginPurchaseTodayBalance": [3000, 3100],
                    "ShortSaleTodayBalance": [100, 90],
                }
            ),
        ]

        result = stock_app.get_data("2330", days=10)

        self.assertEqual(result["Volume"].tolist(), [10000, 12000])
        self.assertEqual(result["InstitutionalNet"].tolist(), [1500, 0])
        self.assertEqual(result["MarginBalance"].tolist(), [3000, 3100])


if __name__ == "__main__":
    unittest.main()
