"""Pure consensus helpers for validated public opinion catalogs."""

from datetime import datetime, timedelta, timezone

from stock_papi.integrations.market_data.tw_security_master import is_taiwan_symbol
from stock_papi.integrations.market_data.us_universe import validate_us_ticker


METHOD_VERSION = "opinion-consensus-v2"
_WINDOWS = {1, 7, 28}
_MARKETS = {"TW", "US"}
_HORIZONS = ("short", "medium", "long", "unspecified")
_COUNT_KEYS = (
    "bullish",
    "bearish",
    "neutral",
    "unclear",
    "conditional",
    "news",
    "flow",
    "trade",
)


def build_consensus(catalog, *, market, symbol, window_days, cutoff_at):
    _validate_inputs(catalog, market, symbol, window_days, cutoff_at)
    market = str(market).strip().upper()
    symbol = str(symbol).strip().upper()
    cutoff_utc = cutoff_at.astimezone(timezone.utc)
    window_start = cutoff_utc - timedelta(days=window_days)

    rows = [
        _row(item, cutoff_utc, window_start)
        for item in catalog["opinions"]
        if isinstance(item, dict)
        and item.get("market") == market
        and item.get("symbol") == symbol
    ]
    rows = [item for item in rows if item is not None]

    blocked_ids = _blocked_ids(rows, cutoff_utc)
    latest = _latest_stances(rows, blocked_ids)
    period = [
        item for item in rows
        if item["in_window"] and item["cutoff_eligible"]
    ]
    counted = [
        item for item in period
        if item.get("content_type") != "original_opinion" and _countable(item, blocked_ids)
    ]
    # One current stance per creator/security/horizon; the timeline keeps every post.
    counted.extend(item for item in latest if item["in_window"])

    return {
        "market": market,
        "symbol": symbol,
        "catalog_version": catalog.get("catalog_version"),
        "method_version": METHOD_VERSION,
        "window_start": window_start.isoformat().replace("+00:00", "Z"),
        "cutoff_at": cutoff_utc.isoformat().replace("+00:00", "Z"),
        "latest_stances": [_public_row(item) for item in latest],
        "period_activity": [_public_row(item) for item in period],
        "counts_by_horizon": _counts_by_horizon(counted),
        "origin_groups": _origin_groups(period),
        "coverage": _coverage(catalog.get("coverage") or []),
        "evidence_ids": _evidence_ids(period, latest),
    }


def _validate_inputs(catalog, market, symbol, window_days, cutoff_at):
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 2:
        raise ValueError("catalog must be a validated v2 dict")
    if not isinstance(catalog.get("opinions"), list):
        raise ValueError("catalog requires opinions")
    if not isinstance(catalog.get("coverage"), list):
        raise ValueError("catalog requires coverage")
    if not str(catalog.get("catalog_version") or "").strip():
        raise ValueError("catalog requires catalog_version")
    market = str(market or "").strip().upper()
    symbol = str(symbol or "").strip().upper()
    if market not in _MARKETS:
        raise ValueError("invalid market")
    if not symbol:
        raise ValueError("invalid symbol")
    if window_days not in _WINDOWS:
        raise ValueError("invalid window_days")
    if not isinstance(cutoff_at, datetime) or cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    if not _security_known(market, symbol):
        raise ValueError("unknown security")


def _row(item, cutoff_utc, window_start):
    published = _aware_utc(item.get("published_at"))
    first_seen = _aware_utc(item.get("first_seen_at"))
    reviewed = _aware_utc(item.get("reviewed_at"))
    if published is None or first_seen is None or reviewed is None:
        return None
    cutoff_eligible = (
        item.get("is_confirmed") is True
        and item.get("review_status") == "confirmed"
        and item.get("source_status") == "available"
        and published <= cutoff_utc
        and first_seen <= cutoff_utc
        and reviewed <= cutoff_utc
    )
    row = dict(item)
    row["_published_at"] = published
    row["_first_seen_at"] = first_seen
    row["_reviewed_at"] = reviewed
    row["cutoff_eligible"] = cutoff_eligible
    row["in_window"] = cutoff_eligible and window_start <= published <= cutoff_utc
    row["outside_window"] = cutoff_eligible and published < window_start
    row["category"] = _category(row)
    row["horizon"] = row.get("horizon") or "unspecified"
    return row


def _blocked_ids(rows, cutoff_utc):
    blocked = set()
    for item in rows:
        if not item["cutoff_eligible"]:
            continue
        if item.get("supersedes_id"):
            blocked.add(item["supersedes_id"])
        if item.get("withdraws_id"):
            blocked.add(item["withdraws_id"])
        withdrawn_at = _aware_utc(item.get("withdrawn_at"))
        if withdrawn_at is not None and withdrawn_at <= cutoff_utc:
            blocked.add(item.get("opinion_id"))
    return blocked


def _latest_stances(rows, blocked_ids):
    latest = {}
    for item in rows:
        if not _latest_eligible(item):
            continue
        key = (
            item.get("creator_id"),
            item.get("market"),
            item.get("symbol"),
            item.get("horizon") or "unspecified",
        )
        current = latest.get(key)
        if current is None or _sort_key(item) > _sort_key(current):
            latest[key] = item
    # Select before excluding withdrawals, so an older stance cannot reappear.
    return [latest[key] for key in sorted(latest)
            if latest[key].get("opinion_id") not in blocked_ids]


def _latest_eligible(item):
    if not item["cutoff_eligible"]:
        return False
    if item.get("withdraws_id") or item.get("continuation_of"):
        return False
    if item.get("content_type") != "original_opinion":
        return False
    if item.get("stance") not in {"bullish", "bearish", "neutral", "unclear"}:
        return False
    return True


def _countable(item, blocked_ids):
    if item.get("opinion_id") in blocked_ids:
        return False
    if item.get("withdraws_id") or item.get("continuation_of"):
        return False
    return item.get("content_type") in {
        "original_opinion",
        "news_relay",
        "flow_observation",
        "trade_disclosure",
    }


def _counts_by_horizon(rows):
    result = {horizon: _empty_count() for horizon in _HORIZONS}
    for item in rows:
        horizon = item.get("horizon") or "unspecified"
        if horizon not in result:
            result[horizon] = _empty_count()
        result[horizon][item["category"]] += 1
        if (
            item.get("content_type") == "original_opinion"
            and item.get("recommendation_kind") == "explicit"
            and item.get("stance") in {"bullish", "bearish"}
        ):
            result[horizon]["explicit_direction_denominator"] += 1
            result[horizon]["explicit_" + item["stance"]] += 1
    for count in result.values():
        denom = count["explicit_direction_denominator"]
        count["bullish_ratio"] = None if denom < 2 else round(count["explicit_bullish"] / denom, 6)
        count["bearish_ratio"] = None if denom < 2 else round(count["explicit_bearish"] / denom, 6)
        count["status"] = "insufficient" if denom < 2 else "ready"
    return result


def _empty_count():
    count = {key: 0 for key in _COUNT_KEYS}
    count["explicit_direction_denominator"] = 0
    count["explicit_bullish"] = 0
    count["explicit_bearish"] = 0
    count["bullish_ratio"] = None
    count["bearish_ratio"] = None
    count["status"] = "insufficient"
    return count


def _origin_groups(rows):
    groups = {}
    for item in rows:
        origin_group_id = item.get("origin_group_id") or item.get("opinion_id")
        group = groups.setdefault(origin_group_id, {
            "origin_group_id": origin_group_id,
            "activity_count": 0,
            "independent_group_count": 1,
            "creator_ids": set(),
            "opinion_ids": [],
        })
        group["activity_count"] += 1
        group["creator_ids"].add(item.get("creator_id"))
        group["opinion_ids"].append(item.get("opinion_id"))
    return {
        key: {
            **value,
            "creator_ids": sorted(value["creator_ids"]),
        }
        for key, value in sorted(groups.items())
    }


def _coverage(rows):
    coverage = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        creator_id = row.get("creator_id")
        if not creator_id:
            continue
        coverage[creator_id] = {
            "creator_id": creator_id,
            "source": row.get("source"),
            "status": row.get("status"),
            "reviewed_through": row.get("reviewed_through"),
            "gaps": row.get("gaps") if isinstance(row.get("gaps"), list) else [],
        }
    return coverage


def _public_row(item):
    return {
        "creator_id": item.get("creator_id"),
        "opinion_id": item.get("opinion_id"),
        "source_url": item.get("source_url"),
        "origin_group_id": item.get("origin_group_id"),
        "content_type": item.get("content_type"),
        "stance": item.get("stance"),
        "recommendation_kind": item.get("recommendation_kind"),
        "horizon": item.get("horizon") or "unspecified",
        "published_at": item.get("published_at"),
        "outside_window": bool(item.get("outside_window")),
        "category": item.get("category"),
    }


def _evidence_ids(period, latest):
    seen = set()
    evidence = []
    for item in list(period) + list(latest):
        opinion_id = item.get("opinion_id")
        if opinion_id and opinion_id not in seen:
            seen.add(opinion_id)
            evidence.append(opinion_id)
    return evidence


def _category(item):
    content_type = item.get("content_type")
    if content_type == "news_relay":
        return "news"
    if content_type == "flow_observation":
        return "flow"
    if content_type == "trade_disclosure":
        return "trade"
    if item.get("recommendation_kind") == "conditional":
        return "conditional"
    stance = item.get("stance")
    return stance if stance in {"bullish", "bearish", "neutral"} else "unclear"


def _aware_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sort_key(item):
    return (
        item["_published_at"].timestamp(),
        item["_reviewed_at"].timestamp(),
        str(item.get("opinion_id") or ""),
    )


def _security_known(market, symbol):
    if market == "TW":
        return is_taiwan_symbol(symbol)
    if market == "US":
        try:
            validate_us_ticker(symbol)
        except ValueError:
            return False
        return True
    return False
