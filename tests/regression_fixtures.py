"""Deterministic regression contract fixtures built from real calendar behavior."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json

from stock_papi.batch.calendar import TWSE_CALENDAR_URL, TradingCalendarSet


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COMMIT_SHA = "d" * 40
DISCLOSURE = "模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"
FACTORS = ("volume_surge_ratio", "foreign_net_flow_ratio", "volatility_20d")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _calendar_document(year: int, *, closed: tuple[str, ...] = ()) -> dict:
    return {
        "schema_version": 1,
        "market": "TW",
        "year": year,
        "source_url": TWSE_CALENDAR_URL,
        "fetched_at": f"{year}-01-01T00:00:00Z",
        "source_sha256": SHA_C,
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "closed_dates": list(closed),
        "special_open_dates": [],
    }


def trading_calendar(*, closed_2026: tuple[str, ...] = ()) -> TradingCalendarSet:
    return TradingCalendarSet.from_documents(
        [_calendar_document(2025), _calendar_document(2026, closed=closed_2026)]
    )


def session_dates(
    calendar: TradingCalendarSet,
    start: str,
    count: int,
) -> list[dt.date]:
    current = dt.date.fromisoformat(start)
    while not calendar.is_session(current):
        current += dt.timedelta(days=1)
    result = [current]
    for _ in range(count - 1):
        current = calendar.next_session(current)
        result.append(current)
    return result


def input_rows(
    calendar: TradingCalendarSet,
    *,
    start: str = "2026-05-01",
    count: int = 35,
) -> list[dict]:
    rows = []
    for index, feature_date in enumerate(session_dates(calendar, start, count)):
        label_date = calendar.session_offset(feature_date, 5)
        close_t = 20_000.0 + index * 13.0
        forward_return = 0.002 + index * 0.0001
        rows.append(
            {
                "feature_session": feature_date.isoformat(),
                "label_end_session": label_date.isoformat(),
                "taiex_close_t": close_t,
                "taiex_close_t_plus_5": close_t * (1.0 + forward_return),
                "five_session_forward_return": forward_return,
                "factor_values": {
                    "volume_surge_ratio": 0.9 + index * 0.01,
                    "foreign_net_flow_ratio": ((index * 7) % 19 - 9) * 0.002,
                    "volatility_20d": 0.01 + (index % 7) * 0.0005,
                },
            }
        )
    return rows


def factor_definitions() -> list[dict]:
    common = {
        "lag_sessions": 0,
        "missing_policy": "listwise_deletion",
        "winsorization_policy": "1st_99th_percentile_linear_interpolation",
        "standardization_policy": "z_score_sample_std_ddof_1",
    }
    return [
        {
            **common,
            "name": "volume_surge_ratio",
            "source_object_kind": "twse_market_daily_summary",
            "source_field": "total_shares_traded",
            "unit": "ratio",
            "formula": "Session t total shares traded divided by 20-session arithmetic mean volume (sessions t-19 to t)",
            "lookback_sessions": 20,
        },
        {
            **common,
            "name": "foreign_net_flow_ratio",
            "source_object_kind": "twse_institutional_flow",
            "source_field": "foreign_net_buy_twd_million",
            "unit": "ratio",
            "formula": "Session t foreign net buy value divided by total session turnover in TWD million",
            "lookback_sessions": 1,
        },
        {
            **common,
            "name": "volatility_20d",
            "source_object_kind": "twse_taiex_daily_closing",
            "source_field": "closing_price",
            "unit": "daily_std",
            "formula": "20-session sample standard deviation (ddof=1) of daily log returns generated from closing prices P[t-20] through P[t]",
            "lookback_sessions": 20,
            "required_price_observations": 21,
        },
    ]


def make_input_document(
    *,
    calendar: TradingCalendarSet | None = None,
    rows: list[dict] | None = None,
    source_market_date: str = "2026-07-17",
) -> dict:
    calendar = calendar or trading_calendar()
    rows = copy.deepcopy(rows or input_rows(calendar))
    manifest = "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json"
    document = {
        "schema_version": 1,
        "kind": "absorb-regression-input-dataset",
        "identity": {
            "dataset_id": "TW-20260717-input-dataset-v1",
            "market": "TW",
            "analysis_scope": "market_level_daily",
            "source_market_date": source_market_date,
            "first_feature_session": rows[0]["feature_session"],
            "last_feature_session": rows[-1]["feature_session"],
            "first_label_end_session": rows[0]["label_end_session"],
            "last_label_end_session": rows[-1]["label_end_session"],
            "first_source_session": calendar.session_offset(
                dt.date.fromisoformat(rows[0]["feature_session"]),
                -20,
            ).isoformat(),
            "last_source_session": source_market_date,
            "lookback_start_session": calendar.session_offset(
                dt.date.fromisoformat(rows[0]["feature_session"]),
                -20,
            ).isoformat(),
            "source_object_count": 1,
            "aggregate_manifest_object": manifest,
            "aggregate_manifest_sha256": SHA_A,
            "aggregate_manifest_schema_version": 1,
            "row_count": len(rows),
            "calendar_id": "TWSE_TRADING_CALENDAR",
            "calendar_version": "2026.1",
            "calendar_sha256": SHA_C,
            "canonical_rows_sha256": hashlib.sha256(_canonical(rows)).hexdigest(),
            "code_commit_sha": COMMIT_SHA,
            "content_sha256": "",
        },
        "source_objects": [
            {
                "object": manifest,
                "sha256": SHA_A,
                "kind": "absorb-quant-manifest",
                "schema_version": 1,
                "source_market_date": source_market_date,
            }
        ],
        "factor_definitions": factor_definitions(),
        "preprocessing_policy": {
            "factor_value_stage": "raw",
            "missing_value_policy": "listwise_deletion",
            "winsorization_policy": "1st_99th_percentile_linear_interpolation",
            "standardization_policy": "z_score_sample_std_ddof_1",
        },
        "rows": rows,
    }
    return rehash_input_document(document)


def rehash_input_document(document: dict) -> dict:
    document["identity"]["canonical_rows_sha256"] = hashlib.sha256(
        _canonical(document["rows"])
    ).hexdigest()
    document["identity"]["content_sha256"] = ""
    document["identity"]["content_sha256"] = hashlib.sha256(
        _canonical(document)
    ).hexdigest()
    return document


def make_artifact_document() -> dict:
    results = []
    for index, name in enumerate(FACTORS):
        coefficient = (index + 1) * 0.01
        results.append(
            {
                "factor_name": name,
                "display_label": name,
                "coefficient": coefficient,
                "standard_error": 0.005,
                "t_statistic": coefficient / 0.005,
                "p_value": 0.04,
                "confidence_interval_low": coefficient - 0.009,
                "confidence_interval_high": coefficient + 0.009,
                "direction": "positive",
                "economic_magnitude": "moderate",
                "display_status": "statistically_significant",
            }
        )
    document = {
        "schema_version": 1,
        "kind": "absorb-regression-research-artifact",
        "identity": {
            "artifact_id": "TW-20260717-regression-ols-v1",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "generated_at": "2026-07-17T10:30:00Z",
            "source_manifest": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
            "source_manifest_sha256": SHA_A,
            "input_dataset_object": f"objects/regression-input/{SHA_B}.json",
            "input_dataset_sha256": SHA_B,
            "input_dataset_content_sha256": SHA_C,
            "input_dataset_rows_sha256": SHA_A,
            "code_commit_sha": COMMIT_SHA,
            "generator_version": "1.0.0",
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
            "independent_variables": list(FACTORS),
            "intercept": True,
            "frequency": "daily",
            "first_feature_session": "2025-07-10",
            "last_feature_session": "2026-07-10",
            "first_label_end_session": "2025-07-17",
            "last_label_end_session": "2026-07-17",
            "label_horizon_sessions": 5,
            "sample_count": 60,
            "missing_value_policy": "listwise_deletion",
            "standardization_policy": "z_score",
            "outlier_policy": "winsorize_1_99",
            "covariance_estimator": "newey_west_hac",
            "hac_max_lags": 4,
            "confidence_level": 0.95,
        },
        "results": results,
        "fit_statistics": {
            "r_squared": 0.2,
            "adjusted_r_squared": 0.15,
            "residual_standard_error": 0.03,
            "degrees_of_freedom": 56,
            "f_statistic": 5.0,
            "f_p_value": 0.01,
        },
        "diagnostics": {
            "multicollinearity": {
                "status": "passed",
                "max_vif": 1.5,
                "note": "VIF excludes intercept",
                "vif_details": {name: 1.5 for name in FACTORS},
            },
            "heteroskedasticity": {
                "status": "passed",
                "test_name": "breusch_pagan",
                "test_statistic": 2.0,
                "p_value": 0.2,
                "threshold": 0.05,
            },
            "autocorrelation": {"status": "passed", "durbin_watson": 2.0},
            "residual_normality": {"status": "passed", "jarque_bera_p_value": 0.4},
            "data_quality": {"missing_rate": 0.0, "outlier_count": 0},
            "warnings": [],
        },
        "presentation": {
            "headline": "歷史因子迴歸分析",
            "summary": "模型方向參考",
            "key_exposures": ["三項市場因子"],
            "limitations": "歷史統計關係不代表未來因果關係。",
            "disclosure": DISCLOSURE,
        },
    }
    return rehash_artifact_document(document)


def rehash_artifact_document(document: dict) -> dict:
    document["identity"]["content_sha256"] = ""
    document["identity"]["content_sha256"] = hashlib.sha256(
        _canonical(document)
    ).hexdigest()
    return document
