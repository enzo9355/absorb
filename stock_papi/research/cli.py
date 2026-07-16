"""Execute independent challengers, strict evaluation and fail-closed promotion."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path

from .challengers import (
    load_dataset,
    run_baselines,
    run_direction_lightgbm,
    run_ranking_lightgbm,
)
from .evaluation import (
    build_split_plan,
    evaluate_prediction_result,
    evaluate_ranking_result,
)
from .promotion import decide_promotion, write_promotion_artifacts


def _git_sha():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("git HEAD is invalid")
    return value


def _load_audit(root, manifest):
    audit = manifest.get("availability_audit") or {}
    relative = str(audit.get("path") or "")
    expected_sha = str(audit.get("sha256") or "")
    if (
        not relative.startswith("research/v1/pit/audits/")
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None
    ):
        raise ValueError("dataset availability audit identity is invalid")
    publish = (Path(root) / "publish").resolve()
    path = (publish / relative).resolve()
    try:
        path.relative_to(publish)
    except ValueError as exc:
        raise ValueError("availability audit escaped publish root") from exc
    try:
        content = path.read_bytes()
        document = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("availability audit is unreadable") from exc
    if (
        hashlib.sha256(content).hexdigest() != expected_sha
        or document.get("kind") != "absorb-pit-availability-audit"
    ):
        raise ValueError("availability audit hash or schema mismatch")
    return document, expected_sha


def _libraries():
    result = {}
    for name in ("numpy", "pandas", "lightgbm"):
        try:
            module = __import__(name)
            result[name] = getattr(module, "__version__", "present")
        except ImportError:
            result[name] = "unavailable"
    return result


def run_research(
    root,
    manifest_path,
    *,
    git_sha,
    bootstrap_iterations=500,
):
    frame, manifest = load_dataset(manifest_path)
    audit, audit_sha = _load_audit(root, manifest)
    plan = build_split_plan(frame["source_market_date"].unique())

    raw_models = run_baselines(frame, plan)
    raw_models["direction_lightgbm"] = run_direction_lightgbm(frame, plan)
    raw_models["ranking_lightgbm"] = run_ranking_lightgbm(
        frame,
        plan,
        audit,
    )
    models = {}
    for name, result in raw_models.items():
        if name == "ranking_lightgbm":
            models[name] = evaluate_ranking_result(
                frame,
                result,
                bootstrap_iterations=bootstrap_iterations,
            )
        else:
            models[name] = evaluate_prediction_result(
                frame,
                result,
                bootstrap_iterations=bootstrap_iterations,
            )
    generated_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    evaluation = {
        "schema_version": 1,
        "kind": "absorb-research-evaluation",
        "market": manifest["market"],
        "generated_at": generated_at,
        "research_git_sha": git_sha,
        "dataset_manifest_path": str(Path(manifest_path)),
        "dataset_manifest_sha256": Path(manifest_path).stem,
        "availability_audit_sha256": audit_sha,
        "dataset": {
            "dataset_sha256": manifest["dataset_sha256"],
            "row_count": manifest["row_count"],
            "symbol_count": manifest["symbol_count"],
            "data_start": manifest["data_start"],
            "data_end": manifest["data_end"],
            "formal_pit_status": manifest["pit_policy"][
                "formal_pit_status"
            ],
            "formal_pit_blockers": manifest["pit_policy"][
                "formal_pit_blockers"
            ],
            "feature_schema_version": manifest[
                "feature_schema_version"
            ],
            "target_definition": manifest["target_definition"],
        },
        "split_plan": plan,
        "libraries": _libraries(),
        "models": models,
        "prediction_latest_updated": False,
        "production_traffic_updated": False,
    }
    decision = decide_promotion(evaluation, audit)
    artifacts = write_promotion_artifacts(root, evaluation, decision)
    return {
        "evaluation": evaluation,
        "decision": decision,
        "artifacts": artifacts,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="ABSORB strict PIT research")
    parser.add_argument(
        "--root", type=Path, default=Path(r"D:\AbsorbData")
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--git-sha")
    parser.add_argument("--bootstrap-iterations", type=int, default=500)
    args = parser.parse_args(argv)
    git_sha = args.git_sha or _git_sha()
    if re.fullmatch(r"[0-9a-f]{40}", git_sha) is None:
        raise ValueError("git_sha is invalid")
    result = run_research(
        args.root,
        args.manifest,
        git_sha=git_sha,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    models = result["evaluation"]["models"]
    summary = {
        "overall": result["decision"]["overall"],
        "formal_pit_status": result["evaluation"]["dataset"][
            "formal_pit_status"
        ],
        "model_statuses": {
            name: value["status"] for name, value in models.items()
        },
        "artifacts": result["artifacts"],
        "prediction_latest_updated": False,
        "production_traffic_updated": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
