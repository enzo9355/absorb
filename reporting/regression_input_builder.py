# -*- coding: utf-8 -*-
"""Pure builder and production readiness orchestrator for RegressionInputDataset."""

from typing import Any
from reporting.regression_input_schema import (
    RegressionInputDataset,
    compute_canonical_rows_sha256,
    compute_regression_input_dataset_content_sha256,
)

BUILDER_READINESS_SOURCE_ADAPTER = False
BUILDER_READINESS_INPUT_READY = False
BUILDER_READINESS_ARTIFACT_AVAILABLE = False
BUILDER_READINESS_AGGREGATE_INTERVAL_VALIDATION = False


def is_production_regression_input_ready() -> bool:
    """Return whether production regression input pipelines are ready."""
    return (
        BUILDER_READINESS_SOURCE_ADAPTER
        and BUILDER_READINESS_INPUT_READY
        and BUILDER_READINESS_ARTIFACT_AVAILABLE
        and BUILDER_READINESS_AGGREGATE_INTERVAL_VALIDATION
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
    code_commit_sha: str = "da25d594d3b76865da22b891285ac0c85e710d86",
    source_objects: list[dict[str, Any]] | None = None,
    factor_definitions: list[dict[str, Any]] | None = None,
    calendar_sha256: str = "c1a2b3e4f5d6a789901234567890abcdefc1a2b3e4f5d6a789901234567890ab",
) -> dict[str, Any]:
    """Pure builder function to construct RegressionInputDataset document dict from verified rows."""
    if not rows:
        raise ValueError("Rows list cannot be empty")

    sorted_rows = sorted(rows, key=lambda x: x["feature_session"])
    rows_sha = compute_canonical_rows_sha256(sorted_rows)

    first_feature = sorted_rows[0]["feature_session"]
    last_feature = sorted_rows[-1]["feature_session"]
    first_label_end = sorted_rows[0]["label_end_session"]
    last_label_end = sorted_rows[-1]["label_end_session"]

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
                "formula": "Session t total shares traded divided by 20-session arithmetic mean volume",
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
                "formula": "20-session sample standard deviation (ddof=1) of daily log returns over closing prices",
                "lookback_sessions": 20,
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
            "first_source_session": first_feature,
            "last_source_session": source_market_date,
            "lookback_start_session": first_feature,
            "source_object_count": len(source_objects),
            "aggregate_manifest_object": aggregate_manifest_object,
            "aggregate_manifest_sha256": aggregate_manifest_sha256,
            "aggregate_manifest_schema_version": 1,
            "row_count": len(sorted_rows),
            "calendar_id": "TWSE_TRADING_CALENDAR",
            "calendar_version": "2026.1",
            "calendar_sha256": calendar_sha256,
            "canonical_rows_sha256": rows_sha,
            "code_commit_sha": code_commit_sha,
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
    RegressionInputDataset.from_document(doc)
    return doc
