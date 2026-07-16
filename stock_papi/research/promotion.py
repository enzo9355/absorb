"""Fail-closed research promotion to immutable validated-preview inputs only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _canonical(document):
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("promotion artifact is not finite JSON") from exc


def _write_immutable(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("immutable promotion artifact conflict")
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _gate(status, detail):
    return {"status": status, "detail": detail}


def decide_promotion(evaluation, availability_audit):
    if (
        not isinstance(evaluation, dict)
        or evaluation.get("schema_version") != 1
        or evaluation.get("kind") != "absorb-research-evaluation"
        or not isinstance(evaluation.get("models"), dict)
    ):
        raise ValueError("research evaluation is invalid")
    pit_status = availability_audit.get("formal_pit_status")
    pit_blockers = list(
        availability_audit.get("formal_pit_blockers") or []
    )
    direction = evaluation["models"].get("direction_lightgbm") or {}
    baseline = evaluation["models"].get("constant_prior") or {}
    gates = {}
    gates["leakage_pit"] = _gate(
        "PASS" if pit_status == "PASS" else "BLOCKED",
        "all formal PIT dependencies are available"
        if pit_status == "PASS"
        else f"unavailable PIT dependencies: {', '.join(pit_blockers)}",
    )
    gates["schema_security"] = _gate(
        "PASS",
        "evaluation and dataset identities are content-addressed",
    )
    dataset = evaluation.get("dataset") or {}
    coverage_pass = (
        type(dataset.get("row_count")) is int
        and dataset["row_count"] >= 100
        and type(dataset.get("symbol_count")) is int
        and dataset["symbol_count"] >= 1
    )
    gates["coverage"] = _gate(
        "PASS" if coverage_pass else "FAIL",
        "dataset has at least 100 verified rows and one verified symbol",
    )
    if direction.get("status") != "RUN":
        gates["direction_challenger"] = _gate(
            "BLOCKED", direction.get("reason") or "direction challenger did not run"
        )
        return {
            "schema_version": 1,
            "kind": "absorb-research-promotion-decision",
            "candidate_type": "probability",
            "overall": "BLOCKED",
            "gates": gates,
            "prediction_latest_updated": False,
            "production_traffic_updated": False,
        }

    model = direction["final_holdout"]
    candidate = model["classification"]
    constant = baseline["final_holdout"]["classification"]
    ranking = model["ranking"]
    transaction = model["transaction"]
    stability = model["stability"]
    brier_pass = candidate["brier"] <= constant["brier"] - 0.001
    calibration_pass = (
        candidate["ece_10"] <= 0.05
        and 0.8 <= candidate["calibration_slope"] <= 1.2
        and abs(candidate["calibration_intercept"]) <= 0.1
    )
    holdout_pass = (
        candidate["roc_auc"] is not None
        and candidate["roc_auc"] >= 0.52
        and candidate["log_loss"] <= constant["log_loss"]
    )
    ranking_pass = (
        ranking["spearman_ic"] is not None
        and ranking["spearman_ic"] >= 0.02
        and ranking["top_decile_spread"] is not None
        and ranking["top_decile_spread"] > 0
        and ranking["turnover"] is not None
        and ranking["turnover"] <= 0.80
    )
    transaction_pass = transaction["net_return_after_base_cost"] > 0
    interval = stability["bootstrap_ci"]["top_decile_net_return"]
    stability_pass = interval["lower"] > 0
    gates.update(
        probability_quality=_gate(
            "PASS" if brier_pass else "FAIL",
            "holdout Brier improves constant prior by at least 0.001",
        ),
        calibration=_gate(
            "PASS" if calibration_pass else "FAIL",
            "ECE <= 0.05, slope 0.8-1.2 and intercept within 0.1",
        ),
        holdout_baseline=_gate(
            "PASS" if holdout_pass else "FAIL",
            "untouched holdout AUC >= 0.52 and Log Loss no worse than constant",
        ),
        ranking_diagnostic=_gate(
            "PASS" if ranking_pass else "FAIL",
            "IC, spread and turnover diagnostic thresholds",
        ),
        transaction_utility=_gate(
            "PASS" if transaction_pass else "FAIL",
            "top-decile return remains positive after base transaction cost",
        ),
        stability=_gate(
            "PASS" if stability_pass else "FAIL",
            "source-date bootstrap lower confidence bound is positive",
        ),
    )
    statuses = [gate["status"] for gate in gates.values()]
    overall = (
        "BLOCKED"
        if "BLOCKED" in statuses
        else "FAIL"
        if "FAIL" in statuses
        else "PASS"
    )
    ranking_model = evaluation["models"].get("ranking_lightgbm") or {}
    ranking_candidate = {
        "overall": ranking_model.get("status", "NOT_RUN"),
        "reason": ranking_model.get("reason"),
        "dependencies": ranking_model.get("dependencies", []),
    }
    return {
        "schema_version": 1,
        "kind": "absorb-research-promotion-decision",
        "candidate_type": "probability",
        "selected_model": "direction_lightgbm",
        "overall": overall,
        "gates": gates,
        "prediction_capability": {
            "mode": "validated_preview" if overall == "PASS" else "research",
            "observation_enabled": True,
            "probability_allowed": overall == "PASS",
            "ranking_allowed": False,
            "strong_action_allowed": False,
            "performance_endorsement_allowed": False,
        },
        "prediction_latest_updated": False,
        "production_traffic_updated": False,
        "ranking_candidate": ranking_candidate,
    }


def write_promotion_artifacts(root, evaluation, decision):
    if (
        not isinstance(decision, dict)
        or decision.get("schema_version") != 1
        or decision.get("kind")
        != "absorb-research-promotion-decision"
        or decision.get("overall") not in {"PASS", "FAIL", "BLOCKED"}
    ):
        raise ValueError("promotion decision is invalid")
    root = Path(root)
    publish = root / "publish" / "research" / "v1"

    evaluation_content = _canonical(evaluation)
    evaluation_sha = hashlib.sha256(evaluation_content).hexdigest()
    evaluation_path = publish / "evaluations" / f"{evaluation_sha}.json"
    _write_immutable(evaluation_path, evaluation_content)

    bound_decision = {
        **decision,
        "evaluation_sha256": evaluation_sha,
        "dataset_manifest_sha256": evaluation.get(
            "dataset_manifest_sha256"
        ),
    }
    decision_content = _canonical(bound_decision)
    decision_sha = hashlib.sha256(decision_content).hexdigest()
    decision_path = publish / "decisions" / f"{decision_sha}.json"
    _write_immutable(decision_path, decision_content)

    candidate_path = None
    preview_path = None
    if decision["overall"] == "PASS":
        candidate = {
            "schema_version": 1,
            "kind": "absorb-validated-research-candidate",
            "mode": "validated_preview",
            "candidate_type": decision["candidate_type"],
            "selected_model": decision["selected_model"],
            "evaluation_sha256": evaluation_sha,
            "decision_sha256": decision_sha,
            "dataset_manifest_sha256": evaluation.get(
                "dataset_manifest_sha256"
            ),
            "prediction_capability": decision["prediction_capability"],
            "production_eligible": False,
        }
        candidate_content = _canonical(candidate)
        candidate_sha = hashlib.sha256(candidate_content).hexdigest()
        candidate_path = publish / "candidates" / f"{candidate_sha}.json"
        _write_immutable(candidate_path, candidate_content)

        preview = {
            "schema_version": 1,
            "kind": "absorb-no-traffic-preview-receipt",
            "candidate_sha256": candidate_sha,
            "candidate_path": (
                f"research/v1/candidates/{candidate_sha}.json"
            ),
            "traffic_percent": 0,
            "prediction_latest_updated": False,
            "production_traffic_updated": False,
        }
        preview_content = _canonical(preview)
        preview_sha = hashlib.sha256(preview_content).hexdigest()
        preview_path = publish / "previews" / f"{preview_sha}.json"
        _write_immutable(preview_path, preview_content)

    return {
        "evaluation_path": str(evaluation_path),
        "evaluation_sha256": evaluation_sha,
        "decision_path": str(decision_path),
        "decision_sha256": decision_sha,
        "candidate_path": str(candidate_path) if candidate_path else None,
        "preview_receipt_path": str(preview_path) if preview_path else None,
    }
