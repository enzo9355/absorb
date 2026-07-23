# -*- coding: utf-8 -*-
"""Statistical validation and diagnostic engine for regression explainer."""

import math
from typing import Any


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def validate_regression_diagnostics(
    fit_stats: dict[str, Any],
    diagnostics: dict[str, Any],
    sample_count: int,
) -> tuple[str, str | None, list[str]]:
    """Validate sample size and diagnostics, returning (summary_status, failure_reason, warnings)."""
    warnings = []

    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        return "unavailable", "invalid_sample_count", []
    if sample_count < 30:
        return "unavailable", "insufficient_sample_count: sample_count < 30", []
    if sample_count > 252:
        return "unavailable", "sample_count_outside_v1_range", []

    required_fit_stats = (
        "r_squared",
        "adjusted_r_squared",
        "residual_standard_error",
        "degrees_of_freedom",
        "f_statistic",
        "f_p_value",
    )
    if any(not _finite_number(fit_stats.get(name)) for name in required_fit_stats):
        return "unavailable", "non_finite_fit_statistics", []
    r2 = float(fit_stats["r_squared"])
    if not 0.0 <= r2 <= 1.0:
        return "unavailable", f"invalid_r_squared: {r2}", []
    if float(fit_stats["adjusted_r_squared"]) > 1.0:
        return "unavailable", "invalid_adjusted_r_squared", []
    if float(fit_stats["residual_standard_error"]) < 0.0:
        return "unavailable", "invalid_residual_standard_error", []
    df = fit_stats["degrees_of_freedom"]
    if isinstance(df, bool) or not isinstance(df, int) or df <= 0:
        return "unavailable", f"invalid_degrees_of_freedom: {df}", []
    if not 0.0 <= float(fit_stats["f_p_value"]) <= 1.0:
        return "unavailable", "invalid_f_p_value", []

    diagnostic_values = (
        diagnostics.get("multicollinearity", {}).get("max_vif"),
        diagnostics.get("heteroskedasticity", {}).get("p_value"),
        diagnostics.get("autocorrelation", {}).get("durbin_watson"),
        diagnostics.get("residual_normality", {}).get("jarque_bera_p_value"),
    )
    if any(not _finite_number(value) for value in diagnostic_values):
        return "unavailable", "non_finite_diagnostics", []

    # Sample Count Warning Check: 30 <= sample_count < 60
    if 30 <= sample_count < 60:
        warnings.append("limited_sample_size: sample count is between 30 and 59, statistical power may be limited")

    # Diagnostic Warnings Check
    multicol = diagnostics.get("multicollinearity", {})
    max_vif = multicol["max_vif"]
    if max_vif >= 5.0:
        warnings.append(f"high_multicollinearity: max_vif={max_vif:.2f} >= 5.0")

    hetero = diagnostics.get("heteroskedasticity", {})
    bp_pval = hetero["p_value"]
    if bp_pval < 0.05:
        warnings.append(f"heteroskedasticity_detected: breusch_pagan_p_value={bp_pval:.4f} < 0.05")

    autocorr = diagnostics.get("autocorrelation", {})
    dw = autocorr["durbin_watson"]
    if dw < 1.5 or dw > 2.5:
        warnings.append(f"autocorrelation_warning: durbin_watson={dw:.2f} outside [1.5, 2.5]")

    normality = diagnostics.get("residual_normality", {})
    jb_pval = normality["jarque_bera_p_value"]
    if jb_pval < 0.05:
        warnings.append(f"non_normal_residuals: jarque_bera_p_value={jb_pval:.4f} < 0.05")

    summary_status = "available_with_limited_sample_warning" if (30 <= sample_count < 60) else "available"
    return summary_status, None, warnings
