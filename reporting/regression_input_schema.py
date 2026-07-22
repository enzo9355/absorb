# -*- coding: utf-8 -*-
"""Strict schema and canonical serializers for RegressionInputDataset."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Protocol


REGRESSION_INPUT_DATASET_SCHEMA_VERSION = 1
REGRESSION_INPUT_DATASET_KIND = "absorb-regression-input-dataset"
MAX_REGRESSION_INPUT_DATASET_BYTES = 5_000_000

AGGREGATE_MANIFEST_PATH_RE = re.compile(
    r"^quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$"
)
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
V1_FACTORS = (
    "volume_surge_ratio",
    "foreign_net_flow_ratio",
    "volatility_20d",
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "identity",
    "source_objects",
    "factor_definitions",
    "preprocessing_policy",
    "rows",
}
_IDENTITY_KEYS = {
    "dataset_id",
    "market",
    "analysis_scope",
    "source_market_date",
    "first_feature_session",
    "last_feature_session",
    "first_label_end_session",
    "last_label_end_session",
    "first_source_session",
    "last_source_session",
    "lookback_start_session",
    "source_object_count",
    "aggregate_manifest_object",
    "aggregate_manifest_sha256",
    "aggregate_manifest_schema_version",
    "row_count",
    "calendar_id",
    "calendar_version",
    "calendar_sha256",
    "canonical_rows_sha256",
    "code_commit_sha",
    "content_sha256",
}
_SOURCE_OBJECT_KEYS = {
    "object",
    "sha256",
    "kind",
    "schema_version",
    "source_market_date",
}
_FACTOR_DEFINITION_KEYS = {
    "name",
    "source_object_kind",
    "source_field",
    "unit",
    "formula",
    "lookback_sessions",
    "lag_sessions",
    "missing_policy",
    "winsorization_policy",
    "standardization_policy",
}
_PREPROCESSING_POLICY = {
    "factor_value_stage": "raw",
    "missing_value_policy": "listwise_deletion",
    "winsorization_policy": "1st_99th_percentile_linear_interpolation",
    "standardization_policy": "z_score_sample_std_ddof_1",
}
_ROW_KEYS = {
    "feature_session",
    "label_end_session",
    "taiex_close_t",
    "taiex_close_t_plus_5",
    "five_session_forward_return",
    "factor_values",
}
_FACTOR_DEFINITIONS = {
    "volume_surge_ratio": {
        "source_object_kind": "twse_market_daily_summary",
        "source_field": "total_shares_traded",
        "unit": "ratio",
        "formula": "Session t total shares traded divided by 20-session arithmetic mean volume (sessions t-19 to t)",
        "lookback_sessions": 20,
    },
    "foreign_net_flow_ratio": {
        "source_object_kind": "twse_institutional_flow",
        "source_field": "foreign_net_buy_twd_million",
        "unit": "ratio",
        "formula": "Session t foreign net buy value divided by total session turnover in TWD million",
        "lookback_sessions": 1,
    },
    "volatility_20d": {
        "source_object_kind": "twse_taiex_daily_closing",
        "source_field": "closing_price",
        "unit": "daily_std",
        "formula": "20-session sample standard deviation (ddof=1) of daily log returns over closing prices (sessions t-19 to t)",
        "lookback_sessions": 20,
    },
}
_FACTOR_COMMON = {
    "lag_sessions": 0,
    "missing_policy": "listwise_deletion",
    "winsorization_policy": "1st_99th_percentile_linear_interpolation",
    "standardization_policy": "z_score_sample_std_ddof_1",
}


class TradingCalendar(Protocol):
    """Minimum verified calendar contract shared by schema and builders."""

    def is_session(self, value: dt.date) -> bool: ...

    def session_offset(self, value: dt.date, offset: int) -> dt.date: ...


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} keys must match schema exactly")
    return value


def _date(value: Any, label: str) -> dt.date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be ISO 8601 YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO 8601 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be ISO 8601 YYYY-MM-DD")
    return parsed


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _sha(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase hexadecimal")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric and bool is not allowed")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be finite")
    if positive and converted <= 0:
        raise ValueError(f"{label} must be > 0")
    return converted


@dataclass(frozen=True)
class RegressionInputIdentity:
    dataset_id: str
    market: str
    analysis_scope: str
    source_market_date: str
    first_feature_session: str
    last_feature_session: str
    first_label_end_session: str
    last_label_end_session: str
    first_source_session: str
    last_source_session: str
    lookback_start_session: str
    source_object_count: int
    aggregate_manifest_object: str
    aggregate_manifest_sha256: str
    aggregate_manifest_schema_version: int
    row_count: int
    calendar_id: str
    calendar_version: str
    calendar_sha256: str
    canonical_rows_sha256: str
    code_commit_sha: str
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in _IDENTITY_KEYS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionInputIdentity":
        _exact_keys(data, _IDENTITY_KEYS, "identity")
        return cls(**data)


@dataclass(frozen=True)
class RegressionInputRow:
    feature_session: str
    label_end_session: str
    taiex_close_t: float
    taiex_close_t_plus_5: float
    five_session_forward_return: float
    factor_values: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_session": self.feature_session,
            "label_end_session": self.label_end_session,
            "taiex_close_t": self.taiex_close_t,
            "taiex_close_t_plus_5": self.taiex_close_t_plus_5,
            "five_session_forward_return": self.five_session_forward_return,
            "factor_values": dict(self.factor_values),
        }


@dataclass(frozen=True)
class RegressionInputDataset:
    schema_version: int
    kind: str
    identity: RegressionInputIdentity
    source_objects: list[dict[str, Any]]
    factor_definitions: list[dict[str, Any]]
    preprocessing_policy: dict[str, Any]
    rows: list[RegressionInputRow]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "identity": self.identity.to_dict(),
            "source_objects": [dict(item) for item in self.source_objects],
            "factor_definitions": [dict(item) for item in self.factor_definitions],
            "preprocessing_policy": dict(self.preprocessing_policy),
            "rows": [row.to_dict() for row in self.rows],
        }

    @classmethod
    def from_document(
        cls,
        document: dict[str, Any],
        *,
        trading_calendar: TradingCalendar,
    ) -> "RegressionInputDataset":
        top = _exact_keys(document, _TOP_LEVEL_KEYS, "Input dataset top-level")
        if top["schema_version"] != REGRESSION_INPUT_DATASET_SCHEMA_VERSION:
            raise ValueError("Invalid schema_version")
        if top["kind"] != REGRESSION_INPUT_DATASET_KIND:
            raise ValueError("Invalid kind")
        if trading_calendar is None:
            raise ValueError("trading_calendar is required")

        identity_data = _exact_keys(top["identity"], _IDENTITY_KEYS, "identity")
        if identity_data["market"] != "TW":
            raise ValueError("identity.market must be TW")
        if identity_data["analysis_scope"] != "market_level_daily":
            raise ValueError("identity.analysis_scope must be market_level_daily")
        if not isinstance(identity_data["dataset_id"], str) or not identity_data["dataset_id"]:
            raise ValueError("identity.dataset_id must be non-empty")
        if identity_data["calendar_id"] != "TWSE_TRADING_CALENDAR":
            raise ValueError("identity.calendar_id must be TWSE_TRADING_CALENDAR")
        if not isinstance(identity_data["calendar_version"], str) or not identity_data["calendar_version"]:
            raise ValueError("identity.calendar_version must be non-empty")

        date_fields = (
            "source_market_date",
            "first_feature_session",
            "last_feature_session",
            "first_label_end_session",
            "last_label_end_session",
            "first_source_session",
            "last_source_session",
            "lookback_start_session",
        )
        dates = {field: _date(identity_data[field], f"identity.{field}") for field in date_fields}
        for field, value in dates.items():
            if not trading_calendar.is_session(value):
                raise ValueError(f"identity.{field} must be a trading session")
        if dates["first_feature_session"] > dates["last_feature_session"]:
            raise ValueError("feature session boundaries are reversed")
        if dates["first_label_end_session"] > dates["last_label_end_session"]:
            raise ValueError("label session boundaries are reversed")
        if dates["first_source_session"] > dates["last_source_session"]:
            raise ValueError("source session boundaries are reversed")

        source_objects = top["source_objects"]
        factor_definitions = top["factor_definitions"]
        rows_data = top["rows"]
        if not isinstance(source_objects, list) or not isinstance(factor_definitions, list) or not isinstance(rows_data, list):
            raise ValueError("source_objects, factor_definitions, and rows must be lists")
        source_count = _integer(identity_data["source_object_count"], "source_object_count", minimum=1)
        row_count = _integer(identity_data["row_count"], "row_count", minimum=1)
        if source_count != len(source_objects):
            raise ValueError("source_object_count must equal len(source_objects)")
        if row_count != len(rows_data) or row_count > 252:
            raise ValueError("row_count must equal len(rows) and be <= 252")
        if identity_data["aggregate_manifest_schema_version"] != 1:
            raise ValueError("aggregate_manifest_schema_version must be 1")
        if not isinstance(identity_data["aggregate_manifest_object"], str) or AGGREGATE_MANIFEST_PATH_RE.fullmatch(identity_data["aggregate_manifest_object"]) is None:
            raise ValueError("aggregate_manifest_object path is invalid")
        for field in (
            "aggregate_manifest_sha256",
            "calendar_sha256",
            "canonical_rows_sha256",
            "content_sha256",
        ):
            _sha(identity_data[field], HEX_64_RE, field)
        _sha(identity_data["code_commit_sha"], HEX_40_RE, "code_commit_sha")

        for source in source_objects:
            _exact_keys(source, _SOURCE_OBJECT_KEYS, "source object")
            _sha(source["sha256"], HEX_64_RE, "source object sha256")
            _date(source["source_market_date"], "source object source_market_date")
            if source["schema_version"] != 1:
                raise ValueError("source object schema_version must be 1")

        names = []
        for definition in factor_definitions:
            _exact_keys(definition, _FACTOR_DEFINITION_KEYS, "factor definition")
            name = definition["name"]
            names.append(name)
            expected = _FACTOR_DEFINITIONS.get(name)
            if expected is None or any(definition.get(key) != value for key, value in {**expected, **_FACTOR_COMMON}.items()):
                raise ValueError("factor definitions must match the three v1 contracts")
        if tuple(names) != V1_FACTORS:
            raise ValueError("factor definitions must contain the three v1 factors exactly once")
        _exact_keys(top["preprocessing_policy"], set(_PREPROCESSING_POLICY), "preprocessing_policy")
        if top["preprocessing_policy"] != _PREPROCESSING_POLICY:
            raise ValueError("preprocessing policy must keep factor values raw")

        rows: list[RegressionInputRow] = []
        previous_feature: dt.date | None = None
        for row_data in rows_data:
            _exact_keys(row_data, _ROW_KEYS, "row")
            feature = _date(row_data["feature_session"], "feature_session")
            label_end = _date(row_data["label_end_session"], "label_end_session")
            if not trading_calendar.is_session(feature) or not trading_calendar.is_session(label_end):
                raise ValueError("feature_session and label_end_session must be trading sessions")
            if previous_feature is not None and feature <= previous_feature:
                raise ValueError("feature_session must be strictly ascending without duplicates")
            previous_feature = feature
            if trading_calendar.session_offset(feature, 5) != label_end:
                raise ValueError("label_end_session must be exactly five trading sessions after feature_session")
            if label_end > dates["source_market_date"]:
                raise ValueError("label_end_session must not exceed source_market_date")

            close_t = _number(row_data["taiex_close_t"], "taiex_close_t", positive=True)
            close_t5 = _number(row_data["taiex_close_t_plus_5"], "taiex_close_t_plus_5", positive=True)
            forward_return = _number(row_data["five_session_forward_return"], "five_session_forward_return")
            expected_return = close_t5 / close_t - 1.0
            if abs(forward_return - expected_return) > 1e-6:
                raise ValueError("five_session_forward_return does not match close-derived forward return")
            factor_values = _exact_keys(row_data["factor_values"], set(V1_FACTORS), "factor values")
            factors = {name: _number(factor_values[name], f"factor {name}") for name in V1_FACTORS}
            rows.append(
                RegressionInputRow(
                    feature_session=feature.isoformat(),
                    label_end_session=label_end.isoformat(),
                    taiex_close_t=close_t,
                    taiex_close_t_plus_5=close_t5,
                    five_session_forward_return=forward_return,
                    factor_values=factors,
                )
            )

        if (
            rows[0].feature_session != identity_data["first_feature_session"]
            or rows[-1].feature_session != identity_data["last_feature_session"]
            or rows[0].label_end_session != identity_data["first_label_end_session"]
            or rows[-1].label_end_session != identity_data["last_label_end_session"]
        ):
            raise ValueError("identity row boundary sessions do not match rows")

        rows_sha = compute_canonical_rows_sha256(rows_data)
        if rows_sha != identity_data["canonical_rows_sha256"]:
            raise ValueError("canonical_rows_sha256 mismatch")
        content_sha = compute_regression_input_dataset_content_sha256(document)
        if content_sha != identity_data["content_sha256"]:
            raise ValueError("content_sha256 mismatch")

        return cls(
            schema_version=REGRESSION_INPUT_DATASET_SCHEMA_VERSION,
            kind=REGRESSION_INPUT_DATASET_KIND,
            identity=RegressionInputIdentity.from_dict(identity_data),
            source_objects=[dict(item) for item in source_objects],
            factor_definitions=[dict(item) for item in factor_definitions],
            preprocessing_policy=dict(top["preprocessing_policy"]),
            rows=rows,
        )


def serialize_regression_rows(rows: list[dict[str, Any] | RegressionInputRow]) -> bytes:
    raw_rows = [row.to_dict() if isinstance(row, RegressionInputRow) else row for row in rows]
    return json.dumps(
        raw_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_canonical_rows_sha256(rows: list[dict[str, Any] | RegressionInputRow]) -> str:
    return hashlib.sha256(serialize_regression_rows(rows)).hexdigest()


def serialize_regression_input_dataset(document: dict[str, Any]) -> bytes:
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if not serialized or len(serialized) > MAX_REGRESSION_INPUT_DATASET_BYTES:
        raise ValueError("Serialized input dataset size is outside allowed range")
    return serialized


def compute_regression_input_dataset_content_sha256(document: dict[str, Any]) -> str:
    doc_copy = json.loads(json.dumps(document, allow_nan=False))
    doc_copy["identity"]["content_sha256"] = ""
    return hashlib.sha256(serialize_regression_input_dataset(doc_copy)).hexdigest()
