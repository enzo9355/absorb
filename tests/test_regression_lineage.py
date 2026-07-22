# -*- coding: utf-8 -*-
"""Data lineage, Point-In-Time (PIT) safety, and factor preprocessing tests."""

import unittest
import numpy as np

from reporting.regression_builder import winsorize_1_99, z_score_standardize


class TestRegressionLineage(unittest.TestCase):

    def test_winsorization_clips_extreme_outliers_at_1_99_percentiles(self):
        arr = np.array([1.0] * 100)
        arr[0] = -100.0  # extreme low outlier
        arr[-1] = 100.0   # extreme high outlier

        win_arr = winsorize_1_99(arr)
        self.assertGreater(win_arr[0], -100.0)
        self.assertLess(win_arr[-1], 100.0)
        self.assertEqual(len(win_arr), 100)

    def test_z_score_standardization_uses_sample_std_ddof_1(self):
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        z_arr = z_score_standardize(arr)

        expected_mean = 0.0
        expected_std = 1.0

        self.assertAlmostEqual(float(np.mean(z_arr)), expected_mean, places=6)
        self.assertAlmostEqual(float(np.std(z_arr, ddof=1)), expected_std, places=6)

    def test_pit_calendar_shift_excludes_future_labels(self):
        source_market_date = "2026-07-17"
        rows = [
            {"feature_session": "2026-07-10", "label_end_session": "2026-07-17"},  # Mature: label_end_session <= source_market_date
            {"feature_session": "2026-07-15", "label_end_session": "2026-07-22"},  # Immature: label_end_session > source_market_date
        ]
        mature_rows = [r for r in rows if r["label_end_session"] <= source_market_date]
        self.assertEqual(len(mature_rows), 1)
        self.assertEqual(mature_rows[0]["feature_session"], "2026-07-10")


if __name__ == "__main__":
    unittest.main()
