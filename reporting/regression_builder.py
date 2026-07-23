# -*- coding: utf-8 -*-
"""Pure builder orchestrator for RegressionResearchArtifact objects."""

import datetime
from typing import Any
import numpy as np

from reporting import git_commit_sha
from reporting.regression_adapter import compute_ols_hac_regression
from reporting.regression_input_schema import HEX_40_RE, RegressionInputDataset, TradingCalendar, V1_FACTORS
from reporting.regression_schema import (
    INPUT_DATASET_OBJECT_RE,
    RegressionResearchArtifact,
    compute_regression_artifact_content_sha256,
)
from reporting.regression_validation import validate_regression_diagnostics


def winsorize_1_99(arr: np.ndarray) -> np.ndarray:
    """Winsorize 1D numpy array at 1st and 99th percentiles using linear interpolation."""
    if len(arr) == 0:
        return arr
    p1 = np.percentile(arr, 1.0, method="linear")
    p99 = np.percentile(arr, 99.0, method="linear")
    return np.clip(arr, p1, p99)


def z_score_standardize(arr: np.ndarray) -> np.ndarray:
    """Z-score standardize 1D numpy array with ddof=1."""
    if len(arr) <= 1:
        return arr
    std_val = np.std(arr, ddof=1)
    if std_val < 1e-12:
        raise ValueError(f"Zero standard deviation encountered during Z-score standardization: std={std_val}")
    mean_val = np.mean(arr)
    return (arr - mean_val) / std_val


def build_regression_research_artifact(
    input_dataset: dict[str, Any] | RegressionInputDataset,
    input_dataset_object_path: str,
    input_dataset_object_sha256: str,
    source_market_date: str,
    applicable_trading_date: str,
    generator_version: str = "1.0.0",
    generated_at: str | None = None,
    code_commit_sha: str | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> dict[str, Any] | None:
    """Pure builder function constructing a RegressionResearchArtifact dict from a verified input dataset."""
    if trading_calendar is None:
        raise ValueError("trading_calendar is required")
    if isinstance(input_dataset, RegressionInputDataset):
        ds_doc = input_dataset.to_document()
    else:
        ds_doc = input_dataset
    dataset_obj = RegressionInputDataset.from_document(
        ds_doc,
        trading_calendar=trading_calendar,
    )

    if dataset_obj.identity.source_market_date != source_market_date:
        raise ValueError("source_market_date must match input dataset identity")
    source_date = datetime.date.fromisoformat(source_market_date)
    applicable_date = datetime.date.fromisoformat(applicable_trading_date)
    if (
        not trading_calendar.is_session(source_date)
        or not trading_calendar.is_session(applicable_date)
        or trading_calendar.session_offset(source_date, 1) != applicable_date
    ):
        raise ValueError("applicable_trading_date must be the next trading session")
    path_match = INPUT_DATASET_OBJECT_RE.fullmatch(input_dataset_object_path)
    if path_match is None or path_match.group(1) != input_dataset_object_sha256:
        raise ValueError("input dataset object path must bind its SHA256")

    resolved_commit_sha = (code_commit_sha or git_commit_sha()).lower()
    if HEX_40_RE.fullmatch(resolved_commit_sha) is None:
        raise ValueError("code_commit_sha must be lowercase 40-hex")

    rows = ds_doc.get("rows", [])
    if not rows:
        return None

    # Recheck every PIT boundary with the same verified calendar used by the input schema.
    mature_rows = []
    for row in rows:
        feature_date = datetime.date.fromisoformat(row["feature_session"])
        label_date = datetime.date.fromisoformat(row["label_end_session"])
        if (
            not trading_calendar.is_session(feature_date)
            or not trading_calendar.is_session(label_date)
            or trading_calendar.session_offset(feature_date, 5) != label_date
        ):
            raise ValueError("invalid trading-calendar PIT row")
        if label_date <= source_date:
            mature_rows.append(row)
    if len(mature_rows) < 30:
        # Sample count < 30 returns None or hard failure
        return None

    # Take up to last 252 mature sessions
    mature_rows = mature_rows[-252:]

    # Step 3: Listwise deletion
    factor_names = list(V1_FACTORS)
    valid_rows = []
    for r in mature_rows:
        fv = r.get("factor_values", {})
        if all(k in fv and isinstance(fv[k], (int, float)) and not isinstance(fv[k], bool) and np.isfinite(fv[k]) for k in factor_names):
            valid_rows.append(r)

    n_sample = len(valid_rows)
    if n_sample < 30:
        return None

    y_raw = np.array([r["five_session_forward_return"] for r in valid_rows], dtype=float)

    # Step 4 & 5: Winsorization and Z-Score Standardization per factor column
    X_processed = []
    for fname in factor_names:
        col_raw = np.array([r["factor_values"][fname] for r in valid_rows], dtype=float)
        col_win = winsorize_1_99(col_raw)
        col_z = z_score_standardize(col_win)
        X_processed.append(col_z)

    factor_matrix = np.column_stack(X_processed).tolist()

    # Step 6 & 7: OLS & Newey-West HAC
    fit_stats, results, diagnostics = compute_ols_hac_regression(
        dependent_series=y_raw.tolist(),
        factor_matrix=factor_matrix,
        factor_names=factor_names,
    )

    # Validation Engine
    summary_status, failure_reason, validation_warnings = validate_regression_diagnostics(
        fit_stats=fit_stats,
        diagnostics=diagnostics,
        sample_count=n_sample,
    )
    if summary_status == "unavailable":
        return None

    if validation_warnings:
        diagnostics.setdefault("warnings", []).extend(validation_warnings)

    first_feature = valid_rows[0]["feature_session"]
    last_feature = valid_rows[-1]["feature_session"]
    first_label_end = valid_rows[0]["label_end_session"]
    last_label_end = valid_rows[-1]["label_end_session"]

    gen_time = generated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    artifact_doc = {
        "schema_version": 1,
        "kind": "absorb-regression-research-artifact",
        "identity": {
            "artifact_id": f"TW-{source_market_date.replace('-', '')}-regression-ols-v1",
            "market": "TW",
            "source_market_date": source_market_date,
            "applicable_trading_date": applicable_trading_date,
            "generated_at": gen_time,
            "source_manifest": dataset_obj.identity.aggregate_manifest_object,
            "source_manifest_sha256": dataset_obj.identity.aggregate_manifest_sha256,
            "input_dataset_object": input_dataset_object_path,
            "input_dataset_sha256": input_dataset_object_sha256,
            "input_dataset_content_sha256": dataset_obj.identity.content_sha256,
            "input_dataset_rows_sha256": dataset_obj.identity.canonical_rows_sha256,
            "code_commit_sha": resolved_commit_sha,
            "generator_version": generator_version,
            "content_sha256": "",
            "regression_spec_version": "1.0",
        },
        "regression_spec": {
            "analysis_scope": "market_level_daily",
            "entity_type": "market_index",
            "universe_definition": "TWSE_TAIEX",
            "observation_unit": "daily_session",
            "model_family": "ols_linear_factor",
            "dependent_variable": "five_session_forward_return",
            "dependent_variable_definition": "5-session forward return over official TAIEX daily closing prices",
            "independent_variables": factor_names,
            "intercept": True,
            "frequency": "daily",
            "first_feature_session": first_feature,
            "last_feature_session": last_feature,
            "first_label_end_session": first_label_end,
            "last_label_end_session": last_label_end,
            "label_horizon_sessions": 5,
            "sample_count": n_sample,
            "missing_value_policy": "listwise_deletion",
            "standardization_policy": "z_score",
            "outlier_policy": "winsorize_1_99",
            "covariance_estimator": "newey_west_hac",
            "hac_max_lags": 4,
            "confidence_level": 0.95,
        },
        "results": results,
        "fit_statistics": fit_stats,
        "diagnostics": diagnostics,
        "presentation": {
            "headline": f"近 {n_sample} 個交易日因子迴歸分析顯示市場因子與未來 5 日報酬呈現統計關係",
            "summary": f"在控制 20 日波動度後，迴歸說明性 R² 為 {fit_stats['r_squared']:.4f}。",
            "key_exposures": [
                f"{r['display_label']}: 係數 {r['coefficient']:+.4f} (t={r['t_statistic']:.2f}, p={r['p_value']:.4f})"
                for r in results
            ],
            "limitations": f"本分析為歷史 OLS 迴歸結果，反映過去 {n_sample} 個交易日之統計相關性，不代表未來因果關係。",
            "disclosure": "模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。",
        },
    }

    content_sha = compute_regression_artifact_content_sha256(artifact_doc)
    artifact_doc["identity"]["content_sha256"] = content_sha

    # Schema validation check
    RegressionResearchArtifact.from_document(artifact_doc)
    return artifact_doc
