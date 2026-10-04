"""Fail-closed readers for small, reviewed public research catalogs."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from stock_papi.services.company_events import (
    CompanyEventSchemaError,
    validate_event_catalog,
)
from stock_papi.services.public_opinions import build_catalog


MAX_RESEARCH_BYTES = 1_000_000
ALLOWED_EVENT_HOSTS = frozenset({"openapi.twse.com.tw", "www.tpex.org.tw"})


def _read_json(filename):
    if filename == 'public-opinions.json' and os.getenv('ABSORB_RESEARCH_REFRESH_ENABLED') == 'true':
        from stock_papi.repositories.reviewed_opinions import read_reviewed_catalog
        reviewed = read_reviewed_catalog()
        if reviewed is not None:
            return reviewed
        local = _read_local_json(filename)
        if isinstance(local, dict):
            local['reviewed_refresh_status'] = 'deployment_snapshot'
        return local
    if filename in {'events.json', 'events-status.json', 'public-opinions-status.json'} and os.getenv('ABSORB_RESEARCH_REFRESH_ENABLED') == 'true':
        from stock_papi.repositories.research_refresh import read_public_documents
        documents = read_public_documents()
        if filename in documents:
            return documents[filename]
    return _read_local_json(filename)


def _read_local_json(filename):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "research", filename)
    try:
        if os.path.getsize(path) > MAX_RESEARCH_BYTES:
            return None
        with open(path, "rb") as handle:
            return json.loads(handle.read(MAX_RESEARCH_BYTES + 1).decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def load_events_with_status():
    document = _read_json("events.json")
    if not isinstance(document, dict):
        return [], "unavailable"
    try:
        catalog = validate_event_catalog(document)
        events = catalog['events']
    except CompanyEventSchemaError:
        return [], "unavailable"
    status = _read_json('events-status.json')
    updated = catalog.get('updated_at')
    if isinstance(status, dict) and status.get('status') == 'unavailable' and _has_timezone(status.get('checked_at')):
        if not updated or datetime.fromisoformat(status['checked_at']) >= datetime.fromisoformat(updated):
            return events, 'source_error'
    if events and not any(row.get('symbol') for row in events):
        return events, 'not_covered'
    if not updated or datetime.now(timezone.utc) - datetime.fromisoformat(updated) > timedelta(days=2):
        return events, 'stale'
    return events, ('available' if events else 'empty')


def load_events():
    return load_events_with_status()[0]


def load_opinions():
    document = _read_json("public-opinions.json")
    empty = {"creators": [], "opinions": [], "outcomes": []}
    if not isinstance(document, dict):
        return empty
    if document.get("schema_version") == 2:
        if (
            not isinstance(document.get("creators"), list)
            or not isinstance(document.get("opinions"), list)
            or not isinstance(document.get("outcomes"), list)
        ):
            return empty
        catalog = build_catalog(document)
        catalog['reviewed_refresh_status'] = document.get('reviewed_refresh_status')
        catalog['published_at'] = document.get('published_at') if _has_timezone(document.get('published_at')) else None
        catalog["ingestion"] = {}
        public_status = _read_json('public-opinions-status.json')
        public_metadata = document.get('ingestion') or {}
        if isinstance(public_status, dict) and public_status.get('catalog_version') == catalog['catalog_version']:
            public_metadata = public_status.get('ingestion') or {}
        if not isinstance(public_metadata, dict):
            public_metadata = {}
        for creator in catalog["creators"]:
            public_meta = public_metadata.get(creator.get('id'))
            if (isinstance(public_meta, dict) and _has_timezone(public_meta.get('fetched_at'))
                    and type(public_meta.get('count')) is int and 0 <= public_meta['count'] <= 10000):
                catalog['ingestion'][creator['id']] = {
                    'fetched_at': public_meta['fetched_at'], 'count': public_meta['count'],
                    'has_more': bool(public_meta.get('has_more')), 'provider': 'FxTwitter',
                }
            handle = creator.get("handle", "")
            if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
                continue
            candidate = _read_json(f"x-candidates/{handle}.json")
            if not isinstance(candidate, dict) or candidate.get("catalog_id") != "public-opinions-fxtwitter-candidate":
                continue
            meta = candidate.get("fetch_meta")
            rows = candidate.get("opinions")
            if not isinstance(meta, dict) or meta.get("username") != handle or not isinstance(rows, list):
                continue
            if not _has_timezone(meta.get("fetched_at")) or not all(
                isinstance(row, dict) and row.get("creator_id") == creator["id"]
                and row.get("review_status") == "pending_review" for row in rows
            ):
                continue
            # Candidate text never enters the reviewed catalog or consensus.
            catalog["ingestion"][creator["id"]] = {
                "fetched_at": meta["fetched_at"], "count": len(rows),
                "has_more": bool(meta.get("has_more")), "provider": "FxTwitter",
            }
        return catalog
    if document.get("schema_version") != 1:
        return {"creators": [], "opinions": [], "outcomes": []}
    creators = document.get("creators")
    opinions = document.get("opinions")
    if not isinstance(creators, list) or not isinstance(opinions, list):
        return {"creators": [], "opinions": [], "outcomes": []}
    legacy_creators = _legacy_creators(creators)
    rows = []
    for item in opinions:
        if isinstance(item, dict):
            rows.append(_legacy_opinion(item))
        else:
            rows.append({
                "raw": item,
                "validation_errors": ["not_mapping"],
                "is_confirmed": False,
            })
    for item in rows:
        if "raw" in item and item.get("validation_errors") == ["not_mapping"]:
            continue
        item.setdefault("summary", item.get("text", ""))
        item.setdefault("name", item.get("symbol") or item.get("company_id") or "")
        item.setdefault("source", "")
    return {
        "creators": legacy_creators,
        "opinions": rows,
        "outcomes": [],
    }


def _legacy_creators(creators):
    rows = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        row = dict(creator)
        row.setdefault("identity_status", "legacy_unverified")
        row.setdefault("source_status", "pending_review")
        rows.append(row)
    return rows


def _legacy_opinion(item):
    row = dict(item)
    row["review_status"] = "legacy_unverified"
    row["source_status"] = "pending_review"
    row["is_confirmed"] = False
    missing = [
        key for key in (
            "opinion_id",
            "source_id",
            "market",
            "symbol",
            "security_status",
            "published_at",
            "first_seen_at",
            "reviewed_at",
            "content_type",
            "stance",
            "recommendation_kind",
        )
        if key not in row
    ]
    errors = ["legacy_schema_v1"] + [f"legacy_missing_{key}" for key in missing]
    for key in ("published_at", "first_seen_at", "reviewed_at"):
        if key in row and not _has_timezone(row.get(key)):
            errors.append(f"legacy_{key}_timezone")
    if not _legacy_source_is_allowed(row.get("source")):
        errors.append("invalid_source_url")
    row["validation_errors"] = errors
    return row


def _has_timezone(value):
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _legacy_source_is_allowed(value):
    text = str(value or "")
    return (
        text.startswith("https://www.youtube.com/")
        or text.startswith("https://youtube.com/")
        or text.startswith("https://youtu.be/")
    )
