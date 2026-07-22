# -*- coding: utf-8 -*-
"""Tests for statistical validation and diagnostic engine."""

import unittest
import copy
import math


class TestRegressionValidation(unittest.TestCase):

    def valid_inputs(self):
        return (
            {
                "r_squared": 0.3,
                "adjusted_r_squared": 0.28,
                "residual_standard_error": 0.02,
                "degrees_of_freedom": 45,
                "f_statistic": 10.0,
                "f_p_value": 0.001,
            },
            {
                "multicollinearity": {"status": "passed", "max_vif": 1.5, "vif_details": {}},
                "heteroskedasticity": {"status": "passed", "test_name": "breusch_pagan", "test_statistic": 1.0, "p_value": 0.5, "threshold": 0.05},
                "autocorrelation": {"status": "passed", "durbin_watson": 2.0},
                "residual_normality": {"status": "passed", "jarque_bera_p_value": 0.5},
                "data_quality": {"missing_rate": 0.0, "outlier_count": 0},
                "warnings": [],
            },
        )

    def test_sample_count_below_30_fails_hard(self):
        from reporting.regression_validation import validate_regression_diagnostics

        fit_stats = {
            "r_squared": 0.3,
            "adjusted_r_squared": 0.28,
            "residual_standard_error": 0.02,
            "degrees_of_freedom": 20,
            "f_statistic": 10.0,
            "f_p_value": 0.001,
        }
        diagnostics = {
            "multicollinearity": {"status": "passed", "max_vif": 1.5, "vif_details": {}},
            "heteroskedasticity": {"status": "passed", "test_name": "breusch_pagan", "test_statistic": 1.0, "p_value": 0.5, "threshold": 0.05},
            "autocorrelation": {"status": "passed", "durbin_watson": 2.0},
            "residual_normality": {"status": "passed", "jarque_bera_p_value": 0.5},
            "data_quality": {"missing_rate": 0.0, "outlier_count": 0},
            "warnings": [],
        }

        status, reason, warnings = validate_regression_diagnostics(
            fit_stats=fit_stats,
            diagnostics=diagnostics,
            sample_count=25,  # < 30 -> hard failure
        )
        self.assertEqual(status, "unavailable")
        self.assertIn("insufficient_sample_count", reason)

    def test_sample_count_30_to_59_yields_limited_sample_warning(self):
        from reporting.regression_validation import validate_regression_diagnostics

        fit_stats = {
            "r_squared": 0.3,
            "adjusted_r_squared": 0.28,
            "residual_standard_error": 0.02,
            "degrees_of_freedom": 45,
            "f_statistic": 10.0,
            "f_p_value": 0.001,
        }
        diagnostics = {
            "multicollinearity": {"status": "passed", "max_vif": 1.5, "vif_details": {}},
            "heteroskedasticity": {"status": "passed", "test_name": "breusch_pagan", "test_statistic": 1.0, "p_value": 0.5, "threshold": 0.05},
            "autocorrelation": {"status": "passed", "durbin_watson": 2.0},
            "residual_normality": {"status": "passed", "jarque_bera_p_value": 0.5},
            "data_quality": {"missing_rate": 0.0, "outlier_count": 0},
            "warnings": [],
        }

        status, reason, warnings = validate_regression_diagnostics(
            fit_stats=fit_stats,
            diagnostics=diagnostics,
            sample_count=45,
        )
        self.assertEqual(status, "available_with_limited_sample_warning")
        self.assertIsNone(reason)
        self.assertTrue(any("limited_sample_size" in w for w in warnings))

    def test_invalid_sample_range_and_nonfinite_statistics_fail_closed(self):
        from reporting.regression_validation import validate_regression_diagnostics

        fit_stats, diagnostics = self.valid_inputs()
        for sample_count in (True, 29, 253):
            with self.subTest(sample_count=sample_count):
                status, reason, _ = validate_regression_diagnostics(
                    fit_stats, diagnostics, sample_count
                )
                self.assertEqual(status, "unavailable")
                self.assertIsNotNone(reason)

        for field in fit_stats:
            with self.subTest(fit_stat=field):
                invalid = copy.deepcopy(fit_stats)
                invalid[field] = math.inf
                status, reason, _ = validate_regression_diagnostics(
                    invalid, diagnostics, 60
                )
                self.assertEqual(status, "unavailable")
                self.assertIn("non_finite", reason)

        invalid_diagnostics = copy.deepcopy(diagnostics)
        invalid_diagnostics["multicollinearity"]["max_vif"] = math.nan
        status, reason, _ = validate_regression_diagnostics(
            fit_stats, invalid_diagnostics, 60
        )
        self.assertEqual(status, "unavailable")
        self.assertEqual(reason, "non_finite_diagnostics")


if __name__ == "__main__":
    unittest.main()
