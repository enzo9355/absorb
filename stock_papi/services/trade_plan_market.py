"""Verified-snapshot adapter from published quant artifacts to trade plans.

Read-only: extends the existing quant reader to expose its real artifact
digest; never fetches live vendor data and never re-hashes arbitrary inputs
as "verified". Corporate-action basis is the published vendor series as-is;
no split adjustment is claimed (see BASIS_LIMITATION).
"""

import datetime

from stock_papi.services.trade_plans import build_trade_plan

BASIS_LIMITATION = (
    "價格序列為已發布 vendor 序列原樣，未聲明拆股調整；"
    "已知公司行動使凍結價位不可比時暫停並重建計畫，不改寫原計畫。"
)


class PlanUnavailable(ValueError):
    pass


def us_sessions_from_documents(documents, *, start, end):
    """Weekday sessions minus exchange holidays between start/end (inclusive).

    Early-close days count as sessions (daily bars exist). Years missing from
    the calendar documents yield no sessions there, which fails closed
    downstream (insufficient) instead of falling back to weekdays.
    """
    closed = set()
    for document in documents or []:
        if not isinstance(document, dict):
            continue
        for key in ("closed_dates",):
            dates = document.get(key)
            if isinstance(dates, list):
                closed.update(str(value)[:10] for value in dates if str(value)[:10])
    sessions = []
    day = datetime.date.fromisoformat(start[:10])
    stop = datetime.date.fromisoformat(end[:10])
    while day <= stop:
        text = day.isoformat()
        if day.weekday() < 5 and text not in closed:
            sessions.append(text)
        day += datetime.timedelta(days=1)
    return sessions


def snapshot_from_artifact(document, digest):
    """Map a verified US quant artifact to a trade-plan snapshot dict."""
    if not isinstance(document, dict):
        raise PlanUnavailable("no verified snapshot")
    if document.get("market") != "US":
        raise PlanUnavailable("unsupported_market")
    if document.get("observation_kind") != "regular_price":
        raise PlanUnavailable("unsupported_observation_kind")
    symbol = str(document.get("symbol") or "").strip().upper()
    if not symbol:
        raise PlanUnavailable("missing_symbol")
    as_of = str(document.get("as_of") or "").strip()[:10]
    try:
        datetime.date.fromisoformat(as_of)
    except ValueError:
        raise PlanUnavailable("invalid_as_of") from None
    rows = document.get("daily")
    if not isinstance(rows, list) or len(rows) < 61:
        raise PlanUnavailable("insufficient_history")
    daily = []
    for row in rows:
        if not isinstance(row, dict):
            raise PlanUnavailable("invalid_daily_row")
        day = str(row.get("Date") or "").strip()[:10]
        try:
            datetime.date.fromisoformat(day)
        except ValueError:
            raise PlanUnavailable("invalid_daily_date") from None
        daily.append({
            "date": day,
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "volume": row.get("Volume"),
        })
    return {
        "market": "US",
        "symbol": symbol,
        "instrument_type": "common_stock",
        "observation_kind": "regular_price",
        "source_snapshot_sha256": digest,
        "source_ref": {"label": "verified_quant_artifact",
                       "artifact_as_of": as_of},
        "as_of": as_of,
        "daily": daily,
        "corporate_action_status": "ok",
        "corporate_action_basis": BASIS_LIMITATION,
    }


def build_us_plan(symbol, evidence_ids, *, fetch_artifact, calendar_documents, now):
    """Build a trade plan from the latest verified US artifact. Fail-closed."""
    from stock_papi.integrations.market_data.us_universe import validate_us_ticker
    symbol = str(symbol or "").strip().upper()
    try:
        validate_us_ticker(symbol)
    except ValueError:
        raise PlanUnavailable("unknown_security") from None
    loaded = fetch_artifact(symbol)
    if not loaded or not isinstance(loaded, (tuple, list)) or len(loaded) != 2:
        raise PlanUnavailable("no verified snapshot")
    document, digest = loaded
    if not isinstance(digest, str) or not digest:
        raise PlanUnavailable("unverified_snapshot")
    as_of = str((document or {}).get("as_of") or "")[:10]
    sessions = us_sessions_from_documents(
        calendar_documents, start="2020-01-01", end=as_of) if as_of else []
    # Keep a bounded trailing window plus headroom for expiry math.
    sessions = [session for session in sessions if session <= as_of][-100:]
    if len(sessions) < 66:
        raise PlanUnavailable("insufficient_calendar_history")
    snapshot = snapshot_from_artifact(document, digest)
    calendar = {"sessions": sessions}
    plan = build_trade_plan(
        snapshot, expected_session=snapshot["as_of"],
        generated_at=now, calendar=calendar,
        evidence_ids=tuple(evidence_ids or ()))
    if plan.get("action") == "insufficient":
        raise PlanUnavailable(str((plan.get("conditions") or {}).get("reason") or "insufficient"))
    return plan
