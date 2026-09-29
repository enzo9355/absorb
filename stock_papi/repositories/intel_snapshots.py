"""Verified Information release reader; no production prefix is read here."""

import datetime
import hashlib
import json
import re

from stock_papi.intel.contracts import _parse_aware_timestamp
from stock_papi.intel.publish import (
    MAX_EVENTS_PAGE_BYTES,
    MAX_FACTS_BYTES,
    MAX_GATE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_SUMMARY_BYTES,
    _MANIFEST_REF,
    _OBJECT_REF,
    _read_object,
    _read_ref,
    _rights_errors,
)


MAX_METADATA_BYTES = 128 * 1024
_INSTRUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _json(content):
    try:
        return json.loads(content.decode("utf-8"))
    except (AttributeError, UnicodeError, ValueError):
        return None


def _unavailable(reason):
    return {"status": "unavailable", "reason_codes": [reason]}


def _metadata(load_object, path, now):
    content, error = _read_object(load_object, path, MAX_METADATA_BYTES)
    if error:
        return None, "source_unavailable"
    value = _json(content)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return None, "schema_error"
    try:
        checked = _parse_aware_timestamp(value.get("checked_at", value.get("checked_as_of")), "metadata checked_at")
        valid_until = _parse_aware_timestamp(value.get("valid_until"), "metadata valid_until")
    except ValueError:
        return None, "schema_error"
    if checked > now or valid_until <= now:
        return None, "source_unavailable"
    return value, None


def _load_manifest(instrument_id, release_id, now, load_object):
    if release_id is None:
        pointer_bytes, error = _read_object(
            load_object, "intel/v1/latest-US.json", MAX_METADATA_BYTES
        )
        if error:
            return None, None, "source_unavailable"
        pointer = _json(pointer_bytes)
        if not isinstance(pointer, dict):
            return None, None, "schema_error"
        ref = pointer.get("manifest_ref")
        match = _MANIFEST_REF.fullmatch(ref) if isinstance(ref, str) else None
        if (
            pointer.get("schema_version") != 1
            or pointer.get("market") != "US"
            or match is None
            or match.group(1) != pointer.get("release_id")
            or type(pointer.get("manifest_size")) is not int
            or not 0 < pointer["manifest_size"] <= MAX_MANIFEST_BYTES
        ):
            return None, None, "schema_error"
        manifest_bytes, error = _read_object(load_object, ref, MAX_MANIFEST_BYTES)
        if error:
            return None, None, "source_unavailable"
        if (
            len(manifest_bytes) != pointer["manifest_size"]
            or hashlib.sha256(manifest_bytes).hexdigest() != pointer.get("manifest_sha256")
        ):
            return None, None, "schema_error"
        manifest = _json(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get("release_id") != pointer["release_id"]:
            return None, None, "schema_error"
    else:
        if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
            return None, None, "schema_error"
        ref = f"intel/v1/manifests/{release_id}.json"
        manifest_bytes, error = _read_object(load_object, ref, MAX_MANIFEST_BYTES)
        if error:
            return None, None, "artifact_revoked"
        manifest = _json(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get("release_id") != release_id:
            return None, None, "schema_error"
    receipt_bytes, receipt_error = _read_object(
        load_object, f"intel/v1/receipts/{manifest.get('release_id')}.json", MAX_METADATA_BYTES
    )
    receipt = _json(receipt_bytes) if not receipt_error else None
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "promoted"
        or receipt.get("release_id") != manifest.get("release_id")
        or receipt.get("manifest_ref") != ref
        or receipt.get("manifest_sha256") != manifest_hash
        or type(receipt.get("generation")) is not int
    ):
        return None, None, "artifact_revoked"
    if (
        manifest.get("schema_version") != 1
        or manifest.get("mode") != "information"
        or manifest.get("market") != "US"
        or manifest.get("model_mode") not in (None, "information")
        or manifest.get("model_version") is not None
    ):
        return None, None, "schema_error"
    try:
        generated = _parse_aware_timestamp(manifest.get("generated_at"), "generated_at")
        cutoff = _parse_aware_timestamp(manifest.get("decision_cutoff_at"), "decision_cutoff_at")
        valid_until = _parse_aware_timestamp(manifest.get("valid_until"), "valid_until")
    except ValueError:
        return None, None, "schema_error"
    if generated > now or cutoff > generated:
        return None, None, "schema_error"
    if valid_until <= now:
        return None, None, "source_delay"
    return manifest, hashlib.sha256(manifest_bytes).hexdigest(), None


def load_intel_snapshot(instrument_id, release_id, now, load_object, *, policy=None, page=1):
    """Load one pinned release page after rechecking current rights and health."""
    if not isinstance(instrument_id, str) or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
        return _unavailable("not_covered")
    try:
        current = _parse_aware_timestamp(now, "now")
    except ValueError:
        return _unavailable("schema_error")
    rights = _rights_errors(policy, current, required_uses=("display_aggregate",))
    if rights:
        return _unavailable(rights[0])

    manifest, manifest_hash, error = _load_manifest(instrument_id, release_id, current, load_object)
    if error:
        return _unavailable(error)
    policy_versions = manifest.get("rights_policy_versions")
    if not isinstance(policy_versions, list) or policy.get("version") not in policy_versions:
        return _unavailable("rights_policy_unknown")
    health, error = _metadata(load_object, "intel/v1/health-US.json", current)
    if error:
        return _unavailable(error)
    if health.get("market") != "US" or health.get("status") != "healthy":
        return _unavailable("source_unavailable")
    revocations, error = _metadata(load_object, "intel/v1/revocations.json", current)
    if error:
        return _unavailable(error)
    revoked_releases = revocations.get("revoked_release_ids")
    revoked_hashes = revocations.get("revoked_object_sha256")
    if not isinstance(revoked_releases, list) or not isinstance(revoked_hashes, list):
        return _unavailable("schema_error")
    if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in revoked_hashes):
        return _unavailable("schema_error")
    if manifest["release_id"] in revoked_releases or manifest_hash in revoked_hashes:
        return _unavailable("artifact_revoked")

    gate_ref = manifest.get("gate_report")
    gate, _, error = _read_ref(load_object, gate_ref, MAX_GATE_BYTES)
    if error:
        return _unavailable(error)
    if isinstance(gate_ref, dict) and gate_ref.get("sha256") in revoked_hashes:
        return _unavailable("artifact_revoked")
    if hashlib.sha256(gate).hexdigest() != manifest.get("gate_report_hash"):
        return _unavailable("schema_error")
    gate_report = _json(gate)
    if not isinstance(gate_report, dict) or gate_report.get("ok") is not True:
        return _unavailable("schema_error")

    instruments = manifest.get("instrument_objects")
    refs = instruments.get(instrument_id) if isinstance(instruments, dict) else None
    if not isinstance(refs, dict):
        return _unavailable("not_covered")
    pages = refs.get("events")
    if not isinstance(pages, list) or type(page) is not int or not 1 <= page <= len(pages):
        return _unavailable("schema_error")
    summary_bytes, summary, error = _read_ref(load_object, refs.get("summary"), MAX_SUMMARY_BYTES)
    if error:
        return _unavailable(error)
    page_bytes, event_page, error = _read_ref(load_object, pages[page - 1], MAX_EVENTS_PAGE_BYTES)
    if error:
        return _unavailable(error)
    content_refs = [refs.get("summary"), pages[page - 1]]
    facts = None
    if refs.get("facts") is not None:
        fact_bytes, facts, error = _read_ref(load_object, refs["facts"], MAX_FACTS_BYTES)
        if error:
            return _unavailable(error)
        content_refs.append(refs["facts"])
    if any(ref.get("sha256") in revoked_hashes for ref in content_refs if isinstance(ref, dict)):
        return _unavailable("artifact_revoked")
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version") != "intel-api-v1"
        or summary.get("instrument_id") != instrument_id
        or summary.get("release_id") != manifest.get("release_id")
        or summary.get("status") not in {"available", "partial", "stale", "unavailable"}
        or not isinstance(summary.get("reason_codes"), list)
        or not isinstance(event_page, dict)
        or event_page.get("schema_version") != "intel-events-v1"
        or event_page.get("instrument_id") != instrument_id
        or event_page.get("release_id") != manifest.get("release_id")
        or event_page.get("page") != page
        or event_page.get("page_count") != len(pages)
        or not isinstance(event_page.get("events"), list)
        or len(event_page["events"]) > 50
        or any(not isinstance(row, dict) for row in event_page["events"])
        or (facts is not None and (not isinstance(facts, dict) or facts.get("instrument_id") != instrument_id))
    ):
        return _unavailable("schema_error")
    return {
        "status": summary["status"],
        "reason_codes": list(summary["reason_codes"]),
        "instrument_id": instrument_id,
        "release": {
            "release_id": manifest["release_id"],
            "generated_at": manifest["generated_at"],
            "decision_cutoff_at": manifest["decision_cutoff_at"],
            "valid_until": manifest["valid_until"],
            "manifest_hash": manifest_hash,
        },
        "summary": summary.get("summary"),
        "events": event_page["events"],
        "event_page": {"page": page, "page_count": len(pages)},
        "fact_ids": summary.get("fact_ids", []),
        "source_checks": health.get("source_checks", []),
    }
