# -*- coding: utf-8 -*-
"""Statistical validation and diagnostic engine for regression explainer."""

from typing import Any


def validate_regression_diagnostics(
    fit_stats: dict[str, Any],
    diagnostics: dict[str, Any],
    sample_count: int,
) -> tuple[str, str | None, list[str]]:
    """Validate sample size and diagnostics, returning (summary_status, failure_reason, warnings)."""
    warnings = []

    # Hard Failure Check 1: Sample count < 30
    if sample_count < 30:
        return "unavailable", "insufficient_sample_count: sample_count < 30", []

    # Hard Failure Check 2: Non-finite fit stats
    r2 = fit_stats.get("r_squared")
    if r2 is None or not (0.0 <= r2 <= 1.0):
        return "unavailable", f"invalid_r_squared: {r2}", []

    df = fit_stats.get("degrees_of_freedom", 0)
    if df <= 0:
        return "unavailable", f"invalid_degrees_of_freedom: {df}", []

    # Sample Count Warning Check: 30 <= sample_count < 60
    if 30 <= sample_count < 60:
        warnings.append("limited_sample_size: sample count is between 30 and 59, statistical power may be limited")

    # Diagnostic Warnings Check
    multicol = diagnostics.get("multicollinearity", {})
    max_vif = multicol.get("max_vif", 1.0)
    if max_vif >= 5.0:
        warnings.append(f"high_multicollinearity: max_vif={max_vif:.2f} >= 5.0")

    hetero = diagnostics.get("heteroskedasticity", {})
    bp_pval = hetero.get("p_value", 1.0)
    if bp_pval < 0.05:
        warnings.append(f"heteroskedasticity_detected: breusch_pagan_p_value={bp_pval:.4f} < 0.05")

    autocorr = diagnostics.get("autocorrelation", {})
    dw = autocorr.get("durbin_watson", 2.0)
    if dw < 1.5 or dw > 2.5:
        warnings.append(f"autocorrelation_warning: durbin_watson={dw:.2f} outside [1.5, 2.5]")

    normality = diagnostics.get("residual_normality", {})
    jb_pval = normality.get("jarque_bera_p_value", 1.0)
    if jb_pval < 0.05:
        warnings.append(f"non_normal_residuals: jarque_bera_p_value={jb_pval:.4f} < 0.05")

    summary_status = "available_with_limited_sample_warning" if (30 <= sample_count < 60) else "available"
    return summary_status, None, warnings
