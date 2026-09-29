"""Fail-closed Information release validation and pointer promotion."""

import datetime
import hashlib
import hmac
import json
import re

from stock_papi.intel.contracts import _parse_aware_timestamp
from stock_papi.intel.explanation import render_summary


MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_SUMMARY_BYTES = 128 * 1024
MAX_EVENTS_PAGE_BYTES = 256 * 1024
MAX_FACTS_BYTES = 5 * 1024 * 1024
MAX_GATE_BYTES = 128 * 1024
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OBJECT_REF = re.compile(r"^intel/v1/objects/([0-9a-f]{64})\.json$")
_MANIFEST_REF = re.compile(r"^intel/v1/manifests/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\.json$")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _now(value):
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    return _parse_aware_timestamp(value, "now")


def _read_object(load_object, path, max_bytes):
    if not callable(load_object):
        return None, "object_loader_missing"
    try:
        content = load_object(path, max_bytes)
    except Exception:
        return None, "object_unavailable"
    if not isinstance(content, bytes):
        return None, "object_unavailable"
    if len(content) > max_bytes:
        return None, "object_too_large"
    return content, None


def _read_ref(load_object, ref, max_bytes):
    if not isinstance(ref, dict):
        return None, None, "object_ref_invalid"
    path = ref.get("path")
    digest = ref.get("sha256")
    size = ref.get("size")
    match = _OBJECT_REF.fullmatch(path) if isinstance(path, str) else None
    if (
        match is None
        or match.group(1) != digest
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or type(size) is not int
        or not 0 < size <= max_bytes
    ):
        return None, None, "object_ref_invalid"
    content, error = _read_object(load_object, path, max_bytes)
    if error:
        return None, None, error
    if len(content) != size:
        return None, None, "object_size_mismatch"
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, digest):
        return None, None, "object_hash_mismatch"
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None, None, "object_schema_error"
    return content, document, None


def _rights_errors(policy, now, required_uses=("store_derived", "display_aggregate")):
    if not isinstance(policy, dict):
        return ["rights_policy_unknown"]
    text_fields = ("policy_id", "version", "reviewer", "retention_policy")
    if any(not isinstance(policy.get(key), str) or not policy[key].strip() for key in text_fields):
        return ["rights_policy_unknown"]
    evidence = policy.get("evidence_urls")
    if not isinstance(evidence, list) or not evidence or any(
        not isinstance(url, str) or not url.startswith("https://") for url in evidence
    ):
        return ["rights_policy_unknown"]
    try:
        reviewed = _parse_aware_timestamp(policy.get("reviewed_at"), "reviewed_at")
        effective = _parse_aware_timestamp(policy.get("effective_from"), "effective_from")
        expires = _parse_aware_timestamp(policy.get("expires_at"), "expires_at")
    except ValueError:
        return ["rights_policy_unknown"]
    if reviewed > now or effective > now or expires <= now:
        return ["rights_restricted"]
    for use in required_uses:
        if policy.get(use) == "denied":
            return ["rights_restricted"]
        if policy.get(use) != "allowed":
            return ["rights_policy_unknown"]
    return []


def _json_document(load_object, ref, max_bytes, expected_types=(dict,)):
    _, document, error = _read_ref(load_object, ref, max_bytes)
    if error:
        return None, error
    if not isinstance(document, expected_types):
        return None, "object_schema_error"
    return document, None


def _validate_instrument_objects(manifest, load_object, errors):
    instruments = manifest.get("instrument_objects")
    if not isinstance(instruments, dict) or not instruments:
        errors.append("instrument_objects_missing")
        return
    for instrument_id, refs in instruments.items():
        if (
            not isinstance(instrument_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", instrument_id) is None
            or not isinstance(refs, dict)
        ):
            errors.append("instrument_objects_invalid")
            continue
        summary, error = _json_document(load_object, refs.get("summary"), MAX_SUMMARY_BYTES)
        summary_payload = None
        if error:
            errors.append(error)
        elif (
            summary.get("schema_version") != "intel-api-v1"
            or summary.get("instrument_id") != instrument_id
            or summary.get("release_id") != manifest.get("release_id")
            or summary.get("status") not in {"available", "partial", "stale", "unavailable"}
            or not isinstance(summary.get("reason_codes"), list)
        ):
            errors.append("summary_schema_error")
        else:
            summary_payload = summary.get("summary")
            if not isinstance(summary_payload, dict):
                errors.append("summary_schema_error")

        pages = refs.get("events")
        if not isinstance(pages, list) or not pages:
            errors.append("event_pages_missing")
        else:
            for page_number, page_ref in enumerate(pages, 1):
                page, error = _json_document(load_object, page_ref, MAX_EVENTS_PAGE_BYTES)
                if error:
                    errors.append(error)
                    continue
                rows = page.get("events")
                if (
                    page.get("schema_version") != "intel-events-v1"
                    or page.get("instrument_id") != instrument_id
                    or page.get("release_id") != manifest.get("release_id")
                    or page.get("page") != page_number
                    or page.get("page_count") != len(pages)
                    or not isinstance(rows, list)
                    or len(rows) > 50
                    or any(not isinstance(row, dict) for row in rows)
                ):
                    errors.append("events_schema_error")

        if refs.get("facts") is not None:
            facts, error = _json_document(load_object, refs["facts"], MAX_FACTS_BYTES)
            if error:
                errors.append(error)
            elif (
                type(facts.get("schema_version")) is not int
                or facts.get("schema_version") != 1
                or facts.get("instrument_id") != instrument_id
                or not isinstance(facts.get("facts"), list)
            ):
                errors.append("facts_schema_error")
            else:
                fact_rows = facts["facts"]
                cutoff = manifest.get("decision_cutoff_at")
                if any(
                    not isinstance(row, dict)
                    or row.get("instrument_id") != instrument_id
                    or row.get("decision_cutoff_at") != cutoff
                    for row in fact_rows
                ):
                    errors.append("facts_schema_error")
                elif summary_payload is not None:
                    try:
                        expected = render_summary(
                            fact_rows,
                            summary_payload.get("rule_version"),
                            summary_payload.get("template_version"),
                        )
                    except (TypeError, ValueError):
                        expected = None
                    if expected != summary_payload:
                        errors.append("summary_fact_traceability_error")
        else:
            errors.append("facts_missing")


def validate_information_release(manifest, load_object, policy, *, now=None):
    """Validate current rights and every referenced immutable object before promotion."""
    errors = []
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest_schema_error"]}
    current = _now(now)
    release_id = manifest.get("release_id")
    if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
        errors.append("release_id_invalid")
    if manifest.get("schema_version") != 1 or manifest.get("mode") != "information":
        errors.append("manifest_schema_error")
    if manifest.get("market") != "US":
        errors.append("market_not_supported")
    if manifest.get("model_mode") not in (None, "information") or manifest.get("model_version") is not None:
        errors.append("shadow_model_not_allowed")
    if not isinstance(manifest.get("code_commit"), str) or not manifest["code_commit"].strip():
        errors.append("manifest_schema_error")
    try:
        generated = _parse_aware_timestamp(manifest.get("generated_at"), "generated_at")
        cutoff = _parse_aware_timestamp(manifest.get("decision_cutoff_at"), "decision_cutoff_at")
        valid_until = _parse_aware_timestamp(manifest.get("valid_until"), "valid_until")
        policy_expiry = _parse_aware_timestamp(policy.get("expires_at"), "policy expires_at") if isinstance(policy, dict) else None
        if cutoff > generated or generated > current or valid_until <= current:
            errors.append("release_time_invalid_or_expired")
        if policy_expiry is not None and valid_until > policy_expiry:
            errors.append("release_exceeds_policy_expiry")
    except ValueError:
        errors.append("manifest_time_invalid")
    errors.extend(_rights_errors(policy, current))
    versions = manifest.get("rights_policy_versions")
    if not isinstance(versions, list) or not isinstance(policy, dict) or policy.get("version") not in versions:
        errors.append("rights_policy_version_mismatch")
    coverage = manifest.get("coverage_report")
    if not isinstance(coverage, dict):
        errors.append("coverage_report_missing")

    gate, gate_error = _json_document(load_object, manifest.get("gate_report"), MAX_GATE_BYTES)
    if gate_error:
        errors.append(gate_error)
    else:
        gate_ref = manifest["gate_report"]
        if (
            gate_ref.get("sha256") != manifest.get("gate_report_hash")
            or gate.get("ok") is not True
            or gate.get("errors") not in ([], None)
        ):
            errors.append("gate_report_invalid")
    _validate_instrument_objects(manifest, load_object, errors)
    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "release_id": release_id,
        "decision_cutoff_at": manifest.get("decision_cutoff_at"),
        "manifest_sha256": hashlib.sha256(_json_bytes(manifest)).hexdigest(),
    }


def _load_current_pointer(store, market):
    path = f"intel/v1/latest-{market}.json"
    content, generation = store.read_pointer(path)
    if content is None:
        return None, generation, None
    try:
        pointer = json.loads(content.decode("utf-8"))
    except (AttributeError, UnicodeError, ValueError):
        return None, generation, "current_pointer_invalid"
    ref = pointer.get("manifest_ref") if isinstance(pointer, dict) else None
    match = _MANIFEST_REF.fullmatch(ref) if isinstance(ref, str) else None
    if (
        not isinstance(pointer, dict)
        or pointer.get("schema_version") != 1
        or pointer.get("market") != market
        or match is None
        or match.group(1) != pointer.get("release_id")
        or type(pointer.get("manifest_size")) is not int
        or not 0 < pointer["manifest_size"] <= MAX_MANIFEST_BYTES
        or re.fullmatch(r"[0-9a-f]{64}", str(pointer.get("manifest_sha256") or "")) is None
    ):
        return None, generation, "current_pointer_invalid"
    manifest_bytes, error = _read_object(store.load_object, ref, MAX_MANIFEST_BYTES)
    if error or len(manifest_bytes) != pointer["manifest_size"] or hashlib.sha256(manifest_bytes).hexdigest() != pointer["manifest_sha256"]:
        return None, generation, "current_pointer_invalid"
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None, generation, "current_pointer_invalid"
    if manifest.get("release_id") != pointer["release_id"] or manifest.get("market") != market:
        return None, generation, "current_pointer_invalid"
    return (pointer, manifest, content), generation, None


def record_source_health(store, report, expected_generation, *, now=None):
    """CAS-update bounded source health independently of content promotion."""
    if not isinstance(report, dict) or type(expected_generation) is not int or expected_generation < 0:
        return {"ok": False, "reason": "health_schema_error"}
    try:
        current = _now(now)
        checked = _parse_aware_timestamp(report.get("checked_at"), "checked_at")
        valid_until = _parse_aware_timestamp(report.get("valid_until"), "valid_until")
    except ValueError:
        return {"ok": False, "reason": "health_time_invalid"}
    status = report.get("status")
    reasons = report.get("reason_codes")
    if (
        type(report.get("schema_version")) is not int
        or report.get("schema_version") != 1
        or report.get("market") != "US"
        or status not in ("healthy", "degraded", "unavailable")
        or checked > current
        or valid_until <= current
        or not isinstance(reasons, list)
        or len(reasons) > 32
        or any(not isinstance(reason, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason) is None for reason in reasons)
        or (status != "healthy" and not reasons)
    ):
        return {"ok": False, "reason": "health_schema_error"}
    value = {
        "schema_version": 1,
        "market": "US",
        "status": status,
        "checked_at": checked.isoformat().replace("+00:00", "Z"),
        "valid_until": valid_until.isoformat().replace("+00:00", "Z"),
        "reason_codes": sorted(set(reasons)),
    }
    content = _json_bytes(value)
    if len(content) > 128 * 1024:
        return {"ok": False, "reason": "health_too_large"}
    path = "intel/v1/health-US.json"
    try:
        previous, generation = store.read_pointer(path)
    except Exception:
        return {"ok": False, "reason": "health_read_failed"}
    if generation != expected_generation:
        return {"ok": False, "reason": "generation_mismatch"}
    if previous is not None:
        try:
            saved = json.loads(previous.decode("utf-8"))
            saved_checked = _parse_aware_timestamp(
                saved.get("checked_at", saved.get("checked_as_of")), "current checked_at"
            )
        except (AttributeError, UnicodeError, ValueError):
            return {"ok": False, "reason": "current_health_invalid"}
        if checked < saved_checked or (checked == saved_checked and previous != content):
            return {"ok": False, "reason": "health_regressed"}
        if checked == saved_checked:
            return {
                "ok": True,
                "idempotent": True,
                "generation": generation,
                "health_sha256": hashlib.sha256(content).hexdigest(),
                "status": status,
                "checked_at": value["checked_at"],
                "valid_until": value["valid_until"],
            }
    try:
        new_generation = store.compare_and_swap_pointer(path, content, expected_generation)
    except Exception:
        new_generation = None
    if new_generation is None:
        return {"ok": False, "reason": "generation_mismatch"}
    try:
        readback, readback_generation = store.read_pointer(path)
    except Exception:
        return {"ok": False, "reason": "health_readback_failed"}
    if readback != content or readback_generation != new_generation:
        return {"ok": False, "reason": "health_readback_failed"}
    return {
        "ok": True,
        "generation": new_generation,
        "health_sha256": hashlib.sha256(content).hexdigest(),
        "status": status,
        "checked_at": value["checked_at"],
        "valid_until": value["valid_until"],
    }


def promote_information_release(store, candidate_ref, expected_generation, *, now=None, policy=None):
    """Promote a validated immutable candidate using store-provided generation CAS.

    Store adapter methods: ``load_object(path, max_bytes)``, ``read_pointer(path)``,
    ``compare_and_swap_pointer(path, bytes, expected_generation)``, and
    ``create_object(path, bytes)``. This repository intentionally supplies no
    production adapter until source rights and storage approval exist.
    """
    match = _MANIFEST_REF.fullmatch(candidate_ref) if isinstance(candidate_ref, str) else None
    if match is None:
        return {"ok": False, "reason": "candidate_ref_invalid"}
    candidate_bytes, error = _read_object(store.load_object, candidate_ref, MAX_MANIFEST_BYTES)
    if error:
        return {"ok": False, "reason": error}
    try:
        manifest = json.loads(candidate_bytes.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {"ok": False, "reason": "manifest_schema_error"}
    if manifest.get("release_id") != match.group(1):
        return {"ok": False, "reason": "candidate_ref_invalid"}
    report = validate_information_release(manifest, store.load_object, policy, now=now)
    if not report["ok"]:
        return {"ok": False, "reason": "candidate_gate_failed", "gate_errors": report["errors"]}

    market = manifest["market"]
    pointer_path = f"intel/v1/latest-{market}.json"
    current, actual_generation, error = _load_current_pointer(store, market)
    if error:
        return {"ok": False, "reason": error}
    manifest_sha = hashlib.sha256(candidate_bytes).hexdigest()
    if current and current[0]["release_id"] == manifest["release_id"]:
        if current[0]["manifest_sha256"] != manifest_sha:
            return {"ok": False, "reason": "release_id_conflict"}
        receipt_path = f"intel/v1/receipts/{manifest['release_id']}.json"
        receipt, receipt_error = _read_object(store.load_object, receipt_path, 128 * 1024)
        if not receipt_error:
            try:
                saved = json.loads(receipt.decode("utf-8"))
            except (UnicodeError, ValueError):
                saved = None
            if isinstance(saved, dict) and saved.get("release_id") == manifest["release_id"]:
                return {"ok": True, "idempotent": True, "generation": actual_generation, "receipt": saved}
    if actual_generation != expected_generation:
        return {"ok": False, "reason": "generation_mismatch"}
    if current:
        previous_cutoff = _parse_aware_timestamp(current[1].get("decision_cutoff_at"), "current cutoff")
        next_cutoff = _parse_aware_timestamp(manifest.get("decision_cutoff_at"), "candidate cutoff")
        if next_cutoff < previous_cutoff:
            return {"ok": False, "reason": "cutoff_regressed"}

    pointer = {
        "schema_version": 1,
        "market": market,
        "release_id": manifest["release_id"],
        "manifest_ref": candidate_ref,
        "manifest_sha256": manifest_sha,
        "manifest_size": len(candidate_bytes),
    }
    pointer_bytes = _json_bytes(pointer)
    try:
        new_generation = store.compare_and_swap_pointer(pointer_path, pointer_bytes, expected_generation)
    except Exception:
        new_generation = None
    if new_generation is None:
        return {"ok": False, "reason": "generation_mismatch"}
    readback, readback_generation = store.read_pointer(pointer_path)
    if readback != pointer_bytes or readback_generation != new_generation:
        return {"ok": False, "reason": "pointer_readback_failed"}

    promoted_at = _now(now).isoformat().replace("+00:00", "Z")
    receipt = {
        "schema_version": 1,
        "release_id": manifest["release_id"],
        "manifest_ref": candidate_ref,
        "manifest_sha256": manifest_sha,
        "expected_generation": expected_generation,
        "generation": new_generation,
        "promoted_at": promoted_at,
        "status": "promoted",
    }
    receipt_bytes = _json_bytes(receipt)
    receipt_path = f"intel/v1/receipts/{manifest['release_id']}.json"
    try:
        created = store.create_object(receipt_path, receipt_bytes)
    except Exception:
        created = False
    if not created:
        existing, read_error = _read_object(store.load_object, receipt_path, 128 * 1024)
        if read_error or existing != receipt_bytes:
            return {"ok": False, "reason": "receipt_write_failed", "generation": new_generation}
    readback_receipt, read_error = _read_object(store.load_object, receipt_path, 128 * 1024)
    if read_error or readback_receipt != receipt_bytes:
        return {"ok": False, "reason": "receipt_readback_failed", "generation": new_generation}
    return {"ok": True, "idempotent": False, "generation": new_generation, "receipt": receipt}
