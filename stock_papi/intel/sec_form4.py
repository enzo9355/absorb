"""Offline Form 4/4A XML parsing and explicit row-level revision linkage."""

import hashlib
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

from stock_papi.intel.contracts import _parse_aware_timestamp, _parse_date


MAX_FORM4_XML_BYTES = 20 * 1024 * 1024
_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")


def _local_name(tag):
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def _child(node, name):
    if node is None:
        return None
    return next((item for item in node if _local_name(item.tag) == name), None)


def _path(node, *names):
    for name in names:
        node = _child(node, name)
        if node is None:
            return None
    return node


def _field_record(node, *path):
    field = _path(node, *path)
    if field is None:
        return {"value": None, "footnote_ids": []}
    value_node = _child(field, "value")
    value = (
        "".join(value_node.itertext()).strip()
        if value_node is not None
        else (field.text or "").strip()
    )
    return {
        "value": value or None,
        "footnote_ids": sorted({
            item.attrib["id"] for item in field.iter()
            if _local_name(item.tag) == "footnoteId" and item.attrib.get("id")
        }),
    }


def _canonical_cik(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,10}", value.strip()) is None:
        raise ValueError("invalid_cik")
    return value.strip().zfill(10)


def _decimal(field):
    raw = field["value"]
    if raw is None:
        status = "footnote_only" if field["footnote_ids"] else "missing"
        return None, status
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw) is None:
        return None, "invalid"
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, "invalid"
    if not value.is_finite() or value < 0:
        return None, "invalid"
    return format(value.normalize(), "f"), "value"


def _iso_date(field):
    if field["value"] is None:
        return None
    try:
        return _parse_date(field["value"], "Form 4 date").isoformat()
    except ValueError:
        return None


def _owner(node):
    owner_id = _child(node, "reportingOwnerId")
    relationship = _child(node, "reportingOwnerRelationship")
    raw_cik = _field_record(owner_id, "rptOwnerCik")["value"]
    raw_name = _field_record(owner_id, "rptOwnerName")["value"]
    try:
        cik = _canonical_cik(raw_cik)
    except ValueError:
        cik = None
    roles = {}
    for tag in ("isDirector", "isOfficer", "isTenPercentOwner", "isOther"):
        value = _field_record(relationship, tag)["value"]
        roles[tag] = True if value in {"1", "true", "TRUE"} else (
            False if value in {"0", "false", "FALSE"} else None
        )
    return {"cik": cik, "name": raw_name, "roles": roles}


def _metadata(fetch_record):
    if not isinstance(fetch_record, dict):
        raise ValueError("fetch_record_required")
    accession = fetch_record.get("accession")
    form_type = str(fetch_record.get("form_type") or "").strip().upper()
    if not isinstance(accession, str) or _ACCESSION.fullmatch(accession) is None:
        raise ValueError("invalid_accession")
    if form_type not in {"4", "4/A"}:
        raise ValueError("invalid_form_type")
    url = fetch_record.get("source_url")
    try:
        parsed_url = urlsplit(url)
        port = parsed_url.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_source_url") from exc
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname not in {"sec.gov", "www.sec.gov"}
        or not parsed_url.path.startswith("/Archives/edgar/data/")
        or parsed_url.username is not None
        or parsed_url.password is not None
        or port not in {None, 443}
        or parsed_url.query
        or parsed_url.fragment
        or f"/{accession.replace('-', '')}/" not in parsed_url.path + "/"
    ):
        raise ValueError("source_url_not_allowlisted")
    first_seen_at = _parse_aware_timestamp(fetch_record.get("first_seen_at"), "first_seen_at")
    accepted_at = fetch_record.get("accepted_at")
    if accepted_at is not None:
        accepted_at = _parse_aware_timestamp(accepted_at, "accepted_at")
    source_public_date = fetch_record.get("source_public_date")
    if source_public_date is not None:
        source_public_date = _parse_date(source_public_date, "source_public_date").isoformat()
    source_timezone = fetch_record.get("source_timezone")
    return {
        **fetch_record,
        "accession": accession,
        "form_type": form_type,
        "source_url": url,
        "first_seen_at": first_seen_at.isoformat().replace("+00:00", "Z"),
        "accepted_at": accepted_at.isoformat().replace("+00:00", "Z") if accepted_at else None,
        "source_public_date": source_public_date,
        "source_timezone": source_timezone,
    }


def validate_fetch_record(fetch_record):
    """Validate source identifiers and timestamps without fetching or storing."""
    return _metadata(fetch_record)


def _parse_row(node, *, table_kind, row_kind, ordinal, accession, digest, owners):
    source_row_id = f"{accession}:{table_kind}:{ordinal}"
    shares_path = (
        ("sharesOwnedFollowingTransaction",)
        if row_kind == "holding"
        else ("transactionAmounts", "transactionShares")
    )
    direct_path = (
        ("directOrIndirectOwnership",)
        if row_kind == "holding"
        else ("postTransactionAmounts", "directOrIndirectOwnership")
    )
    raw = {
        "security_title": _field_record(node, "securityTitle"),
        "transaction_date": _field_record(node, "transactionDate"),
        "deemed_execution_date": _field_record(node, "deemedExecutionDate"),
        "transaction_code": _field_record(node, "transactionCoding", "transactionCode"),
        "shares": _field_record(node, *shares_path),
        "price_per_share": _field_record(node, "transactionAmounts", "transactionPricePerShare"),
        "post_transaction_shares": _field_record(
            node, "postTransactionAmounts", "sharesOwnedFollowingTransaction"
        ),
        "acquired_disposed": _field_record(
            node, "transactionAmounts", "transactionAcquiredDisposedCode"
        ),
        "direct_indirect": _field_record(node, *direct_path),
        "ownership_nature": _field_record(node, "ownershipNature"),
    }
    shares, shares_status = _decimal(raw["shares"])
    price, price_status = _decimal(raw["price_per_share"])
    post_shares, post_shares_status = _decimal(raw["post_transaction_shares"])
    transaction_date = _iso_date(raw["transaction_date"])
    deemed_date = _iso_date(raw["deemed_execution_date"])
    code = raw["transaction_code"]["value"]
    acquired_disposed = raw["acquired_disposed"]["value"]
    security_title = raw["security_title"]["value"]
    row_errors = []
    if not security_title:
        row_errors.append("security_title_missing")
    if row_kind == "transaction" and not transaction_date:
        row_errors.append("transaction_date_missing")
    if row_kind == "transaction" and shares is None:
        row_errors.append("transaction_shares_" + shares_status)
    if row_kind == "holding" and shares is None:
        row_errors.append("holding_shares_" + shares_status)
    if row_kind == "transaction" and (not code or acquired_disposed not in {"A", "D"}):
        row_errors.append("transaction_code_or_acquired_disposed_missing")
    if raw["transaction_date"]["value"] and not transaction_date:
        row_errors.append("transaction_date_invalid")
    if raw["shares"]["value"] and shares is None:
        row_errors.append("shares_invalid")
    if raw["price_per_share"]["value"] and price is None:
        row_errors.append("price_invalid")
    if (code == "P" and acquired_disposed != "A") or (code == "S" and acquired_disposed != "D"):
        classification = "classification_conflict"
        if row_kind == "transaction":
            row_errors.append("code_acquired_disposed_conflict")
    elif table_kind == "non_derivative" and row_kind == "transaction" and code == "P":
        classification = "purchase_disclosed"
    elif table_kind == "non_derivative" and row_kind == "transaction" and code == "S":
        classification = "sale_disclosed"
    else:
        classification = "other_disclosure"
    version_material = f"{accession}\n{source_row_id}\n{digest}".encode("utf-8")
    footnote_ids = sorted({
        footnote for field in raw.values() for footnote in field["footnote_ids"]
    })
    normalized = {
        "security_title": security_title,
        "transaction_date": transaction_date,
        "deemed_execution_date": deemed_date,
        "transaction_code": code,
        "acquired_disposed": acquired_disposed,
        "shares": shares,
        "shares_status": shares_status,
        "price_per_share": price,
        "price_status": price_status,
        "price_footnote_ids": raw["price_per_share"]["footnote_ids"],
        "post_transaction_shares": post_shares,
        "post_transaction_shares_status": post_shares_status,
        "direct_indirect": raw["direct_indirect"]["value"],
        "ownership_nature": raw["ownership_nature"]["value"],
        "transaction_classification": classification,
        "footnote_ids": footnote_ids,
    }
    return {
        "event_id": source_row_id,
        "event_version_id": hashlib.sha256(version_material).hexdigest(),
        "source_document_id": accession,
        "source_row_id": source_row_id,
        "table_kind": table_kind,
        "row_kind": row_kind,
        "row_ordinal": ordinal,
        "reporting_owners": [dict(owner) for owner in owners],
        "raw_value": raw,
        "normalized_payload": normalized,
        "revision_kind": "original",
        "linkage_status": "not_applicable",
        "supersedes_version_id": None,
        "aggregation_eligibility": False,
        "errors": row_errors,
    }


def parse_form4(raw_bytes, fetch_record):
    """Parse one offline Form 4/4A XML document; never performs network I/O."""
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        return {"filing": None, "rows": [], "errors": ["raw_xml_required"]}
    if len(raw_bytes) > MAX_FORM4_XML_BYTES:
        return {"filing": None, "rows": [], "errors": ["raw_document_too_large"]}
    try:
        record = _metadata(fetch_record)
    except ValueError as exc:
        return {"filing": None, "rows": [], "errors": [str(exc)]}
    try:
        root = SafeET.fromstring(raw_bytes)
    except DefusedXmlException:
        return {"filing": None, "rows": [], "errors": ["unsafe_xml"]}
    except (ParseError, LookupError, UnicodeError, ValueError):
        return {"filing": None, "rows": [], "errors": ["xml_parse_error"]}
    if _local_name(root.tag) != "ownershipDocument":
        return {"filing": None, "rows": [], "errors": ["not_ownership_document"]}

    form_type = (_field_record(root, "documentType")["value"] or "").strip().upper()
    if form_type not in {"4", "4/A"} or form_type != record["form_type"]:
        return {"filing": None, "rows": [], "errors": ["form_type_mismatch"]}
    issuer_node = _child(root, "issuer")
    try:
        issuer_cik = _canonical_cik(_field_record(issuer_node, "issuerCik")["value"])
    except ValueError:
        return {"filing": None, "rows": [], "errors": ["issuer_cik_missing_or_invalid"]}
    period = _field_record(root, "periodOfReport")["value"]
    try:
        period = _parse_date(period, "periodOfReport").isoformat()
    except ValueError:
        return {"filing": None, "rows": [], "errors": ["period_of_report_invalid"]}
    owners = [_owner(item) for item in root if _local_name(item.tag) == "reportingOwner"]
    if not owners:
        return {"filing": None, "rows": [], "errors": ["reporting_owner_missing"]}
    footnotes = {}
    for container in root:
        if _local_name(container.tag) != "footnotes":
            continue
        for node in container:
            if _local_name(node.tag) != "footnote" or not node.attrib.get("id"):
                continue
            footnote_id = node.attrib["id"]
            if footnote_id in footnotes:
                return {"filing": None, "rows": [], "errors": ["duplicate_footnote_id"]}
            footnotes[footnote_id] = "".join(node.itertext()).strip()

    digest = hashlib.sha256(raw_bytes).hexdigest()
    rows = []
    for table_tag, table_kind in (("nonDerivativeTable", "non_derivative"), ("derivativeTable", "derivative")):
        table = _child(root, table_tag)
        if table is None:
            continue
        ordinal = 0
        for node in table:
            node_name = _local_name(node.tag)
            if node_name not in {"nonDerivativeTransaction", "nonDerivativeHolding", "derivativeTransaction", "derivativeHolding"}:
                continue
            row_kind = "holding" if node_name.endswith("Holding") else "transaction"
            rows.append(_parse_row(
                node, table_kind=table_kind, row_kind=row_kind, ordinal=ordinal,
                accession=record["accession"], digest=digest, owners=owners,
            ))
            ordinal += 1
    filing = {
        "accession": record["accession"],
        "form_type": form_type,
        "period_of_report": period,
        "filing_accepted_at": record.get("accepted_at"),
        "source_public_date": record.get("source_public_date"),
        "source_timezone": record.get("source_timezone"),
        "first_seen_at": record["first_seen_at"],
        "source_url": record["source_url"],
        "rights_policy_version": record.get("rights_policy_version", "unknown"),
        "raw_sha256": digest,
        "issuer": {
            "cik": issuer_cik,
            "name": _field_record(issuer_node, "issuerName")["value"],
            "trading_symbol": _field_record(issuer_node, "issuerTradingSymbol")["value"],
        },
        "reporting_owners": owners,
        "footnotes": footnotes,
        "row_count": len(rows),
        "row_error_count": sum(bool(row["errors"]) for row in rows),
    }
    return {"filing": filing, "rows": rows, "errors": []}


def reconcile_rows(original_rows, amendment_rows, linkage_evidence):
    """Apply only explicit row links; ambiguous or absent links stay ineligible."""
    if not all(isinstance(items, (list, tuple)) for items in (original_rows, amendment_rows, linkage_evidence)):
        raise ValueError("rows and linkage_evidence must be sequences")
    originals = [dict(row) for row in original_rows]
    amendments = [dict(row) for row in amendment_rows]
    original_by_id = {}
    for row in originals:
        if not isinstance(row, dict):
            raise ValueError("rows must be mappings")
        source_row_id = row.get("source_row_id")
        if not isinstance(source_row_id, str) or not source_row_id or source_row_id in original_by_id:
            raise ValueError("original source_row_id must be unique")
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in (
            "event_id", "event_version_id"
        )):
            raise ValueError("row event and version ids are required")
        original_by_id[source_row_id] = row
    amendment_by_id = {}
    for row in amendments:
        if not isinstance(row, dict):
            raise ValueError("rows must be mappings")
        source_row_id = row.get("source_row_id")
        if not isinstance(source_row_id, str) or not source_row_id or source_row_id in amendment_by_id:
            raise ValueError("amendment source_row_id must be unique")
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in (
            "event_id", "event_version_id"
        )):
            raise ValueError("row event and version ids are required")
        amendment_by_id[source_row_id] = row
    version_ids = [row["event_version_id"] for row in (*originals, *amendments)]
    if len(version_ids) != len(set(version_ids)):
        raise ValueError("event_version_id must be unique")

    evidence_by_amendment = {}
    for evidence in linkage_evidence:
        if not isinstance(evidence, dict):
            raise ValueError("linkage evidence must be a mapping")
        amendment_id = evidence.get("amendment_source_row_id")
        if not isinstance(amendment_id, str) or amendment_id not in amendment_by_id:
            raise ValueError("linkage evidence references unknown amendment row")
        original_id = evidence.get("original_source_row_id")
        candidate_ids = evidence.get("original_source_row_ids", [])
        if original_id is not None and (
            not isinstance(original_id, str) or not original_id
        ):
            raise ValueError("revision candidate ids must be non-empty strings")
        if not isinstance(candidate_ids, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in candidate_ids
        ):
            raise ValueError("revision candidate ids must be non-empty strings")
        evidence_by_amendment.setdefault(amendment_id, []).append(evidence)

    links = []
    unresolved = []
    for amendment_id, row in amendment_by_id.items():
        evidence_rows = evidence_by_amendment.get(amendment_id, [])
        if len(evidence_rows) == 1 and evidence_rows[0].get("status") == "new":
            evidence = evidence_rows[0]
            try:
                _parse_aware_timestamp(evidence.get("known_at"), "known_at")
            except ValueError:
                evidence_rows = []
            else:
                row["revision_kind"] = "amendment_addition"
                continue
        if len(evidence_rows) == 1 and evidence_rows[0].get("status") == "verified":
            evidence = evidence_rows[0]
            original_id = evidence.get("original_source_row_id")
            original = original_by_id.get(original_id)
            try:
                known_at = _parse_aware_timestamp(evidence.get("known_at"), "known_at")
            except ValueError:
                known_at = None
            if (
                original is not None
                and known_at is not None
                and isinstance(evidence.get("evidence_ref"), str)
                and evidence["evidence_ref"].strip()
                and isinstance(original.get("event_version_id"), str)
                and isinstance(row.get("event_version_id"), str)
            ):
                row["revision_kind"] = "amendment"
                row["linkage_status"] = "verified"
                row["supersedes_version_id"] = original["event_version_id"]
                links.append({
                    "from_event_version_id": original["event_version_id"],
                    "to_event_version_id": row["event_version_id"],
                    "known_at": known_at.isoformat().replace("+00:00", "Z"),
                    "linkage_status": "verified",
                    "evidence_ref": evidence["evidence_ref"].strip(),
                })
                continue

        possible_ids = set()
        for evidence in evidence_rows:
            possible_ids.update(evidence.get("original_source_row_ids") or [])
            if evidence.get("original_source_row_id"):
                possible_ids.add(evidence["original_source_row_id"])
        affected = [original_by_id[item] for item in sorted(possible_ids) if item in original_by_id]
        reason = "ambiguous_revision" if len(affected) > 1 or len(evidence_rows) > 1 else "unresolved_revision"
        for item in [*affected, row]:
            item["linkage_status"] = "unresolved"
            item["aggregation_eligibility"] = False
        unresolved.append({
            "amendment_source_row_id": amendment_id,
            "possible_original_source_row_ids": sorted(possible_ids),
            "reason": reason,
        })
        known_values = []
        for evidence in evidence_rows:
            try:
                known_values.append(_parse_aware_timestamp(evidence.get("known_at"), "known_at"))
            except ValueError:
                continue
        known_at = max(known_values).isoformat().replace("+00:00", "Z") if known_values else None
        for original_id in sorted(possible_ids):
            original = original_by_id.get(original_id)
            if original is not None:
                links.append({
                    "from_event_version_id": original.get("event_version_id"),
                    "to_event_version_id": row.get("event_version_id"),
                    "known_at": known_at,
                    "linkage_status": "unresolved",
                })

    return {"versions": originals + amendments, "links": links, "unresolved": unresolved}
