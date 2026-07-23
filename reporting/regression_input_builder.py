# -*- coding: utf-8 -*-
"""Pure builder and fail-closed readiness declarations for RegressionInputDataset."""

import datetime as dt
from typing import Any
from reporting import git_commit_sha
from reporting.regression_input_schema import (
    HEX_40_RE,
    RegressionInputDataset,
    TradingCalendar,
    compute_canonical_rows_sha256,
    compute_regression_input_dataset_content_sha256,
)

PRODUCTION_REGRESSION_SOURCE_ADAPTER_READY = False
PRODUCTION_REGRESSION_INPUT_READY = False
PRODUCTION_REGRESSION_ARTIFACT_AVAILABLE = False
AGGREGATE_MANIFEST_INTERVAL_VALIDATION_READY = False

# Backward-compatible names retained for existing callers on the PR branch.
BUILDER_READINESS_SOURCE_ADAPTER = PRODUCTION_REGRESSION_SOURCE_ADAPTER_READY
BUILDER_READINESS_INPUT_READY = PRODUCTION_REGRESSION_INPUT_READY
BUILDER_READINESS_ARTIFACT_AVAILABLE = PRODUCTION_REGRESSION_ARTIFACT_AVAILABLE
BUILDER_READINESS_AGGREGATE_INTERVAL_VALIDATION = AGGREGATE_MANIFEST_INTERVAL_VALIDATION_READY


def is_production_regression_input_ready() -> bool:
    """Return whether production regression input pipelines are ready."""
    return (
        PRODUCTION_REGRESSION_SOURCE_ADAPTER_READY
        and PRODUCTION_REGRESSION_INPUT_READY
        and PRODUCTION_REGRESSION_ARTIFACT_AVAILABLE
        and AGGREGATE_MANIFEST_INTERVAL_VALIDATION_READY
    )


def orchestrate_production_regression_input(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Production orchestrator entry point. Returns None when readiness flags are False."""
    if not is_production_regression_input_ready():
        return None
    return None


def build_regression_input_dataset(
    source_market_date: str,
    rows: list[dict[str, Any]],
    aggregate_manifest_object: str,
    aggregate_manifest_sha256: str,
    code_commit_sha: str | None = None,
    source_objects: list[dict[str, Any]] | None = None,
    factor_definitions: list[dict[str, Any]] | None = None,
    calendar_sha256: str = "c1a2b3e4f5d6a789901234567890abcdefc1a2b3e4f5d6a789901234567890ab",
    calendar_version: str = "2026.1",
    trading_calendar: TradingCalendar | None = None,
) -> dict[str, Any]:
    """Pure builder function to construct RegressionInputDataset document dict from verified rows."""
    if not rows:
        raise ValueError("Rows list cannot be empty")
    if trading_calendar is None:
        raise ValueError("trading_calendar is required")
    resolved_commit_sha = (code_commit_sha or git_commit_sha()).lower()
    if HEX_40_RE.fullmatch(resolved_commit_sha) is None:
        raise ValueError("code_commit_sha must be lowercase 40-hex")

    sorted_rows = sorted(rows, key=lambda x: x["feature_session"])
    rows_sha = compute_canonical_rows_sha256(sorted_rows)

    first_feature = sorted_rows[0]["feature_session"]
    last_feature = sorted_rows[-1]["feature_session"]
    first_label_end = sorted_rows[0]["label_end_session"]
    last_label_end = sorted_rows[-1]["label_end_session"]
    first_feature_date = dt.date.fromisoformat(first_feature)
    source_date = dt.date.fromisoformat(source_market_date)
    if not trading_calendar.is_session(source_date):
        raise ValueError("source_market_date must be a trading session")
    lookback_start = trading_calendar.session_offset(first_feature_date, -20).isoformat()

    if source_objects is None:
        source_objects = [
            {
                "object": aggregate_manifest_object,
                "sha256": aggregate_manifest_sha256,
                "kind": "absorb-quant-manifest",
                "schema_version": 1,
                "source_market_date": source_market_date,
            }
        ]

    if factor_definitions is None:
        factor_definitions = [
            {
                "name": "volume_surge_ratio",
                "source_object_kind": "twse_market_daily_summary",
                "source_field": "total_shares_traded",
                "unit": "ratio",
                "formula": "Session t total shares traded divided by 20-session arithmetic mean volume (sessions t-19 to t)",
                "lookback_sessions": 20,
                "lag_sessions": 0,
                "missing_policy": "listwise_deletion",
                "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                "standardization_policy": "z_score_sample_std_ddof_1",
            },
            {
                "name": "foreign_net_flow_ratio",
                "source_object_kind": "twse_institutional_flow",
                "source_field": "foreign_net_buy_twd_million",
                "unit": "ratio",
                "formula": "Session t foreign net buy value divided by total session turnover in TWD million",
                "lookback_sessions": 1,
                "lag_sessions": 0,
                "missing_policy": "listwise_deletion",
                "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                "standardization_policy": "z_score_sample_std_ddof_1",
            },
            {
                "name": "volatility_20d",
                "source_object_kind": "twse_taiex_daily_closing",
                "source_field": "closing_price",
                "unit": "daily_std",
                "formula": "20-session sample standard deviation (ddof=1) of daily log returns generated from closing prices P[t-20] through P[t]",
                "lookback_sessions": 20,
                "required_price_observations": 21,
                "lag_sessions": 0,
                "missing_policy": "listwise_deletion",
                "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                "standardization_policy": "z_score_sample_std_ddof_1",
            },
        ]

    doc = {
        "schema_version": 1,
        "kind": "absorb-regression-input-dataset",
        "identity": {
            "dataset_id": f"TW-{source_market_date.replace('-', '')}-input-dataset-v1",
            "market": "TW",
            "analysis_scope": "market_level_daily",
            "source_market_date": source_market_date,
            "first_feature_session": first_feature,
            "last_feature_session": last_feature,
            "first_label_end_session": first_label_end,
            "last_label_end_session": last_label_end,
            "first_source_session": lookback_start,
            "last_source_session": source_market_date,
            "lookback_start_session": lookback_start,
            "source_object_count": len(source_objects),
            "aggregate_manifest_object": aggregate_manifest_object,
            "aggregate_manifest_sha256": aggregate_manifest_sha256,
            "aggregate_manifest_schema_version": 1,
            "row_count": len(sorted_rows),
            "calendar_id": "TWSE_TRADING_CALENDAR",
            "calendar_version": calendar_version,
            "calendar_sha256": calendar_sha256,
            "canonical_rows_sha256": rows_sha,
            "code_commit_sha": resolved_commit_sha,
            "content_sha256": "",
        },
        "source_objects": source_objects,
        "factor_definitions": factor_definitions,
        "preprocessing_policy": {
            "factor_value_stage": "raw",
            "missing_value_policy": "listwise_deletion",
            "winsorization_policy": "1st_99th_percentile_linear_interpolation",
            "standardization_policy": "z_score_sample_std_ddof_1",
        },
        "rows": sorted_rows,
    }

    content_sha = compute_regression_input_dataset_content_sha256(doc)
    doc["identity"]["content_sha256"] = content_sha

    # Schema validation check
    RegressionInputDataset.from_document(doc, trading_calendar=trading_calendar)
    return doc
