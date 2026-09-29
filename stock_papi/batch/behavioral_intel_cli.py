"""Explicit local replay of caller-supplied Form 4 XML; no network or GCS path."""

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from stock_papi.intel.contracts import _parse_aware_timestamp
from stock_papi.intel.sec_form4 import (
    MAX_FORM4_XML_BYTES,
    parse_form4,
    reconcile_rows,
    validate_fetch_record,
)


MAX_RECORD_BYTES = 1_000_000
PROTECTED_ROOTS = (Path(r"D:\AbsorbData"), Path(r"D:\StockPapiData"))


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_content_addressed(path, content):
    """Atomically persist a hash-addressed object and verify existing bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = hashlib.sha256(content).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("content-addressed object hash mismatch")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".intel-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("content-addressed object hash mismatch")
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _json_bytes(value)
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _read_record(path):
    if not path.exists():
        return None, None, "fetch_record_missing"
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return None, None, "fetch_record_too_large"
        content = path.read_bytes()
        if len(content) > MAX_RECORD_BYTES:
            return None, None, "fetch_record_too_large"
        record = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None, None, "fetch_record_invalid"
    if not isinstance(record, dict):
        return None, None, "fetch_record_invalid"
    return record, hashlib.sha256(content).hexdigest(), None


def _rights_storage_error(record):
    if record.get("synthetic") is True:
        return None
    policy = record.get("rights_policy")
    if not isinstance(policy, dict):
        return "rights_policy_unknown"
    required_text = ("policy_id", "version", "reviewer", "retention_policy")
    if any(not isinstance(policy.get(key), str) or not policy[key].strip() for key in required_text):
        return "rights_policy_unknown"
    if record.get("rights_policy_version") != policy["version"]:
        return "rights_policy_unknown"
    evidence = policy.get("evidence_urls")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(url, str) and url.startswith("https://") for url in evidence
    ):
        return "rights_policy_unknown"
    try:
        reviewed_at = _parse_aware_timestamp(policy.get("reviewed_at"), "reviewed_at")
        effective_from = _parse_aware_timestamp(policy.get("effective_from"), "effective_from")
        expires_at = _parse_aware_timestamp(policy.get("expires_at"), "expires_at")
    except ValueError:
        return "rights_policy_unknown"
    now = datetime.datetime.now(datetime.timezone.utc)
    if reviewed_at > now or effective_from > now or expires_at <= now:
        return "rights_restricted"
    uses = (
        "fetch", "store_raw", "store_derived", "display_raw", "display_aggregate",
        "training", "inference", "external_LLM",
    )
    if any(
        not isinstance(policy.get(use), str)
        or policy[use] not in {"allowed", "denied", "unknown"}
        for use in uses
    ):
        return "rights_policy_unknown"
    if policy["store_raw"] == "denied" or policy["store_derived"] == "denied":
        return "rights_restricted"
    if policy["store_raw"] != "allowed" or policy["store_derived"] != "allowed":
        return "rights_policy_unknown"
    return None


def run_offline_replay(input_dir, output_dir, cutoff):
    input_path = Path(input_dir).resolve(strict=True)
    output_path = Path(output_dir).resolve()
    cutoff_at = _parse_aware_timestamp(cutoff, "cutoff")
    cutoff = cutoff_at.isoformat().replace("+00:00", "Z")
    if not input_path.is_dir():
        raise ValueError("input_dir must be a directory")
    if output_path == input_path or _inside(output_path, input_path):
        raise ValueError("output_dir cannot be inside input_dir")
    if any(_inside(output_path, root.resolve()) for root in PROTECTED_ROOTS):
        raise ValueError("output_dir cannot target a production data root")

    files = sorted(input_path.glob("*.xml"), key=lambda path: path.name.casefold())
    discoveries = []
    for source in files:
        try:
            size = source.stat().st_size
        except OSError:
            size = None
        discoveries.append({"file_name": source.name, "size": size})
    discovery = {
        "schema_version": 1,
        "mode": "offline_replay",
        "cutoff": cutoff,
        "items": discoveries,
    }
    discovery_bytes = _json_bytes(discovery)
    discovery_hash = hashlib.sha256(discovery_bytes).hexdigest()
    discovery_ref = f"discovery/{discovery_hash}.json"
    _write_content_addressed(output_path / discovery_ref, discovery_bytes)
    checkpoint = {
        "schema_version": 1,
        "mode": "offline_replay",
        "state": "running",
        "cutoff": cutoff,
        "discovery_ref": discovery_ref,
        "processed_file_names": [],
    }
    _atomic_json(output_path / "checkpoint.json", checkpoint)
    item_records = []
    parsed_batches = []
    counts = {
        "discovered": len(files), "parsed": 0, "pending": 0,
        "quarantined": 0, "explicitly_excluded": 0,
    }
    acquired = 0
    for source in files:
        item = {"file_name": source.name}
        try:
            size = source.stat().st_size
            if size > MAX_FORM4_XML_BYTES:
                raise OverflowError
        except OverflowError:
            item.update({"status": "quarantined", "size": size, "errors": ["raw_document_too_large"]})
            counts["quarantined"] += 1
            item_records.append(item)
            continue
        except OSError:
            item.update({"status": "pending", "errors": ["input_unreadable"]})
            counts["pending"] += 1
            item_records.append(item)
            continue
        record, record_digest, record_error = _read_record(source.with_suffix(".record.json"))
        if record_error:
            item.update({"status": "pending", "errors": [record_error]})
            counts["pending"] += 1
            item_records.append(item)
            continue
        try:
            record = validate_fetch_record(record)
            item["first_seen_at"] = record["first_seen_at"]
            if _parse_aware_timestamp(record["first_seen_at"], "first_seen_at") > cutoff_at:
                item.update({
                    "status": "explicitly_excluded",
                    "errors": ["first_seen_after_cutoff"],
                })
                counts["explicitly_excluded"] += 1
                item_records.append(item)
                checkpoint["processed_file_names"].append(source.name)
                checkpoint["counts"] = dict(counts)
                _atomic_json(output_path / "checkpoint.json", checkpoint)
                continue
        except ValueError as exc:
            item.update({"status": "quarantined", "errors": [str(exc)]})
            counts["quarantined"] += 1
            item_records.append(item)
            checkpoint["processed_file_names"].append(source.name)
            checkpoint["counts"] = dict(counts)
            _atomic_json(output_path / "checkpoint.json", checkpoint)
            continue
        rights_error = _rights_storage_error(record)
        if rights_error:
            item.update({"status": "pending", "errors": [rights_error]})
            counts["pending"] += 1
            item_records.append(item)
            checkpoint["processed_file_names"].append(source.name)
            checkpoint["counts"] = dict(counts)
            _atomic_json(output_path / "checkpoint.json", checkpoint)
            continue
        try:
            raw_bytes = source.read_bytes()
            if len(raw_bytes) > MAX_FORM4_XML_BYTES:
                raise ValueError("raw_document_too_large")
        except ValueError as exc:
            item.update({"status": "quarantined", "errors": [str(exc)]})
            counts["quarantined"] += 1
            item_records.append(item)
            checkpoint["processed_file_names"].append(source.name)
            checkpoint["counts"] = dict(counts)
            _atomic_json(output_path / "checkpoint.json", checkpoint)
            continue
        except OSError:
            item.update({"status": "pending", "errors": ["input_unreadable"]})
            counts["pending"] += 1
            item_records.append(item)
            checkpoint["processed_file_names"].append(source.name)
            checkpoint["counts"] = dict(counts)
            _atomic_json(output_path / "checkpoint.json", checkpoint)
            continue
        digest = hashlib.sha256(raw_bytes).hexdigest()
        item["raw_sha256"] = digest
        item["fetch_record_sha256"] = record_digest
        _write_content_addressed(output_path / "raw" / f"{digest}.xml", raw_bytes)
        item["raw_ref"] = f"raw/{digest}.xml"
        acquired += 1
        result = parse_form4(raw_bytes, record)
        if result["errors"]:
            quarantine_bytes = _json_bytes({"file_name": source.name, "errors": result["errors"]})
            quarantine_hash = hashlib.sha256(quarantine_bytes).hexdigest()
            _write_content_addressed(
                output_path / "quarantine" / f"{quarantine_hash}.json", quarantine_bytes
            )
            item.update({
                "status": "quarantined",
                "errors": result["errors"],
                "quarantine_ref": f"quarantine/{quarantine_hash}.json",
            })
            counts["quarantined"] += 1
        else:
            parsed_bytes = _json_bytes(result)
            parsed_hash = hashlib.sha256(parsed_bytes).hexdigest()
            _write_content_addressed(
                output_path / "parsed" / f"{parsed_hash}.json", parsed_bytes
            )
            item.update({
                "status": "parsed",
                "row_count": len(result["rows"]),
                "row_error_count": result["filing"]["row_error_count"],
                "parsed_ref": f"parsed/{parsed_hash}.json",
            })
            counts["parsed"] += 1
            parsed_batches.append((record, result))
        item_records.append(item)
        checkpoint["processed_file_names"].append(source.name)
        checkpoint["counts"] = dict(counts)
        _atomic_json(output_path / "checkpoint.json", checkpoint)

    reconciliation = None
    reconciliation_ref = None
    if parsed_batches:
        original_rows = []
        amendment_rows = []
        linkage_evidence = []
        for record, result in parsed_batches:
            if result["filing"]["form_type"] == "4/A":
                amendment_rows.extend(result["rows"])
                evidence = record.get("linkage_evidence") or []
                if not isinstance(evidence, list):
                    raise ValueError("linkage_evidence must be a list")
                linkage_evidence.extend(evidence)
            else:
                original_rows.extend(result["rows"])
        reconciled = reconcile_rows(original_rows, amendment_rows, linkage_evidence)
        reconciled_bytes = _json_bytes(reconciled)
        reconciled_hash = hashlib.sha256(reconciled_bytes).hexdigest()
        _write_content_addressed(
            output_path / "reconciled" / f"{reconciled_hash}.json", reconciled_bytes
        )
        reconciliation_ref = f"reconciled/{reconciled_hash}.json"
        reconciliation = {
            "version_count": len(reconciled["versions"]),
            "link_count": len(reconciled["links"]),
            "unresolved_count": len(reconciled["unresolved"]),
            "aggregation_eligible_count": sum(
                item.get("aggregation_eligibility") is True for item in reconciled["versions"]
            ),
        }
    receipt = {
        "schema_version": 1,
        "mode": "offline_replay",
        "cutoff": cutoff,
        "discovery_ref": discovery_ref,
        "items": item_records,
        "counts": counts,
        "input_file_acquisition_coverage": acquired / len(files) if files else None,
        "source_coverage_status": "partial" if files else "unavailable",
        "source_coverage_complete": False,
        "reconciliation": reconciliation,
        "reconciliation_ref": reconciliation_ref,
    }
    run_id = hashlib.sha256(_json_bytes(receipt)).hexdigest()
    receipt["run_id"] = run_id
    receipt_bytes = _json_bytes(receipt)
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path = output_path / "receipts" / f"{receipt_hash}.json"
    _write_content_addressed(receipt_path, receipt_bytes)
    _atomic_json(output_path / "checkpoint.json", {
        "schema_version": 1,
        "mode": "offline_replay",
        "state": "complete",
        "run_id": run_id,
        "discovery_ref": discovery_ref,
        "receipt_ref": f"receipts/{receipt_hash}.json",
    })
    return {**receipt, "receipt_ref": f"receipts/{receipt_hash}.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-only Form 4/4A XML replay")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_offline_replay(args.input_dir, args.output_dir, args.cutoff)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    complete = result["counts"]["pending"] == 0 and result["counts"]["quarantined"] == 0
    print(json.dumps({
        "ok": complete,
        "run_id": result["run_id"],
        "counts": result["counts"],
        "source_coverage_status": result["source_coverage_status"],
        "source_coverage_complete": result["source_coverage_complete"],
        "receipt_ref": result["receipt_ref"],
        "reconciliation": result["reconciliation"],
    }, ensure_ascii=False))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
