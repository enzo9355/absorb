"""Bounded local importer for manually reviewed public activities.

Reads a small hand-built JSON file, validates subjects/activities with the
same contracts as the web catalog, and writes a candidate JSON to a NEW file.
Never overwrites the input, the catalog, or an existing candidate.
Pending rows are never auto-promoted to confirmed.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from stock_papi.services.public_opinions import (
    _validate_subjects,
    validate_activity,
)

MAX_INPUT_BYTES = 1_000_000


def _fail(message, code=2):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    return code


def _load_json(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, "input_unreadable"
    if size > MAX_INPUT_BYTES:
        return None, "input_too_large"
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            return None, "input_too_large"
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        return None, "input_invalid_json"
    return document, None


def _load_catalog_activities(catalog_path):
    try:
        with open(catalog_path, "rb") as handle:
            document = json.loads(handle.read(MAX_INPUT_BYTES + 1).decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return {}, None
    existing = {}
    if isinstance(document, dict):
        for item in document.get("activities") or []:
            if isinstance(item, dict) and item.get("activity_id"):
                existing[str(item["activity_id"])] = item
        subjects = {}
        for row in document.get("subjects") or []:
            if isinstance(row, dict) and row.get("subject_id"):
                subjects[str(row["subject_id"])] = row
        return existing, subjects
    return {}, {}


def build_candidate(input_doc, existing_ids, existing_subjects):
    if not isinstance(input_doc, dict):
        return None, "input_must_be_mapping"
    subjects_in = input_doc.get("subjects") or []
    activities_in = input_doc.get("activities") or []
    if not isinstance(subjects_in, list) or not isinstance(activities_in, list):
        return None, "input_lists_required"

    subjects_rows, subject_map, subject_errors = _validate_subjects(subjects_in)
    # Merge known catalog subjects so activities can reference existing subjects.
    merged_subjects = dict(existing_subjects or {})
    for row in subjects_rows:
        sid = str(row.get("subject_id") or "")
        if sid and sid not in merged_subjects:
            merged_subjects[sid] = row
    # Re-resolve verification for merged map: catalog rows may lack flags.
    resolved_map = {}
    for sid, row in merged_subjects.items():
        if isinstance(row, dict) and "is_verified" in row:
            resolved_map[sid] = row
        else:
            tmp_rows, tmp_map, _ = _validate_subjects([row])
            resolved_map[sid] = tmp_map.get(sid, {"is_verified": False})

    added = 0
    duplicate = 0
    pending = 0
    rejected = 0
    candidate_rows = []
    details = []
    seen_in_batch = set()
    for index, raw in enumerate(activities_in):
        if not isinstance(raw, dict):
            rejected += 1
            details.append({"index": index, "verdict": "rejected", "reasons": ["not_mapping"]})
            continue
        validated = validate_activity(raw, resolved_map)
        activity_id = str(validated.get("activity_id") or "")
        reasons = list(validated.get("validation_errors") or [])
        if activity_id and (activity_id in existing_ids or activity_id in seen_in_batch):
            reasons = reasons + ["duplicate_activity_id"]
            validated = dict(validated, validation_errors=reasons, is_confirmed=False)
        if activity_id:
            seen_in_batch.add(activity_id)
        # Never auto-promote: pending_review stays pending even if otherwise valid.
        if str(raw.get("review_status") or "").strip() != "confirmed":
            pending += 1
            details.append({"index": index, "activity_id": activity_id,
                            "verdict": "pending", "reasons": reasons})
            candidate_rows.append(validated)
            continue
        if validated.get("is_confirmed"):
            added += 1
            details.append({"index": index, "activity_id": activity_id, "verdict": "added", "reasons": []})
        else:
            rejected += 1
            details.append({"index": index, "activity_id": activity_id,
                            "verdict": "rejected", "reasons": reasons})
        candidate_rows.append(validated)

    candidate = {
        "candidate_schema_version": 1,
        "subjects": subjects_rows,
        "subject_errors": subject_errors,
        "activities": candidate_rows,
        "summary": {"added": added, "duplicate": duplicate + sum(1 for d in details if "duplicate_activity_id" in d.get("reasons", [])),
                    "pending": pending, "rejected": rejected},
        "details": details,
    }
    # Count duplicates separately for clarity.
    dup_count = sum(1 for d in details if "duplicate_activity_id" in d.get("reasons", []))
    candidate["summary"]["duplicate"] = dup_count
    return candidate, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate manual public-activity input into a new candidate file.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    catalog_path = Path(args.catalog)
    output_path = Path(args.output)

    # Output must differ from input/catalog; exclusive create.
    try:
        if output_path.resolve() == input_path.resolve():
            return _fail("output_must_differ_from_input")
        if output_path.resolve() == catalog_path.resolve():
            return _fail("output_must_differ_from_catalog")
    except OSError:
        pass
    if output_path.exists():
        return _fail("output_already_exists")

    input_doc, error = _load_json(str(input_path))
    if error:
        return _fail(error)
    existing_ids, existing_subjects = _load_catalog_activities(str(catalog_path))
    candidate, candidate_error = build_candidate(input_doc, existing_ids, existing_subjects)
    if candidate_error:
        return _fail(candidate_error)

    # Exclusive create: fail if raced into existence.
    try:
        with open(output_path, "x", encoding="utf-8") as handle:
            json.dump(candidate, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError:
        return _fail("output_already_exists")
    except OSError:
        return _fail("output_unwritable")

    summary = candidate["summary"]
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
