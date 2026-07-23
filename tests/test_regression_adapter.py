"""Reference and boundary tests for the fixed v1 OLS/HAC adapter."""

import unittest

import numpy as np
import statsmodels.api as sm

from reporting.regression_adapter import compute_ols_hac_regression
from tests.regression_fixtures import FACTORS


class TestRegressionAdapter(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(42)
        self.matrix = rng.normal(size=(80, 3))
        noise = rng.normal(scale=0.01, size=80)
        self.y = 0.01 + self.matrix @ np.array([0.04, -0.03, 0.02]) + noise

    def test_matches_direct_statsmodels_hac_reference_within_1e_5(self):
        fit_stats, results, diagnostics = compute_ols_hac_regression(
            dependent_series=self.y.tolist(),
            factor_matrix=self.matrix.tolist(),
            factor_names=list(FACTORS),
        )

        design = sm.add_constant(self.matrix, has_constant="add")
        reference = sm.OLS(self.y, design).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": 4, "kernel": "bartlett", "use_correction": True},
            use_t=True,
        )
        confidence_intervals = reference.conf_int(alpha=0.05)

        for index, item in enumerate(results, start=1):
            with self.subTest(factor=item["factor_name"]):
                self.assertAlmostEqual(item["coefficient"], reference.params[index], places=5)
                self.assertAlmostEqual(item["standard_error"], reference.bse[index], places=5)
                self.assertAlmostEqual(item["t_statistic"], reference.tvalues[index], places=5)
                self.assertAlmostEqual(item["p_value"], reference.pvalues[index], places=5)
                self.assertAlmostEqual(item["confidence_interval_low"], confidence_intervals[index, 0], places=5)
                self.assertAlmostEqual(item["confidence_interval_high"], confidence_intervals[index, 1], places=5)
        self.assertAlmostEqual(fit_stats["r_squared"], reference.rsquared, places=5)
        self.assertEqual(set(diagnostics["multicollinearity"]["vif_details"]), set(FACTORS))

    def test_fixed_v1_parameters_cannot_be_overridden(self):
        with self.assertRaises(TypeError):
            compute_ols_hac_regression(
                self.y.tolist(), self.matrix.tolist(), list(FACTORS), lags=1
            )
        with self.assertRaises(TypeError):
            compute_ols_hac_regression(
                self.y.tolist(), self.matrix.tolist(), list(FACTORS), confidence_level=0.9
            )

    def test_rejects_short_malformed_nonfinite_and_rank_deficient_inputs(self):
        cases = (
            (self.y[:29].tolist(), self.matrix[:29].tolist(), list(FACTORS)),
            (self.y.tolist(), self.matrix[:, :2].tolist(), list(FACTORS)),
            (self.y.tolist(), self.matrix.tolist(), list(FACTORS[:2])),
            (self.y.tolist(), [[True, *row[1:]] for row in self.matrix.tolist()], list(FACTORS)),
            (self.y.tolist(), np.column_stack([self.matrix[:, 0], self.matrix[:, 0], self.matrix[:, 2]]).tolist(), list(FACTORS)),
        )
        for dependent, matrix, names in cases:
            with self.subTest(rows=len(dependent), factors=len(names)):
                with self.assertRaises((ValueError, TypeError)):
                    compute_ols_hac_regression(dependent, matrix, names)


if __name__ == "__main__":
    unittest.main()
