# -*- coding: utf-8 -*-
"""Dataclasses and serializers for RegressionInputDataset."""

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

REGRESSION_INPUT_DATASET_SCHEMA_VERSION = 1
REGRESSION_INPUT_DATASET_KIND = "absorb-regression-input-dataset"
MAX_REGRESSION_INPUT_DATASET_BYTES = 5_000_000

AGGREGATE_MANIFEST_PATH_RE = re.compile(r"^quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$")
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


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
        return {
            "dataset_id": self.dataset_id,
            "market": self.market,
            "analysis_scope": self.analysis_scope,
            "source_market_date": self.source_market_date,
            "first_feature_session": self.first_feature_session,
            "last_feature_session": self.last_feature_session,
            "first_label_end_session": self.first_label_end_session,
            "last_label_end_session": self.last_label_end_session,
            "first_source_session": self.first_source_session,
            "last_source_session": self.last_source_session,
            "lookback_start_session": self.lookback_start_session,
            "source_object_count": self.source_object_count,
            "aggregate_manifest_object": self.aggregate_manifest_object,
            "aggregate_manifest_sha256": self.aggregate_manifest_sha256,
            "aggregate_manifest_schema_version": self.aggregate_manifest_schema_version,
            "row_count": self.row_count,
            "calendar_id": self.calendar_id,
            "calendar_version": self.calendar_version,
            "calendar_sha256": self.calendar_sha256,
            "canonical_rows_sha256": self.canonical_rows_sha256,
            "code_commit_sha": self.code_commit_sha,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionInputIdentity":
        agg_obj = str(data["aggregate_manifest_object"])
        agg_sha = str(data["aggregate_manifest_sha256"])
        cal_sha = str(data["calendar_sha256"])
        if not AGGREGATE_MANIFEST_PATH_RE.fullmatch(agg_obj):
            raise ValueError(f"Invalid aggregate_manifest_object path: {agg_obj}")
        if not HEX_64_RE.fullmatch(agg_sha):
            raise ValueError(f"Invalid aggregate_manifest_sha256 (must be 64 lowercase hex): {agg_sha}")
        if not HEX_64_RE.fullmatch(cal_sha):
            raise ValueError(f"Invalid calendar_sha256 (must be 64 lowercase hex): {cal_sha}")
        if int(data["aggregate_manifest_schema_version"]) != 1:
            raise ValueError(f"Invalid aggregate_manifest_schema_version: {data.get('aggregate_manifest_schema_version')}")

        return cls(
            dataset_id=data["dataset_id"],
            market=data["market"],
            analysis_scope=data["analysis_scope"],
            source_market_date=data["source_market_date"],
            first_feature_session=data["first_feature_session"],
            last_feature_session=data["last_feature_session"],
            first_label_end_session=data["first_label_end_session"],
            last_label_end_session=data["last_label_end_session"],
            first_source_session=data["first_source_session"],
            last_source_session=data["last_source_session"],
            lookback_start_session=data["lookback_start_session"],
            source_object_count=int(data["source_object_count"]),
            aggregate_manifest_object=agg_obj,
            aggregate_manifest_sha256=agg_sha,
            aggregate_manifest_schema_version=int(data["aggregate_manifest_schema_version"]),
            row_count=int(data["row_count"]),
            calendar_id=data["calendar_id"],
            calendar_version=data["calendar_version"],
            calendar_sha256=cal_sha,
            canonical_rows_sha256=data["canonical_rows_sha256"],
            code_commit_sha=data["code_commit_sha"],
            content_sha256=data.get("content_sha256", ""),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionInputRow":
        close_t = data["taiex_close_t"]
        close_t5 = data["taiex_close_t_plus_5"]
        fwd_ret = data["five_session_forward_return"]
        if isinstance(close_t, bool) or isinstance(close_t5, bool) or isinstance(fwd_ret, bool):
            raise TypeError("Bools not allowed as numeric values")
        if not (isinstance(close_t, (int, float)) and isinstance(close_t5, (int, float)) and isinstance(fwd_ret, (int, float))):
            raise TypeError("Row prices and returns must be numeric")

        factors = {}
        for k, v in data.get("factor_values", {}).items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError(f"Factor value for {k} must be numeric float, got {type(v)}")
            factors[k] = float(v)

        return cls(
            feature_session=data["feature_session"],
            label_end_session=data["label_end_session"],
            taiex_close_t=float(close_t),
            taiex_close_t_plus_5=float(close_t5),
            five_session_forward_return=float(fwd_ret),
            factor_values=factors,
        )


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
            "source_objects": list(self.source_objects),
            "factor_definitions": list(self.factor_definitions),
            "preprocessing_policy": dict(self.preprocessing_policy),
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "RegressionInputDataset":
        if not isinstance(document, dict) or not document:
            raise ValueError("Input dataset document must be non-empty dict")
        if document.get("schema_version") != REGRESSION_INPUT_DATASET_SCHEMA_VERSION:
            raise ValueError(f"Invalid schema_version: {document.get('schema_version')}")
        if document.get("kind") != REGRESSION_INPUT_DATASET_KIND:
            raise ValueError(f"Invalid kind: {document.get('kind')}")

        prep_policy = document.get("preprocessing_policy", {})
        if prep_policy.get("factor_value_stage") != "raw":
            raise ValueError(f"factor_value_stage must be 'raw', got {prep_policy.get('factor_value_stage')}")

        identity = RegressionInputIdentity.from_dict(document["identity"])
        rows_data = document.get("rows", [])
        if len(rows_data) != identity.row_count:
            raise ValueError(f"row_count mismatch: identity specified {identity.row_count}, got {len(rows_data)} rows")

        rows = []
        prev_session = None
        for r_dict in rows_data:
            r = RegressionInputRow.from_dict(r_dict)
            if prev_session is not None and r.feature_session <= prev_session:
                raise ValueError(f"Rows must be sorted strictly by feature_session ascending without duplicates: {r.feature_session} <= {prev_session}")
            prev_session = r.feature_session
            rows.append(r)

        return cls(
            schema_version=int(document["schema_version"]),
            kind=str(document["kind"]),
            identity=identity,
            source_objects=list(document.get("source_objects", [])),
            factor_definitions=list(document.get("factor_definitions", [])),
            preprocessing_policy=dict(prep_policy),
            rows=rows,
        )


def serialize_regression_rows(rows: list[dict[str, Any] | RegressionInputRow]) -> bytes:
    """Serialize row dictionaries deterministically for rows_sha256 calculation."""
    raw_rows = [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]
    return json.dumps(
        raw_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_canonical_rows_sha256(rows: list[dict[str, Any] | RegressionInputRow]) -> str:
    """Compute SHA-256 over serialized canonical rows."""
    serialized_rows = serialize_regression_rows(rows)
    return hashlib.sha256(serialized_rows).hexdigest()


def serialize_regression_input_dataset(document: dict[str, Any]) -> bytes:
    """Serialize RegressionInputDataset document into canonical UTF-8 JSON bytes."""
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(serialized) > MAX_REGRESSION_INPUT_DATASET_BYTES:
        raise ValueError(f"Serialized input dataset exceeds size limit: {len(serialized)} > {MAX_REGRESSION_INPUT_DATASET_BYTES}")
    return serialized


def compute_regression_input_dataset_content_sha256(document: dict[str, Any]) -> str:
    """Compute semantic content SHA-256 over canonical bytes with content_sha256=''."""
    doc_copy = json.loads(json.dumps(document))
    if "identity" in doc_copy:
        doc_copy["identity"]["content_sha256"] = ""
    canonical_bytes = serialize_regression_input_dataset(doc_copy)
    return hashlib.sha256(canonical_bytes).hexdigest()
