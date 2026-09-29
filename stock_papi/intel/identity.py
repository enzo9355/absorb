"""Conservative point-in-time issuer/security resolution."""

import datetime
import re

from stock_papi.intel.contracts import _parse_aware_timestamp, _parse_date


def _cik(value):
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,10}", value.strip()) is None:
        raise ValueError("issuer_cik must contain 1 to 10 digits")
    return value.strip().zfill(10)


def _title(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("security_title is required")
    return " ".join(value.casefold().split())


def resolve_instrument(master, issuer_cik, security_title, event_date, knowledge_cutoff):
    """Resolve an exact SEC-title mapping row known by the PIT cutoff.

    ``master`` is a sequence of versioned, source-backed mapping rows, or a
    mapping whose ``records`` value is that sequence. It is not a ticker list.
    """
    cik = _cik(issuer_cik)
    title = _title(security_title)
    effective_date = _parse_date(event_date, "event_date")
    cutoff = _parse_aware_timestamp(knowledge_cutoff, "knowledge_cutoff")
    if isinstance(master, dict):
        records = master.get("records")
    else:
        records = master
    if not isinstance(records, (list, tuple)):
        raise ValueError("master must be a sequence of versioned records")

    matching = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("master record must be a mapping")
        if _cik(record.get("issuer_cik")) != cik or _title(record.get("security_title")) != title:
            continue
        record_id = record.get("record_version_id")
        instrument_id = record.get("instrument_id")
        source_ref = record.get("source_ref")
        if not all(isinstance(value, str) and value.strip() for value in (record_id, instrument_id, source_ref)):
            raise ValueError("matching master record lacks version, instrument, or source")
        known_from = _parse_aware_timestamp(record.get("known_from"), "known_from")
        if known_from > cutoff:
            continue
        effective_from = _parse_date(record.get("effective_from"), "effective_from")
        effective_to = (
            _parse_date(record["effective_to"], "effective_to")
            if record.get("effective_to") is not None else None
        )
        if effective_to is not None and effective_to <= effective_from:
            raise ValueError("master effective interval must be [from,to)")
        matching.append((record, known_from, effective_from, effective_to))

    superseded = {
        row.get("supersedes_version_id")
        for row, _, _, _ in matching
        if isinstance(row.get("supersedes_version_id"), str)
    }
    active_versions = [
        (row, known, start, end)
        for row, known, start, end in matching
        if row["record_version_id"] not in superseded
        and start <= effective_date
        and (end is None or effective_date < end)
    ]
    instruments = {row["instrument_id"] for row, _, _, _ in active_versions}
    if not active_versions:
        return {"status": "unresolved", "instrument_id": None, "reason_codes": ["mapping_unknown"]}
    if len(instruments) != 1:
        return {
            "status": "ambiguous_mapping", "instrument_id": None,
            "reason_codes": ["ambiguous_mapping"],
        }
    record, known_from, _, _ = max(active_versions, key=lambda item: item[1])
    asset_type = str(record.get("asset_type") or "UNKNOWN").upper()
    if asset_type != "COMMON_EQUITY":
        status = "coverage_unknown" if asset_type == "UNKNOWN" else "unsupported_security"
        return {"status": status, "instrument_id": None, "reason_codes": [status]}
    return {
        "status": "resolved",
        "instrument_id": record["instrument_id"],
        "record_version_id": record["record_version_id"],
        "source_ref": record["source_ref"],
        "known_from": known_from.isoformat().replace("+00:00", "Z"),
        "reason_codes": [],
    }
