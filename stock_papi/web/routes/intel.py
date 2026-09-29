"""Bounded, no-store Information API routes."""

import re
from urllib.parse import urlsplit

from flask import jsonify, request, url_for


_INSTRUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVENT_FIELDS = (
    "event_id", "event_version_id", "event_date", "event_at",
    "first_public_time_upper_bound", "transaction_classification",
    "transaction_code", "acquired_disposed", "security_title", "shares",
    "price_per_share", "price_status", "price_currency", "direct_indirect",
    "ownership_nature", "source_document_id",
)
_SUMMARY_SLOTS = ("purchase_activity", "sale_activity", "purchase_cluster", "price_context")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def sanitize_public_event(row):
    if not isinstance(row, dict):
        return {}
    result = {
        key: row[key]
        for key in _EVENT_FIELDS
        if key in row and isinstance(row[key], str) and len(row[key]) <= 512
    }
    for key in ("shares", "price_per_share"):
        value = row.get(key)
        if isinstance(value, str) and len(value) <= 64 and _DECIMAL.fullmatch(value):
            result[key] = value
    source_url = row.get("source_url")
    try:
        parsed = urlsplit(source_url)
        if (
            isinstance(source_url, str)
            and len(source_url) <= 2048
            and parsed.scheme == "https"
            and parsed.hostname in {"sec.gov", "www.sec.gov"}
            and parsed.path.startswith("/Archives/edgar/data/")
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and not parsed.query
            and not parsed.fragment
        ):
            result["source_url"] = source_url
    except (TypeError, ValueError):
        pass
    return result


def sanitize_public_summary(summary, instrument_id, decision_cutoff_at=None):
    if (
        not isinstance(summary, dict)
        or type(summary.get("schema_version")) is not int
        or summary["schema_version"] != 1
        or summary.get("instrument_id") != instrument_id
        or (
            decision_cutoff_at is not None
            and summary.get("decision_cutoff_at") != decision_cutoff_at
        )
        or not isinstance(summary.get("decision_cutoff_at"), str)
        or len(summary["decision_cutoff_at"]) > 64
        or any(
            not isinstance(summary.get(key), str)
            or not summary[key].strip()
            or len(summary[key]) > 128
            for key in ("rule_version", "template_version")
        )
        or not isinstance(summary.get("disclaimer"), str)
        or len(summary["disclaimer"]) > 512
        or not isinstance(summary.get("summary_id"), str)
        or _HASH.fullmatch(summary["summary_id"]) is None
        or not isinstance(summary.get("slots"), dict)
    ):
        return None
    slots = {}
    for name in _SUMMARY_SLOTS:
        slot = summary["slots"].get(name)
        if slot is None:
            continue
        if not isinstance(slot, dict) or not isinstance(slot.get("text"), str) or len(slot["text"]) > 2000:
            return None
        fact_id = slot.get("fact_id")
        if fact_id is not None and (
            not isinstance(fact_id, str) or _HASH.fullmatch(fact_id) is None
        ):
            return None
        slots[name] = {"fact_id": fact_id, "text": slot["text"]}
    if not slots:
        return None
    return {
        "schema_version": 1,
        "decision_cutoff_at": summary["decision_cutoff_at"],
        "rule_version": summary["rule_version"],
        "template_version": summary["template_version"],
        "summary_id": summary["summary_id"],
        "disclaimer": summary["disclaimer"],
        "slots": slots,
    }


def register_intel_routes(app, *, load_snapshot=None, enabled=False):
    def response_for(snapshot, instrument_id, *, include_events=False):
        status = snapshot.get("status") if isinstance(snapshot, dict) else "unavailable"
        reasons = snapshot.get("reason_codes") if isinstance(snapshot, dict) else None
        if not isinstance(reasons, list) or any(not isinstance(value, str) for value in reasons):
            reasons = ["schema_error"]
            status = "unavailable"
        if status not in {"available", "partial", "stale", "unavailable"}:
            status = "unavailable"
            reasons = ["schema_error"]
        http_status = 200
        if status == "unavailable":
            http_status = 410 if set(reasons) & {"artifact_revoked", "source_delay"} else (
                200 if "not_covered" in reasons else 503
            )
        result = {
            "schema_version": "intel-api-v1",
            "instrument_id": instrument_id,
            "status": status,
            "reason_codes": reasons,
        }
        release = snapshot.get("release") if isinstance(snapshot, dict) else None
        if isinstance(release, dict):
            result["release"] = {
                key: release[key]
                for key in ("release_id", "generated_at", "decision_cutoff_at", "valid_until", "manifest_hash")
                if key in release
            }
        if include_events:
            if status == "unavailable":
                result["events"] = []
                result["event_page"] = {"page": 1, "page_count": 0}
            else:
                rows = snapshot.get("events") if isinstance(snapshot, dict) else None
                event_page = snapshot.get("event_page") if isinstance(snapshot, dict) else None
                page = event_page.get("page") if isinstance(event_page, dict) else None
                page_count = event_page.get("page_count") if isinstance(event_page, dict) else None
                if (
                    not isinstance(rows, list)
                    or len(rows) > 50
                    or any(not isinstance(row, dict) for row in rows)
                    or type(page) is not int
                    or type(page_count) is not int
                    or not 1 <= page <= page_count
                ):
                    result.update(status="unavailable", reason_codes=["schema_error"])
                    http_status = 503
                    rows, page, page_count = [], 1, 0
                result["events"] = [sanitize_public_event(row) for row in rows]
                result["event_page"] = {"page": page, "page_count": page_count}
        else:
            summary = snapshot.get("summary") if isinstance(snapshot, dict) else None
            expected_cutoff = release.get("decision_cutoff_at") if isinstance(release, dict) else None
            safe_summary = (
                sanitize_public_summary(summary, instrument_id, expected_cutoff)
                if status != "unavailable" else None
            )
            if status != "unavailable" and safe_summary is None:
                result.update(status="unavailable", reason_codes=["schema_error"])
                http_status = 503
            result["summary"] = safe_summary
            result["fact_ids"] = sorted({
                slot["fact_id"]
                for slot in (safe_summary or {}).get("slots", {}).values()
                if slot.get("fact_id") is not None
            })
            release_id = release.get("release_id") if isinstance(release, dict) else None
            result["event_page"] = {
                "first_page_url": url_for(
                    "intel_stock_events", instrument_id=instrument_id,
                    release_id=release_id or "unavailable", page=1,
                )
            }
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response, http_status

    def load(instrument_id, release_id=None, page=1):
        if enabled is not True or not callable(load_snapshot):
            return {"status": "unavailable", "reason_codes": ["feature_disabled"]}
        try:
            value = load_snapshot(instrument_id, release_id=release_id, page=page)
        except Exception:
            return {"status": "unavailable", "reason_codes": ["source_unavailable"]}
        return value if isinstance(value, dict) else {
            "status": "unavailable", "reason_codes": ["source_unavailable"]
        }

    def summary(instrument_id):
        if not isinstance(instrument_id, str) or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
            return jsonify({"status": "unavailable", "reason_codes": ["not_covered"]}), 404
        release_id = request.args.get("release_id")
        if release_id is not None and _RELEASE_ID.fullmatch(release_id) is None:
            return jsonify({"status": "unavailable", "reason_codes": ["schema_error"]}), 400
        result, code = response_for(load(instrument_id, release_id), instrument_id)
        return result, code

    def events(instrument_id):
        if not isinstance(instrument_id, str) or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
            return jsonify({"status": "unavailable", "reason_codes": ["not_covered"]}), 404
        release_id = request.args.get("release_id")
        page_text = request.args.get("page", "1")
        if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
            return jsonify({"status": "unavailable", "reason_codes": ["schema_error"]}), 400
        if not isinstance(page_text, str) or re.fullmatch(r"[1-9][0-9]{0,3}", page_text) is None:
            return jsonify({"status": "unavailable", "reason_codes": ["schema_error"]}), 400
        result, code = response_for(
            load(instrument_id, release_id, int(page_text)), instrument_id, include_events=True
        )
        return result, code

    app.add_url_rule(
        "/api/intel/stock/<instrument_id>/summary", "intel_stock_summary", summary,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/intel/stock/<instrument_id>/events", "intel_stock_events", events,
        methods=["GET"],
    )
