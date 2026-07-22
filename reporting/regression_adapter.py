# -*- coding: utf-8 -*-
"""OLS regression adapter with Newey-West HAC covariance estimator."""

import math
from typing import Any

from stock_papi.research.regression_deps import (
    get_breusch_pagan_test,
    get_durbin_watson_test,
    get_jarque_bera_test,
    get_statsmodels_api,
    get_vif_calculator,
)
from reporting.regression_input_schema import V1_FACTORS

FACTOR_DISPLAY_LABELS = {
    "volume_surge_ratio": "成交量異常放大比率",
    "foreign_net_flow_ratio": "外資買賣超占成交量比率",
    "volatility_20d": "20日標的波動度",
}


def compute_ols_hac_regression(
    dependent_series: list[float],
    factor_matrix: list[list[float]],
    factor_names: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Compute OLS regression estimates with Newey-West HAC covariance."""
    sm = get_statsmodels_api()
    import numpy as np

    if not 30 <= len(dependent_series) <= 252:
        raise ValueError("v1 regression requires between 30 and 252 rows")
    if factor_names != list(V1_FACTORS):
        raise ValueError("factor_names must be the three v1 factors in contract order")
    if any(isinstance(value, bool) for value in dependent_series) or any(
        isinstance(value, bool) for row in factor_matrix for value in row
    ):
        raise TypeError("bool is not a valid regression numeric value")

    y = np.array(dependent_series, dtype=float)
    X_raw = np.array(factor_matrix, dtype=float)

    if X_raw.ndim != 2 or X_raw.shape[1] != len(factor_names):
        raise ValueError("factor matrix columns must match factor_names")
    if len(y) != len(X_raw):
        raise ValueError(f"Sample length mismatch: y has {len(y)} rows, X has {len(X_raw)} rows")

    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(X_raw)):
        raise ValueError("Non-finite values (NaN, Inf) found in dependent or factor matrix")

    # Add constant intercept to design matrix
    X = sm.add_constant(X_raw, has_constant="add")

    # Rank check: design matrix full rank requirement
    rank = np.linalg.matrix_rank(X)
    expected_rank = X.shape[1]
    if rank < expected_rank:
        raise ValueError(f"Design matrix rank deficient: rank={rank} < expected={expected_rank}")

    model = sm.OLS(y, X)
    fit_res = model.fit(
        cov_type="HAC",
        cov_kwds={
            "maxlags": 4,
            "kernel": "bartlett",
            "use_correction": True,
        },
        use_t=True,
    )

    fit_stats = {
        "r_squared": float(fit_res.rsquared),
        "adjusted_r_squared": float(fit_res.rsquared_adj),
        "residual_standard_error": float(math.sqrt(fit_res.mse_resid)),
        "degrees_of_freedom": int(fit_res.df_resid),
        "f_statistic": float(fit_res.fvalue) if fit_res.fvalue is not None else 0.0,
        "f_p_value": float(fit_res.f_pvalue) if fit_res.f_pvalue is not None else 1.0,
    }

    # Calculate 95% confidence intervals
    conf_int = fit_res.conf_int(alpha=0.05)

    results = []
    # Intercept is index 0; factor columns are indices 1..k
    for idx, name in enumerate(factor_names, start=1):
        coef = float(fit_res.params[idx])
        se = float(fit_res.bse[idx])
        t_stat = float(fit_res.tvalues[idx])
        p_val = float(fit_res.pvalues[idx])
        ci_low = float(conf_int[idx, 0])
        ci_high = float(conf_int[idx, 1])

        direction = "positive" if coef > 0 else "negative" if coef < 0 else "neutral"
        mag = "strong" if abs(t_stat) >= 3.0 else "moderate" if abs(t_stat) >= 2.0 else "weak"
        disp_status = "statistically_significant" if p_val < 0.05 else "statistically_insignificant"

        results.append({
            "factor_name": name,
            "display_label": FACTOR_DISPLAY_LABELS.get(name, name),
            "coefficient": coef,
            "standard_error": se,
            "t_statistic": t_stat,
            "p_value": p_val,
            "confidence_interval_low": ci_low,
            "confidence_interval_high": ci_high,
            "direction": direction,
            "economic_magnitude": mag,
            "display_status": disp_status,
        })

    # Compute diagnostics
    vif_calc = get_vif_calculator()
    vif_details = {}
    max_vif = 1.0
    for idx, name in enumerate(factor_names):
        # VIF calculated over factor columns excluding intercept (column idx)
        v = float(vif_calc(X_raw, idx))
        vif_details[name] = v
        if v > max_vif:
            max_vif = v

    bp_calc = get_breusch_pagan_test()
    residuals = fit_res.resid
    lm_stat, lm_pval, _, _ = bp_calc(residuals, X)

    dw_calc = get_durbin_watson_test()
    dw_val = float(dw_calc(residuals))

    jb_calc = get_jarque_bera_test()
    jb_val, jb_pval, _, _ = jb_calc(residuals)

    diagnostics = {
        "multicollinearity": {
            "status": "passed" if max_vif < 5.0 else "warning",
            "max_vif": float(max_vif),
            "note": "VIF calculated exclusively over independent factor columns excluding constant intercept",
            "vif_details": vif_details,
        },
        "heteroskedasticity": {
            "status": "passed" if lm_pval >= 0.05 else "warning",
            "test_name": "breusch_pagan",
            "test_statistic": float(lm_stat),
            "p_value": float(lm_pval),
            "threshold": 0.05,
        },
        "autocorrelation": {
            "status": "passed" if 1.5 <= dw_val <= 2.5 else "warning",
            "durbin_watson": float(dw_val),
        },
        "residual_normality": {
            "status": "passed" if jb_pval >= 0.05 else "warning",
            "jarque_bera_p_value": float(jb_pval),
        },
        "data_quality": {
            "missing_rate": 0.0,
            "outlier_count": 0,
        },
        "warnings": [],
    }

    return fit_stats, results, diagnostics
