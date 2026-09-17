"""Validated company-event facts and the small date windows used by the UI."""

from __future__ import annotations

import copy
import datetime as dt
import re
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
MAX_EVENTS = 1_000
ALLOWED_EVENT_HOSTS = frozenset(
    {
        "openapi.twse.com.tw",
        "www.tpex.org.tw",
        "mops.twse.com.tw",
        "mops.tpex.org.tw",
    }
)
EVENT_STATUSES = frozenset(
    {"confirmed", "corrected", "cancelled", "pending_review", "source_snapshot"}
)
SOURCE_STATUSES = frozenset({"available", "unavailable"})


class CompanyEventError(ValueError):
    """Base error for company-event data."""


class CompanyEventSchemaError(CompanyEventError):
    """Event data failed a trust-boundary validation."""


def _text(value, label, limit=500, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit:
        raise CompanyEventSchemaError(f"{label} is invalid")
    value = value.strip()
    if not allow_empty and not value:
        raise CompanyEventSchemaError(f"{label} is invalid")
    if any(ord(char) < 32 for char in value):
        raise CompanyEventSchemaError(f"{label} is invalid")
    return value


def _id(value, label):
    value = _text(value, label, 120)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", value) is None:
        raise CompanyEventSchemaError(f"{label} is invalid")
    return value


def _date(value, label, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise CompanyEventSchemaError(f"{label} is invalid")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CompanyEventSchemaError(f"{label} is invalid") from exc
    if parsed.isoformat() != value:
        raise CompanyEventSchemaError(f"{label} is invalid")
    return value


def _datetime(value, label, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise CompanyEventSchemaError(f"{label} is invalid")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise CompanyEventSchemaError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CompanyEventSchemaError(f"{label} must include timezone")
    return value


def is_allowed_source_url(value):
    """Allow only HTTPS URLs on known official market-data hosts."""
    if not isinstance(value, str) or len(value) > 2_048:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() == "https"
        and parsed.hostname
        and parsed.hostname.lower() in ALLOWED_EVENT_HOSTS
        and not parsed.username
        and not parsed.password
        and parsed.port is None
        and not parsed.fragment
        and parsed.path not in {"", "/"}
    )


def _symbol(value):
    value = _text(value, "event symbol", 20, allow_empty=True).upper()
    if value and re.fullmatch(r"[A-Z0-9.^_-]{1,20}", value) is None:
        raise CompanyEventSchemaError("event symbol is invalid")
    return value


def _event(item):
    required = {
        "id", "source_id", "symbol", "name", "market", "event_type", "title",
        "summary", "published_at", "effective_at", "period_start", "period_end",
        "source", "source_title", "source_publisher", "source_locator",
        "source_checked_at", "source_status", "status", "correction_of",
    }
    if not isinstance(item, dict) or not required <= set(item):
        raise CompanyEventSchemaError("event schema is invalid")
    if set(item) - required:
        raise CompanyEventSchemaError("event contains unknown fields")
    event = {
        "id": _id(item["id"], "event id"),
        "source_id": _id(item["source_id"], "event source id"),
        "symbol": _symbol(item["symbol"]),
        "name": _text(item["name"], "event name", 160),
        "market": _text(item["market"], "event market", 8),
        "event_type": _text(item["event_type"], "event type", 80),
        "title": _text(item["title"], "event title", 300),
        "summary": _text(item["summary"], "event summary", 1_000),
        "published_at": _datetime(item["published_at"], "event published_at", required=True),
        "effective_at": _datetime(item["effective_at"], "event effective_at"),
        "period_start": _date(item["period_start"], "event period_start"),
        "period_end": _date(item["period_end"], "event period_end"),
        "source": _text(item["source"], "event source", 2_048),
        "source_title": _text(item["source_title"], "source title", 300),
        "source_publisher": _text(item["source_publisher"], "source publisher", 160),
        "source_locator": _text(item["source_locator"], "source locator", 300),
        "source_checked_at": _datetime(
            item["source_checked_at"], "source checked_at", required=True
        ),
        "source_status": item["source_status"],
        "status": item["status"],
        "correction_of": item["correction_of"],
    }
    if not is_allowed_source_url(event["source"]):
        raise CompanyEventSchemaError("event source is not allowlisted")
    if event["market"] not in {"TW", "US"}:
        raise CompanyEventSchemaError("event market is invalid")
    if event["source_status"] not in SOURCE_STATUSES:
        raise CompanyEventSchemaError("event source status is invalid")
    if event["status"] not in EVENT_STATUSES:
        raise CompanyEventSchemaError("event status is invalid")
    correction_of = event["correction_of"]
    if correction_of is not None:
        event["correction_of"] = _id(correction_of, "event correction_of")
        if event["correction_of"] == event["source_id"]:
            raise CompanyEventSchemaError("event correction_of is self-referential")
    if (
        event["period_start"]
        and event["period_end"]
        and event["period_end"] < event["period_start"]
    ):
        raise CompanyEventSchemaError("event period is invalid")
    return event


def validate_event_catalog(document):
    """Validate and detach a versioned event catalog.

    Repeated source IDs represent the same announcement on a rerun. The first
    validated copy is retained; a correction uses a new source ID and points
    back to the original source ID.
    """
    required = {"schema_version", "catalog_id", "events"}
    optional = {"updated_at", "coverage_note"}
    if (
        not isinstance(document, dict)
        or not required <= set(document)
        or set(document) - required - optional
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise CompanyEventSchemaError("event catalog schema is invalid")
    catalog_id = _id(document["catalog_id"], "catalog id")
    if "updated_at" in document:
        updated_at = _datetime(document["updated_at"], "catalog updated_at", required=True)
    else:
        updated_at = None
    coverage_note = (
        _text(document["coverage_note"], "catalog coverage_note", 1_000)
        if "coverage_note" in document
        else None
    )
    raw_events = document["events"]
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise CompanyEventSchemaError("event catalog size is invalid")
    events = []
    source_ids = set()
    event_ids = set()
    for raw in raw_events:
        event = _event(raw)
        if event["source_id"] in source_ids:
            continue
        if event["id"] in event_ids:
            raise CompanyEventSchemaError("duplicate event id")
        source_ids.add(event["source_id"])
        event_ids.add(event["id"])
        events.append(event)
    known_sources = {event["source_id"] for event in events}
    for event in events:
        correction_of = event["correction_of"]
        if correction_of is not None and correction_of not in known_sources:
            raise CompanyEventSchemaError("event correction target is unknown")
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": catalog_id,
        "updated_at": updated_at,
        "coverage_note": coverage_note,
        "events": events,
    }


def _effective_date(event):
    value = event.get("effective_at") if isinstance(event, dict) else None
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


def _as_date(value):
    if value is None:
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise CompanyEventSchemaError("window as_of is invalid") from exc
    raise CompanyEventSchemaError("window as_of is invalid")


def split_event_window(events, *, as_of=None, past_days=30, future_days=14):
    """Split explicit-date events into the bounded public timeline windows."""
    if not isinstance(events, list):
        raise CompanyEventSchemaError("events must be a list")
    if (
        isinstance(past_days, bool)
        or isinstance(future_days, bool)
        or not isinstance(past_days, int)
        or not isinstance(future_days, int)
        or past_days < 0
        or future_days < 0
    ):
        raise CompanyEventSchemaError("event window is invalid")
    target = _as_date(as_of)
    lower = target - dt.timedelta(days=past_days)
    upper = target + dt.timedelta(days=future_days)
    past, upcoming, undated = [], [], []
    for item in events:
        if not isinstance(item, dict):
            raise CompanyEventSchemaError("event item is invalid")
        event_date = _effective_date(item)
        if event_date is None:
            undated.append(copy.deepcopy(item))
        elif lower <= event_date <= target:
            past.append(copy.deepcopy(item))
        elif target < event_date <= upper:
            upcoming.append(copy.deepcopy(item))
    past.sort(key=lambda item: item.get("effective_at") or "", reverse=True)
    upcoming.sort(key=lambda item: item.get("effective_at") or "")
    return {
        "as_of": target.isoformat(),
        "past_start": lower.isoformat(),
        "future_end": upper.isoformat(),
        "past": past,
        "upcoming": upcoming,
        "undated": undated,
    }


def build_watchlist_summary(
    watchlist,
    events,
    *,
    observation_for=None,
    as_of=None,
    past_days=30,
    future_days=14,
    event_status="available",
):
    """Build private watchlist sections while preserving every watched symbol."""
    if not isinstance(watchlist, list):
        raise CompanyEventSchemaError("watchlist must be a list")
    window = split_event_window(
        events, as_of=as_of, past_days=past_days, future_days=future_days
    )
    by_symbol = {}
    for event in events:
        if isinstance(event, dict) and event.get("symbol"):
            by_symbol.setdefault(event["symbol"].upper(), []).append(event)
    rows = []
    seen = set()
    has_company_events = any(
        isinstance(event, dict) and str(event.get("symbol") or "").strip()
        for event in events
    )
    for item in watchlist:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        name = item.get("name")
        if not isinstance(code, str) or not code or code.upper() in seen:
            continue
        code = code.upper()
        seen.add(code)
        observation = None
        if callable(observation_for):
            try:
                candidate = observation_for(code)
                if isinstance(candidate, dict):
                    observation = copy.deepcopy(candidate)
            except Exception:
                observation = None
        matched = [copy.deepcopy(event) for event in by_symbol.get(code, [])]
        row_window = split_event_window(
            matched, as_of=window["as_of"], past_days=past_days, future_days=future_days
        )
        new_events = [
            event for event in row_window["past"]
            if _effective_date(event) == dt.date.fromisoformat(window["as_of"])
        ]
        risk_events = observation.get("risk_events") if observation else []
        if not isinstance(risk_events, list):
            risk_events = []
        changed = bool(new_events or risk_events or (observation and observation.get("change_pct") is not None))
        row_event_status = event_status
        if event_status == "available" and not matched and not has_company_events:
            row_event_status = "not_covered"
        rows.append(
            {
                "code": code,
                "name": name if isinstance(name, str) else code,
                "observation": observation,
                "events": matched,
                "new_events": new_events,
                "upcoming_events": row_window["upcoming"],
                "changed": changed,
                "event_status": row_event_status,
            }
        )
    new_events = [event for row in rows for event in row["new_events"]]
    upcoming_events = [event for row in rows for event in row["upcoming_events"]]
    changed = [row for row in rows if row["changed"]]
    return {
        "status": event_status,
        "as_of": window["as_of"],
        "past_start": window["past_start"],
        "future_end": window["future_end"],
        "changed": changed,
        "new_events": new_events,
        "upcoming_events": upcoming_events,
        "all": rows,
    }


__all__ = [
    "ALLOWED_EVENT_HOSTS",
    "CompanyEventError",
    "CompanyEventSchemaError",
    "EVENT_STATUSES",
    "MAX_EVENTS",
    "SOURCE_STATUSES",
    "build_watchlist_summary",
    "is_allowed_source_url",
    "split_event_window",
    "validate_event_catalog",
]
