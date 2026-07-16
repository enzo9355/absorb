"""Build and persist local daily dashboard/report candidates without cutover."""

import datetime
import hashlib
import json
import math
import os
import re
from pathlib import Path

from stock_papi.services.model_evidence import (
    presentation_policy,
    sanitize_public_report,
)


MAX_DASHBOARD_BYTES = 5_000_000


def _canonical(document):
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_immutable(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("immutable daily candidate conflict")
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _validate_dashboard(document):
    if not isinstance(document, dict):
        raise ValueError("dashboard snapshot must be an object")
    try:
        inference = datetime.date.fromisoformat(document["inference_as_of"])
        generated = datetime.datetime.fromisoformat(
            document["generated_at"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("dashboard dates are invalid") from exc
    baseline_status = document.get("baseline_status")
    backtest_as_of = document.get("backtest_as_of")
    if backtest_as_of is not None:
        backtest_as_of = datetime.date.fromisoformat(str(backtest_as_of))
    if (
        document.get("schema_version") != 1
        or document.get("kind") != "absorb-daily-dashboard"
        or document.get("market") != "TW"
        or generated.tzinfo is None
        or inference > generated.astimezone(datetime.timezone.utc).date()
        or baseline_status not in {"validated_compatible", "initial_backtest_bootstrap"}
        or (baseline_status == "validated_compatible" and backtest_as_of is None)
        or (backtest_as_of is not None and backtest_as_of > inference)
        or not isinstance(document.get("model_version"), str)
        or type(document.get("feature_schema_version")) is not int
        or not isinstance(document.get("recommendation_policy_version"), str)
        or re.fullmatch(
            r"quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json",
            str(document.get("source_manifest") or ""),
        )
        is None
        or re.fullmatch(r"[0-9a-f]{64}", str(document.get("source_manifest_sha256") or ""))
        is None
        or not isinstance(document.get("sector_snapshot"), dict)
        or not isinstance(document["sector_snapshot"].get("sectors"), dict)
        or not isinstance(document.get("heatmap"), list)
        or not isinstance(document.get("daily_focus"), list)
        or not isinstance(document.get("top_picks"), list)
        or not isinstance(document.get("gates"), dict)
        or not isinstance(document.get("presentation"), dict)
        or type(document["presentation"].get("strong_action_allowed")) is not bool
        or type(document["presentation"].get("performance_endorsement_allowed")) is not bool
    ):
        raise ValueError("dashboard snapshot schema is invalid")
    content = _canonical(document)
    if len(content) > MAX_DASHBOARD_BYTES:
        raise ValueError("dashboard snapshot is too large")
    return document


def build_daily_products(report, metadata, baseline):
    source_date = report.source.manifest.market_as_of.isoformat()
    generated_at = metadata["published_at"]
    backtests = {item.industry: item for item in report.backtests}
    stocks = {stock.symbol: stock for stock in report.source.stocks}
    presentation = presentation_policy(baseline["status"])
    sectors = {}
    all_items = []
    for industry in report.industries:
        items = []
        for symbol in industry.symbols:
            stock = stocks.get(symbol)
            if stock is None:
                continue
            latest = stock.latest
            probability = _number(latest.get("AI_P"))
            close = _number(latest.get("Close"))
            ma20 = _number(latest.get("MA20"))
            if probability is None:
                continue
            item = {
                "code": stock.symbol,
                "name": stock.name,
                "price": close,
                "prob": round(probability, 1),
                "trend": (
                    "站上 MA20"
                    if close is not None and ma20 is not None and close >= ma20
                    else "跌破 MA20"
                    if close is not None and ma20 is not None
                    else "中性"
                ),
                "score": round(probability, 2),
                "direction_score": round(probability, 1),
                "as_of": source_date,
                "sample_count": backtests[industry.name].valid_signals,
                "coverage": industry.coverage,
                "rotation": industry.rotation,
                "near_rotation_boundary": industry.near_boundary,
                "data_quality_warning": baseline["status"] != "validated_compatible",
                "model_output_label": presentation["model_output_label"],
                "calibration_notice": presentation["calibration_notice"],
                "strong_action_allowed": presentation["strong_action_allowed"],
            }
            items.append(item)
            all_items.append((industry.name, item))
        sectors[industry.name] = sorted(
            items, key=lambda value: (-value["score"], value["code"])
        )[:10]

    heatmap = []
    for industry in report.industries:
        items = sectors.get(industry.name) or []
        if not items or industry.average_probability is None:
            continue
        probability = round(float(industry.average_probability), 1)
        heatmap.append(
            {
                "name": industry.name,
                "probability": probability,
                "direction_score": probability,
                "count": industry.component_count,
                "tone": "hot" if probability >= 60 else "cold" if probability < 45 else "steady",
                "code": items[0]["code"],
            }
        )
    heatmap.sort(key=lambda item: (-item["probability"], item["name"]))

    picks = []
    seen = set()
    for industry_name, item in sorted(
        all_items, key=lambda value: (-value[1]["score"], value[1]["code"])
    ):
        if item["code"] in seen:
            continue
        seen.add(item["code"])
        picks.append({**item, "primary_industry": industry_name})
        if len(picks) == 3:
            break

    sector_snapshot = {
        "schema_version": 1,
        "as_of": source_date,
        "generated_at": generated_at,
        "sectors": sectors,
    }
    dashboard = {
        "schema_version": 1,
        "kind": "absorb-daily-dashboard",
        "market": "TW",
        "inference_as_of": source_date,
        "backtest_as_of": baseline.get("backtest_as_of"),
        "model_version": baseline["model_version"],
        "feature_schema_version": baseline["feature_schema_version"],
        "recommendation_policy_version": baseline["recommendation_policy_version"],
        "backtest_version": baseline.get("backtest_version"),
        "baseline_status": baseline["status"],
        "baseline_mismatch_fields": list(baseline.get("mismatch_fields") or []),
        "source_manifest": metadata["source_manifest"],
        "source_manifest_sha256": metadata["source_manifest_sha256"],
        "generated_at": generated_at,
        "sector_snapshot": sector_snapshot,
        "heatmap": heatmap,
        "daily_focus": list(metadata["summary"][:2]),
        "top_picks": picks,
        "gates": {
            "source_identity": "PASS",
            "source_date": "PASS",
            "finite_json": "PASS",
            "baseline": (
                "PASS" if baseline["status"] == "validated_compatible" else "DEGRADED"
            ),
            "production_cutover": "NOT_RUN",
        },
        "presentation": presentation,
    }
    return _validate_dashboard(dashboard)


def write_daily_candidate(root, report_metadata, dashboard):
    from reporting.schemas import ReportMetadataV2

    report_metadata = dict(report_metadata)
    content = dict(report_metadata.get("content") or {})
    content["public_report"] = sanitize_public_report(
        content.get("public_report"),
        dashboard["baseline_status"],
    )
    content["presentation"] = dict(dashboard["presentation"])
    report_metadata["content"] = content
    if dashboard["baseline_status"] == "initial_backtest_bootstrap":
        report_metadata["summary"] = [
            (
                str(item)
                .replace("五日上漲機率", "模型方向分數")
                .replace("機率變化", "方向分數變化")
                .replace("模型偏多產業", "模型分數較高產業")
                .replace("模型偏弱產業", "模型分數較低產業")
                .replace("%", "")
                if "機率" in str(item) or "模型偏" in str(item)
                else str(item)
            )
            for item in report_metadata.get("summary") or []
        ]
        warnings = list(report_metadata.get("warnings") or [])
        notice = "尚未完成機率校準驗證；本報告只顯示模型方向分數，不含績效背書。"
        if notice not in warnings:
            warnings.append(notice)
        report_metadata["warnings"] = warnings
    report_document = ReportMetadataV2.from_document(report_metadata).to_document()
    dashboard = _validate_dashboard(dashboard)
    identity = _canonical({"report": report_document, "dashboard": dashboard})
    candidate_id = hashlib.sha256(identity).hexdigest()[:16]
    directory = (
        Path(root)
        / "outputs"
        / "post_close_report"
        / "candidates"
        / f"{dashboard['inference_as_of']}-{candidate_id}"
    )
    documents = {
        "post-close-report-v2.json": report_document,
        "dashboard-snapshot.json": dashboard,
        "sector-snapshot.json": dashboard["sector_snapshot"],
        "heatmap.json": dashboard["heatmap"],
        "daily-focus.json": dashboard["daily_focus"],
        "top-picks.json": dashboard["top_picks"],
    }
    files = {}
    for name, document in documents.items():
        content = _canonical(document)
        _write_immutable(directory / name, content)
        files[name] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    manifest = {
        "schema_version": 1,
        "kind": "absorb-daily-candidate",
        "inference_as_of": dashboard["inference_as_of"],
        "baseline_status": dashboard["baseline_status"],
        "files": files,
    }
    _write_immutable(directory / "candidate.json", _canonical(manifest))
    return directory


def _read_candidate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "candidate.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "absorb-daily-candidate":
        raise ValueError("daily candidate manifest is invalid")
    documents = {}
    for name, expected in manifest["files"].items():
        path = directory / name
        content = path.read_bytes()
        if len(content) != expected["size"] or hashlib.sha256(content).hexdigest() != expected["sha256"]:
            raise ValueError("daily candidate hash mismatch")
        documents[name] = json.loads(content)
    _validate_dashboard(documents["dashboard-snapshot.json"])
    return documents


def publish_dashboard_snapshot(root, document):
    document = _validate_dashboard(document)
    content = _canonical(document)
    digest = hashlib.sha256(content).hexdigest()
    publish = Path(root) / "publish" / "dashboard" / "v1"
    _write_immutable(publish / "objects" / f"{digest}.json", content)
    latest = {
        "schema_version": 1,
        "kind": "absorb-daily-dashboard",
        "market": "TW",
        "inference_as_of": document["inference_as_of"],
        "backtest_as_of": document["backtest_as_of"],
        "path": f"objects/{digest}.json",
        "sha256": digest,
        "size": len(content),
    }
    _write_atomic(publish / "latest-TW.json", _canonical(latest))
    return publish / "latest-TW.json"


def promote_daily_candidate(root, directory):
    from reporting.publisher import publish_report_v2

    documents = _read_candidate(directory)
    report_latest = publish_report_v2(
        Path(root), documents["post-close-report-v2.json"]
    )
    dashboard_latest = publish_dashboard_snapshot(
        root, documents["dashboard-snapshot.json"]
    )
    return {"report_latest": str(report_latest), "dashboard_latest": str(dashboard_latest)}
