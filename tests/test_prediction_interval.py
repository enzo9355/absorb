"""五日預測的誤差區間（規格書 §7-2）。

**這個區間不是信賴區間。** 它是「過去樣本外誤差的中間 80%」套在點預測上 ——
對誤差分布的描述，不是機率保證。模型沒有輸出校準過的機率分布，
把它畫成信賴區間等於宣稱一個沒有被驗證過的東西。

這一組測試守三件事：
1 區間必須真的涵蓋它宣稱的比例（不是隨手取的數字）。
2 區間必須包住點預測，而且不自洽就整個丟掉，不畫一條錯的。
3 舊產物沒有這個欄位時，畫面照常運作。
"""

import math
import unittest

import numpy as np
import pandas as pd

from stock_papi.batch.prediction_products import _residual_interval
from stock_papi.quant.model import (
    RESIDUAL_INTERVAL_LOWER_Q,
    RESIDUAL_INTERVAL_MIN_SAMPLES,
    RESIDUAL_INTERVAL_UPPER_Q,
)
from stock_papi.services.prediction_view import prediction_for


def _snapshot(interval=None):
    entity = {
        "symbol": "2330",
        "entity_type": "security",
        "as_of": "2026-08-26",
        "target_session": "2026-09-02",
        "current_price": 1000.0,
        "up_probability": 0.61,
        "predicted_return_5d": 0.02,
        "predicted_price": 1020.0,
        "predicted_change_pct": 2.0,
    }
    if interval is not None:
        entity["prediction_interval"] = interval
    return {
        "schema_version": 2,
        "validation_mode": "research",
        "kind": "absorb-five-session-predictions",
        "market": "TW",
        "as_of": "2026-08-26",
        "entities": {"2330": entity},
    }


VALID_INTERVAL = {
    "coverage_pct": 80.0,
    "sample_count": 240,
    "return_low_pct": -2.70,
    "return_high_pct": 6.10,
    "price_low": 973.0,
    "price_high": 1061.0,
}


class ResidualIntervalCoverageTests(unittest.TestCase):
    def test_interval_actually_covers_the_share_it_claims(self):
        """宣稱 80% 就必須真的涵蓋約 80%。

        這是整個設計唯一值得做的理由：區間來自實際量到的樣本外誤差，
        所以它的涵蓋率是可以被檢查的 —— 而不是模型自己說了算。
        """
        rng = np.random.default_rng(7)
        for noise in (0.01, 0.03, 0.08):
            with self.subTest(noise=noise):
                actual = rng.normal(0, 0.05, 4000)
                predicted = actual + rng.normal(0.003, noise, 4000)
                errors = pd.Series(predicted - actual)
                low_q, high_q = np.quantile(
                    errors.to_numpy(dtype=float),
                    [RESIDUAL_INTERVAL_LOWER_Q, RESIDUAL_INTERVAL_UPPER_Q],
                )
                inside = (
                    (actual >= predicted - high_q) & (actual <= predicted - low_q)
                ).mean()
                expected = RESIDUAL_INTERVAL_UPPER_Q - RESIDUAL_INTERVAL_LOWER_Q
                self.assertAlmostEqual(inside, expected, delta=0.02)

    def test_minimum_sample_count_is_high_enough_to_estimate_a_decile(self):
        """樣本太少時分位數估不準 —— 一個估不準的區間比沒有區間更糟。"""
        self.assertGreaterEqual(RESIDUAL_INTERVAL_MIN_SAMPLES, 50)
        # 至少要能讓兩端各有 5 個樣本落在尾巴裡
        tail = RESIDUAL_INTERVAL_MIN_SAMPLES * RESIDUAL_INTERVAL_LOWER_Q
        self.assertGreaterEqual(tail, 5)


class ResidualIntervalBuildTests(unittest.TestCase):
    def _backtest(self, **overrides):
        interval = {
            "return_offset_low": -0.047,
            "return_offset_high": 0.041,
            "coverage_pct": 80.0,
            "sample_count": 240,
        }
        interval.update(overrides)
        return {"backtest": {"price_metrics": {"residual_interval": interval}}}

    def test_missing_interval_is_not_an_error(self):
        """舊快照沒有這個欄位 —— 不給區間，不是失敗。"""
        self.assertIsNone(_residual_interval({}, 1000.0, 0.02))
        self.assertIsNone(_residual_interval({"backtest": {}}, 1000.0, 0.02))
        self.assertIsNone(
            _residual_interval({"backtest": {"price_metrics": {}}}, 1000.0, 0.02)
        )

    def test_interval_brackets_the_point_prediction(self):
        result = _residual_interval(self._backtest(), 1000.0, 0.02)
        self.assertLess(result["price_low"], 1020.0)
        self.assertGreater(result["price_high"], 1020.0)
        self.assertTrue(
            math.isclose(result["price_low"], 1000.0 * (1 + result["return_low_pct"] / 100))
        )

    def test_inconsistent_interval_is_rejected_not_silently_dropped(self):
        """上下界顛倒是資料錯誤，不是缺值。靜靜丟掉會讓錯誤留在上游。"""
        with self.assertRaises(ValueError):
            _residual_interval(
                self._backtest(return_offset_low=0.05, return_offset_high=-0.05),
                1000.0,
                0.02,
            )
        with self.assertRaises(ValueError):
            _residual_interval(self._backtest(coverage_pct=0.0), 1000.0, 0.02)
        with self.assertRaises(ValueError):
            _residual_interval(self._backtest(sample_count=0), 1000.0, 0.02)

    def test_interval_below_zero_price_is_dropped(self):
        """殘差分布失真到讓價格下緣跌破零，就不給區間。"""
        self.assertIsNone(
            _residual_interval(self._backtest(return_offset_low=-5.0), 1000.0, 0.02)
        )


class PredictionViewIntervalTests(unittest.TestCase):
    def test_band_starts_with_zero_width_at_the_known_close(self):
        """起點寬度為零是刻意的 —— 今天的收盤是已知的，不該有不確定性。"""
        view = prediction_for(_snapshot(VALID_INTERVAL), "TW", "2330", "2026-08-26")
        band = view["band"]
        self.assertEqual(len(band), 2)
        self.assertEqual(band[0]["upper"], band[0]["lower"])
        self.assertEqual(band[0]["upper"], 1000.0)
        self.assertLess(band[1]["lower"], band[1]["upper"])

    def test_view_drops_an_interval_that_does_not_bracket_the_prediction(self):
        """區間不包住點預測，它描述的就不是這一次的預測。寧可沒有帶。"""
        bad = dict(VALID_INTERVAL, price_low=1030.0, price_high=1090.0)
        view = prediction_for(_snapshot(bad), "TW", "2330", "2026-08-26")
        self.assertIsNotNone(view)
        self.assertNotIn("band", view)
        self.assertNotIn("interval", view)

    def test_old_products_without_an_interval_still_render(self):
        view = prediction_for(_snapshot(), "TW", "2330", "2026-08-26")
        self.assertIsNotNone(view)
        self.assertNotIn("band", view)
        self.assertEqual(view["predicted_price"], 1020.0)


if __name__ == "__main__":
    unittest.main()
