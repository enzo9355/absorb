# -*- coding: utf-8 -*-
"""Strict schema and canonical serializer for regression research artifacts."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import re
from typing import Any

from reporting.regression_input_schema import AGGREGATE_MANIFEST_PATH_RE, HEX_40_RE, HEX_64_RE, V1_FACTORS


REGRESSION_ARTIFACT_SCHEMA_VERSION = 1
REGRESSION_ARTIFACT_KIND = "absorb-regression-research-artifact"
MAX_REGRESSION_ARTIFACT_BYTES = 2_000_000
MANDATORY_DISCLOSURE = "模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"
INPUT_DATASET_OBJECT_RE = re.compile(r"^objects/regression-input/([0-9a-f]{64})\.json$")
FORBIDDEN_WORDS = (
    "Probability",
    "勝率",
    "上漲機率",
    "下跌機率",
    "正式預測",
    "買進訊號",
    "賣出訊號",
    "保證獲利",
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "identity",
    "regression_spec",
    "results",
    "fit_statistics",
    "diagnostics",
    "presentation",
}
_IDENTITY_KEYS = {
    "artifact_id",
    "market",
    "source_market_date",
    "applicable_trading_date",
    "generated_at",
    "source_manifest",
    "source_manifest_sha256",
    "input_dataset_object",
    "input_dataset_sha256",
    "input_dataset_content_sha256",
    "input_dataset_rows_sha256",
    "code_commit_sha",
    "generator_version",
    "content_sha256",
    "regression_spec_version",
}
_SPEC_KEYS = {
    "analysis_scope",
    "entity_type",
    "universe_definition",
    "observation_unit",
    "model_family",
    "dependent_variable",
    "dependent_variable_definition",
    "independent_variables",
    "intercept",
    "frequency",
    "first_feature_session",
    "last_feature_session",
    "first_label_end_session",
    "last_label_end_session",
    "label_horizon_sessions",
    "sample_count",
    "missing_value_policy",
    "standardization_policy",
    "outlier_policy",
    "covariance_estimator",
    "hac_max_lags",
    "confidence_level",
}
_SPEC_FIXED = {
    "analysis_scope": "market_level_daily",
    "entity_type": "market_index",
    "universe_definition": "TWSE_TAIEX",
    "observation_unit": "daily_session",
    "model_family": "ols_linear_factor",
    "dependent_variable": "five_session_forward_return",
    "intercept": True,
    "frequency": "daily",
    "label_horizon_sessions": 5,
    "missing_value_policy": "listwise_deletion",
    "standardization_policy": "z_score",
    "outlier_policy": "winsorize_1_99",
    "covariance_estimator": "newey_west_hac",
    "hac_max_lags": 4,
    "confidence_level": 0.95,
}
_RESULT_KEYS = {
    "factor_name",
    "display_label",
    "coefficient",
    "standard_error",
    "t_statistic",
    "p_value",
    "confidence_interval_low",
    "confidence_interval_high",
    "direction",
    "economic_magnitude",
    "display_status",
}
_FIT_KEYS = {
    "r_squared",
    "adjusted_r_squared",
    "residual_standard_error",
    "degrees_of_freedom",
    "f_statistic",
    "f_p_value",
}
_DIAGNOSTIC_KEYS = {
    "multicollinearity",
    "heteroskedasticity",
    "autocorrelation",
    "residual_normality",
    "data_quality",
    "warnings",
}
_MULTICOLLINEARITY_KEYS = {"status", "max_vif", "note", "vif_details"}
_HETEROSKEDASTICITY_KEYS = {
    "status",
    "test_name",
    "test_statistic",
    "p_value",
    "threshold",
}
_AUTOCORRELATION_KEYS = {"status", "durbin_watson"}
_RESIDUAL_NORMALITY_KEYS = {"status", "jarque_bera_p_value"}
_DATA_QUALITY_KEYS = {"missing_rate", "outlier_count"}
_DIAGNOSTIC_STATUSES = {"passed", "warning"}
_VIF_MATCH_TOLERANCE = 1e-9
_PRESENTATION_KEYS = {"headline", "summary", "key_exposures", "limitations", "disclosure"}


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


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be timezone-aware ISO 8601")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be timezone-aware ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware ISO 8601")
    return value


def _sha(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase hexadecimal")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric and bool is not allowed")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be finite")
    return converted


def _validate_finite_tree(value: Any, label: str) -> None:
    if isinstance(value, bool):
        raise TypeError(f"{label} must not contain bool numeric values")
    if isinstance(value, (int, float)):
        _number(value, label)
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_tree(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_tree(child, f"{label}[{index}]")


def _visible_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _visible_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _visible_strings(child)


def _validate_diagnostics(data: dict[str, Any]) -> None:
    multicollinearity = _exact_keys(
        data["multicollinearity"],
        _MULTICOLLINEARITY_KEYS,
        "diagnostics.multicollinearity",
    )
    if multicollinearity["status"] not in _DIAGNOSTIC_STATUSES:
        raise ValueError("diagnostics.multicollinearity.status is invalid")
    max_vif = _number(
        multicollinearity["max_vif"],
        "diagnostics.multicollinearity.max_vif",
    )
    if max_vif < 1:
        raise ValueError("diagnostics.multicollinearity.max_vif must be >= 1")
    note = multicollinearity["note"]
    if not isinstance(note, str) or not note.strip():
        raise ValueError("diagnostics.multicollinearity.note must be non-empty")
    vif_details = _exact_keys(
        multicollinearity["vif_details"],
        set(V1_FACTORS),
        "diagnostics.multicollinearity.vif_details",
    )
    vif_values = [
        _number(vif_details[name], f"diagnostics.multicollinearity.vif_details.{name}")
        for name in V1_FACTORS
    ]
    if any(value < 1 for value in vif_values):
        raise ValueError("diagnostics.multicollinearity VIF values must be >= 1")
    if not math.isclose(
        max_vif,
        max(vif_values),
        rel_tol=0.0,
        abs_tol=_VIF_MATCH_TOLERANCE,
    ):
        raise ValueError("diagnostics.multicollinearity.max_vif must match vif_details")

    heteroskedasticity = _exact_keys(
        data["heteroskedasticity"],
        _HETEROSKEDASTICITY_KEYS,
        "diagnostics.heteroskedasticity",
    )
    if heteroskedasticity["test_name"] != "breusch_pagan":
        raise ValueError("diagnostics.heteroskedasticity.test_name is invalid")
    test_statistic = _number(
        heteroskedasticity["test_statistic"],
        "diagnostics.heteroskedasticity.test_statistic",
    )
    p_value = _number(
        heteroskedasticity["p_value"],
        "diagnostics.heteroskedasticity.p_value",
    )
    threshold = _number(
        heteroskedasticity["threshold"],
        "diagnostics.heteroskedasticity.threshold",
    )
    if test_statistic < 0 or not 0 <= p_value <= 1 or threshold != 0.05:
        raise ValueError("diagnostics.heteroskedasticity values are invalid")
    expected_status = "passed" if p_value >= threshold else "warning"
    if heteroskedasticity["status"] != expected_status:
        raise ValueError("diagnostics.heteroskedasticity.status is inconsistent")

    autocorrelation = _exact_keys(
        data["autocorrelation"],
        _AUTOCORRELATION_KEYS,
        "diagnostics.autocorrelation",
    )
    durbin_watson = _number(
        autocorrelation["durbin_watson"],
        "diagnostics.autocorrelation.durbin_watson",
    )
    if not 0 <= durbin_watson <= 4:
        raise ValueError("diagnostics.autocorrelation.durbin_watson must be between 0 and 4")
    expected_status = "passed" if 1.5 <= durbin_watson <= 2.5 else "warning"
    if autocorrelation["status"] != expected_status:
        raise ValueError("diagnostics.autocorrelation.status is inconsistent")

    residual_normality = _exact_keys(
        data["residual_normality"],
        _RESIDUAL_NORMALITY_KEYS,
        "diagnostics.residual_normality",
    )
    jarque_bera_p_value = _number(
        residual_normality["jarque_bera_p_value"],
        "diagnostics.residual_normality.jarque_bera_p_value",
    )
    if not 0 <= jarque_bera_p_value <= 1:
        raise ValueError(
            "diagnostics.residual_normality.jarque_bera_p_value must be between 0 and 1"
        )
    expected_status = "passed" if jarque_bera_p_value >= 0.05 else "warning"
    if residual_normality["status"] != expected_status:
        raise ValueError("diagnostics.residual_normality.status is inconsistent")

    data_quality = _exact_keys(
        data["data_quality"],
        _DATA_QUALITY_KEYS,
        "diagnostics.data_quality",
    )
    missing_rate = _number(
        data_quality["missing_rate"],
        "diagnostics.data_quality.missing_rate",
    )
    outlier_count = data_quality["outlier_count"]
    if not 0 <= missing_rate <= 1:
        raise ValueError("diagnostics.data_quality.missing_rate must be between 0 and 1")
    if isinstance(outlier_count, bool) or not isinstance(outlier_count, int) or outlier_count < 0:
        raise ValueError("diagnostics.data_quality.outlier_count must be a non-negative integer")

    warnings = data["warnings"]
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in warnings
    ):
        raise ValueError("diagnostics.warnings must be a list of non-empty strings")


@dataclass(frozen=True)
class RegressionIdentity:
    artifact_id: str
    market: str
    source_market_date: str
    applicable_trading_date: str
    generated_at: str
    source_manifest: str
    source_manifest_sha256: str
    input_dataset_object: str
    input_dataset_sha256: str
    input_dataset_content_sha256: str
    input_dataset_rows_sha256: str
    code_commit_sha: str
    generator_version: str
    content_sha256: str
    regression_spec_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionIdentity":
        _exact_keys(data, _IDENTITY_KEYS, "identity")
        return cls(**data)


@dataclass(frozen=True)
class RegressionSpec:
    analysis_scope: str
    entity_type: str
    universe_definition: str
    observation_unit: str
    model_family: str
    dependent_variable: str
    dependent_variable_definition: str
    independent_variables: list[str]
    intercept: bool
    frequency: str
    first_feature_session: str
    last_feature_session: str
    first_label_end_session: str
    last_label_end_session: str
    label_horizon_sessions: int
    sample_count: int
    missing_value_policy: str
    standardization_policy: str
    outlier_policy: str
    covariance_estimator: str
    hac_max_lags: int
    confidence_level: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionSpec":
        _exact_keys(data, _SPEC_KEYS, "regression_spec")
        return cls(**data)


@dataclass(frozen=True)
class RegressionResultItem:
    factor_name: str
    display_label: str
    coefficient: float
    standard_error: float
    t_statistic: float
    p_value: float
    confidence_interval_low: float
    confidence_interval_high: float
    direction: str
    economic_magnitude: str
    display_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionResultItem":
        _exact_keys(data, _RESULT_KEYS, "result")
        return cls(**data)


@dataclass(frozen=True)
class RegressionFitStatistics:
    r_squared: float
    adjusted_r_squared: float
    residual_standard_error: float
    degrees_of_freedom: int
    f_statistic: float
    f_p_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionFitStatistics":
        _exact_keys(data, _FIT_KEYS, "fit_statistics")
        return cls(**data)


@dataclass(frozen=True)
class RegressionDiagnostics:
    multicollinearity: dict[str, Any]
    heteroskedasticity: dict[str, Any]
    autocorrelation: dict[str, Any]
    residual_normality: dict[str, Any]
    data_quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionDiagnostics":
        _exact_keys(data, _DIAGNOSTIC_KEYS, "diagnostics")
        return cls(**data)


@dataclass(frozen=True)
class RegressionPresentation:
    headline: str
    summary: str
    key_exposures: list[str]
    limitations: str
    disclosure: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionPresentation":
        _exact_keys(data, _PRESENTATION_KEYS, "presentation")
        return cls(**data)


@dataclass(frozen=True)
class RegressionResearchArtifact:
    schema_version: int
    kind: str
    identity: RegressionIdentity
    regression_spec: RegressionSpec
    results: list[RegressionResultItem]
    fit_statistics: RegressionFitStatistics
    diagnostics: RegressionDiagnostics
    presentation: RegressionPresentation

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "identity": self.identity.to_dict(),
            "regression_spec": self.regression_spec.to_dict(),
            "results": [item.to_dict() for item in self.results],
            "fit_statistics": self.fit_statistics.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "presentation": self.presentation.to_dict(),
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "RegressionResearchArtifact":
        top = _exact_keys(document, _TOP_LEVEL_KEYS, "artifact top-level")
        if top["schema_version"] != REGRESSION_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("Invalid schema_version")
        if top["kind"] != REGRESSION_ARTIFACT_KIND:
            raise ValueError("Invalid kind")

        identity_data = _exact_keys(top["identity"], _IDENTITY_KEYS, "identity")
        if identity_data["market"] != "TW":
            raise ValueError("identity.market must be TW")
        if not isinstance(identity_data["artifact_id"], str) or not identity_data["artifact_id"]:
            raise ValueError("artifact_id must be non-empty")
        source_date = _date(identity_data["source_market_date"], "source_market_date")
        applicable_date = _date(identity_data["applicable_trading_date"], "applicable_trading_date")
        if applicable_date <= source_date:
            raise ValueError("applicable_trading_date must be after source_market_date")
        _timestamp(identity_data["generated_at"], "generated_at")
        if not isinstance(identity_data["source_manifest"], str) or AGGREGATE_MANIFEST_PATH_RE.fullmatch(identity_data["source_manifest"]) is None:
            raise ValueError("source_manifest path is invalid")
        for field_name in (
            "source_manifest_sha256",
            "input_dataset_sha256",
            "input_dataset_content_sha256",
            "input_dataset_rows_sha256",
            "content_sha256",
        ):
            _sha(identity_data[field_name], HEX_64_RE, field_name)
        _sha(identity_data["code_commit_sha"], HEX_40_RE, "code_commit_sha")
        path_match = INPUT_DATASET_OBJECT_RE.fullmatch(str(identity_data["input_dataset_object"]))
        if path_match is None or path_match.group(1) != identity_data["input_dataset_sha256"]:
            raise ValueError("input_dataset_object path must bind input_dataset_sha256")
        if identity_data["regression_spec_version"] != "1.0":
            raise ValueError("regression_spec_version must be 1.0")
        if not isinstance(identity_data["generator_version"], str) or not identity_data["generator_version"]:
            raise ValueError("generator_version must be non-empty")

        spec_data = _exact_keys(top["regression_spec"], _SPEC_KEYS, "regression_spec")
        for key, expected in _SPEC_FIXED.items():
            if spec_data[key] != expected:
                raise ValueError(f"regression_spec.{key} must be {expected!r}")
        if spec_data["independent_variables"] != list(V1_FACTORS):
            raise ValueError("independent_variables must be the three unique v1 factors")
        if not isinstance(spec_data["dependent_variable_definition"], str) or not spec_data["dependent_variable_definition"]:
            raise ValueError("dependent_variable_definition must be non-empty")
        sample_count = spec_data["sample_count"]
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 30 <= sample_count <= 252:
            raise ValueError("sample_count must be between 30 and 252")
        spec_dates = {
            field_name: _date(spec_data[field_name], field_name)
            for field_name in (
                "first_feature_session",
                "last_feature_session",
                "first_label_end_session",
                "last_label_end_session",
            )
        }
        if spec_dates["first_feature_session"] > spec_dates["last_feature_session"]:
            raise ValueError("feature session boundaries are reversed")
        if spec_dates["first_label_end_session"] > spec_dates["last_label_end_session"]:
            raise ValueError("label session boundaries are reversed")
        if spec_dates["last_label_end_session"] > source_date:
            raise ValueError("last_label_end_session must not exceed source_market_date")

        results_data = top["results"]
        if not isinstance(results_data, list):
            raise ValueError("results must be a list")
        results: list[RegressionResultItem] = []
        factor_names = []
        for item in results_data:
            data = _exact_keys(item, _RESULT_KEYS, "result")
            factor_names.append(data["factor_name"])
            coefficient = _number(data["coefficient"], "coefficient")
            standard_error = _number(data["standard_error"], "standard_error")
            t_statistic = _number(data["t_statistic"], "t_statistic")
            p_value = _number(data["p_value"], "p_value")
            ci_low = _number(data["confidence_interval_low"], "confidence_interval_low")
            ci_high = _number(data["confidence_interval_high"], "confidence_interval_high")
            if standard_error < 0:
                raise ValueError("standard_error must be >= 0")
            if not 0 <= p_value <= 1:
                raise ValueError("p_value must be between 0 and 1")
            if not ci_low <= coefficient <= ci_high:
                raise ValueError("confidence interval must contain coefficient")
            expected_direction = "positive" if coefficient > 0 else "negative" if coefficient < 0 else "neutral"
            if data["direction"] != expected_direction:
                raise ValueError("direction must match coefficient sign")
            expected_status = "statistically_significant" if p_value < 0.05 else "statistically_insignificant"
            if data["display_status"] != expected_status:
                raise ValueError("display_status must match p_value")
            if data["economic_magnitude"] not in {"weak", "moderate", "strong"}:
                raise ValueError("economic_magnitude is invalid")
            if not isinstance(data["display_label"], str) or not data["display_label"]:
                raise ValueError("display_label must be non-empty")
            results.append(
                RegressionResultItem(
                    factor_name=data["factor_name"],
                    display_label=data["display_label"],
                    coefficient=coefficient,
                    standard_error=standard_error,
                    t_statistic=t_statistic,
                    p_value=p_value,
                    confidence_interval_low=ci_low,
                    confidence_interval_high=ci_high,
                    direction=data["direction"],
                    economic_magnitude=data["economic_magnitude"],
                    display_status=data["display_status"],
                )
            )
        if factor_names != list(V1_FACTORS):
            raise ValueError("results factors must match independent_variables exactly once")

        fit_data = _exact_keys(top["fit_statistics"], _FIT_KEYS, "fit_statistics")
        r_squared = _number(fit_data["r_squared"], "r_squared")
        adjusted_r_squared = _number(fit_data["adjusted_r_squared"], "adjusted_r_squared")
        residual_standard_error = _number(fit_data["residual_standard_error"], "residual_standard_error")
        f_statistic = _number(fit_data["f_statistic"], "f_statistic")
        f_p_value = _number(fit_data["f_p_value"], "f_p_value")
        degrees_of_freedom = fit_data["degrees_of_freedom"]
        if not 0 <= r_squared <= 1:
            raise ValueError("r_squared must be between 0 and 1")
        if adjusted_r_squared > 1:
            raise ValueError("adjusted_r_squared must be <= 1")
        if residual_standard_error < 0:
            raise ValueError("residual_standard_error must be >= 0")
        if isinstance(degrees_of_freedom, bool) or not isinstance(degrees_of_freedom, int) or degrees_of_freedom <= 0:
            raise ValueError("degrees_of_freedom must be a positive integer")
        if not 0 <= f_p_value <= 1:
            raise ValueError("f_p_value must be between 0 and 1")
        fit_statistics = RegressionFitStatistics(
            r_squared=r_squared,
            adjusted_r_squared=adjusted_r_squared,
            residual_standard_error=residual_standard_error,
            degrees_of_freedom=degrees_of_freedom,
            f_statistic=f_statistic,
            f_p_value=f_p_value,
        )

        diagnostics_data = _exact_keys(top["diagnostics"], _DIAGNOSTIC_KEYS, "diagnostics")
        _validate_finite_tree(diagnostics_data, "diagnostics")
        _validate_diagnostics(diagnostics_data)
        presentation_data = _exact_keys(top["presentation"], _PRESENTATION_KEYS, "presentation")
        if presentation_data["disclosure"] != MANDATORY_DISCLOSURE:
            raise ValueError("presentation.disclosure must match mandatory disclosure")
        if not isinstance(presentation_data["key_exposures"], list) or not all(isinstance(item, str) for item in presentation_data["key_exposures"]):
            raise ValueError("presentation.key_exposures must be a list of strings")

        visible = {
            "results": results_data,
            "warnings": diagnostics_data["warnings"],
            "presentation": presentation_data,
        }
        for text in _visible_strings(visible):
            for forbidden in FORBIDDEN_WORDS:
                if forbidden.lower() in text.lower():
                    if (
                        text == MANDATORY_DISCLOSURE
                        and forbidden == "正式預測"
                    ):
                        continue
                    raise ValueError(f"Forbidden word found in user-visible text: {forbidden}")

        if compute_regression_artifact_content_sha256(document) != identity_data["content_sha256"]:
            raise ValueError("content_sha256 mismatch")

        return cls(
            schema_version=REGRESSION_ARTIFACT_SCHEMA_VERSION,
            kind=REGRESSION_ARTIFACT_KIND,
            identity=RegressionIdentity.from_dict(identity_data),
            regression_spec=RegressionSpec.from_dict(spec_data),
            results=results,
            fit_statistics=fit_statistics,
            diagnostics=RegressionDiagnostics.from_dict(diagnostics_data),
            presentation=RegressionPresentation.from_dict(presentation_data),
        )


def serialize_regression_artifact(document: dict[str, Any]) -> bytes:
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if not serialized or len(serialized) > MAX_REGRESSION_ARTIFACT_BYTES:
        raise ValueError("Serialized regression artifact size is outside allowed range")
    return serialized


def compute_regression_artifact_content_sha256(document: dict[str, Any]) -> str:
    doc_copy = json.loads(json.dumps(document, allow_nan=False))
    doc_copy["identity"]["content_sha256"] = ""
    return hashlib.sha256(serialize_regression_artifact(doc_copy)).hexdigest()
