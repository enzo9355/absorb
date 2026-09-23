"""Public opinion catalog helpers."""

import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit, urlunsplit

from stock_papi.integrations.market_data.tw_security_master import is_taiwan_symbol
from stock_papi.integrations.market_data.us_universe import validate_us_ticker


_DIRECTIONS = {"buy", "sell", "long", "short", "hold"}
_MARKETS = {"TW", "US"}
_CONTENT_TYPES = {
    "original_opinion",
    "news_relay",
    "flow_observation",
    "trade_disclosure",
}
_SOURCE_KINDS = {"x_post", "youtube_video", "official_site", "article", "video"}
_SOURCE_HOSTS = {
    "youtube_video": {"www.youtube.com", "youtube.com", "youtu.be"},
    "official_site": {"unusualwhales.com", "sikandmedia.com", "www.sikandmedia.com"},
    "article": set(),
    "video": {"www.youtube.com", "youtube.com", "youtu.be"},
}
_STANCES = {"bullish", "bearish", "neutral", "unclear"}
_RECOMMENDATION_KINDS = {"explicit", "conditional", "mention"}
_HORIZONS = {"short", "medium", "long", "unspecified"}
_CONDITIONAL_TERMS = ("if", "when", "若", "如果", "跌破", "站上", "除非", "才")
_NEGATIVE_BUY_TERMS = (
    "not buy",
    "do not buy",
    "don't buy",
    "not recommend buying",
    "不建議買",
    "不要買",
    "不買",
)
_NEWS_RELAY_TERMS = ("reuters:", "bloomberg:", "cnbc:", "according to", "報導", "轉貼", "引述")
_FLOW_TERMS = ("options flow", "option flow", "flow:", "call sweep", "put sweep", "資金流", "期權流")
_TRADE_DISCLOSURE_TERMS = ("disclosed", "disclosure", "bought", "sold", "trade", "持倉", "交易揭露")
_LONG_HORIZON_TERMS = ("long-term", "long term", "長期")
_MEDIUM_HORIZON_TERMS = ("medium-term", "medium term", "中期")
_SHORT_HORIZON_TERMS = ("short-term", "short term", "near term", "短期")
_RECOMMENDATION_TERMS = (
    "buy",
    "sell",
    "long",
    "short",
    "買",
    "賣",
    "買進",
    "賣出",
    "做多",
    "做空",
    "加碼",
    "減碼",
    "建議",
)
_OUTCOME_KEYS = ("return_5d", "return_20d", "return_60d", "max_drawdown")
_COVERAGE_STATUSES = {
    "verified",
    "partial",
    "zero_new",
    "failure",
    "pending",
    "pending_review",
    "unavailable",
}


def build_catalog(catalog, candles_by_symbol=None):
    if not isinstance(catalog, dict):
        raise ValueError("catalog must be a mapping")
    if catalog.get("schema_version") == 2:
        return _build_v2_catalog(catalog, candles_by_symbol or {})
    creators = _validate_creators(catalog.get("creators") or [])
    _validate_outcomes(catalog.get("outcomes") or [])
    seen = set()
    opinions = []
    outcomes = []
    for opinion in catalog.get("opinions") or []:
        item = _validate_opinion(opinion, creators)
        _validate_outcome(item.get("outcome") or {})
        key = (item["creator_id"], item["symbol"], item["direction"])
        if key in seen:
            continue
        seen.add(key)
        item["classification"] = classify_opinion(item)
        item["outcome"] = calculate_outcome(
            item,
            (candles_by_symbol or {}).get(item["symbol"]) or [],
        )
        if item["outcome"]:
            outcomes.append({"opinion_id": item["id"], **item["outcome"]})
        opinions.append(item)
    return {
        "creators": list(creators.values()),
        "opinions": opinions,
        "outcomes": outcomes,
    }


def classify_opinion(opinion):
    if opinion.get("content_type") and opinion.get("content_type") != "original_opinion":
        return "mention"
    kind = opinion.get("recommendation_kind")
    if kind == "explicit":
        return "explicit_recommendation"
    if kind == "conditional":
        return "conditional"
    if kind == "mention":
        return "mention"
    text = str(opinion.get("text") or "").lower()
    if any(term in text for term in _CONDITIONAL_TERMS):
        return "conditional"
    if any(term in text for term in _RECOMMENDATION_TERMS):
        return "explicit_recommendation"
    return "mention"


def parse_opinion_markers(opinion):
    text = str((opinion or {}).get("text") or "")
    lower = text.lower()
    supplied_type = str((opinion or {}).get("content_type") or "").strip()
    content_type = supplied_type if supplied_type in _CONTENT_TYPES else _infer_content_type(lower)
    negative = any(term in lower or term in text for term in _NEGATIVE_BUY_TERMS)
    quoted = content_type == "news_relay" or any(term in lower for term in _NEWS_RELAY_TERMS)
    conditional = any(term in lower or term in text for term in _CONDITIONAL_TERMS)
    horizon = _infer_horizon(lower)
    conditions = [text] if conditional else []
    stance = _infer_stance(lower, text, content_type, negative)
    recommendation_kind = _infer_recommendation_kind(lower, text, content_type, conditional, negative)
    parsed = {
        "content_type": content_type,
        "stance": stance,
        "recommendation_kind": recommendation_kind,
        "horizon": horizon,
        "conditions": conditions,
        "negative": negative,
        "quoted": quoted,
    }
    parsed["classification"] = classify_opinion(parsed)
    return parsed


def latest_valid_stances(catalog_or_opinions):
    opinions = (
        catalog_or_opinions.get("opinions") or []
        if isinstance(catalog_or_opinions, dict)
        else catalog_or_opinions
    )
    superseded = {
        item.get("supersedes_id")
        for item in opinions
        if isinstance(item, dict) and item.get("is_confirmed") and item.get("supersedes_id")
    }
    withdrawn = {
        item.get("withdraws_id")
        for item in opinions
        if isinstance(item, dict) and item.get("is_confirmed") and item.get("withdraws_id")
    }
    latest = {}
    for item in opinions:
        if not _is_current_stance_candidate(item, superseded=superseded, withdrawn=withdrawn):
            continue
        key = _stance_key(item)
        current = latest.get(key)
        if current is None or _opinion_sort_key(item) > _opinion_sort_key(current):
            latest[key] = item
    return [latest[key] for key in sorted(latest)]


def _build_v2_catalog(catalog, candles_by_symbol):
    creators, creator_rows = _validate_v2_creators(catalog.get("creators") or [])
    catalog_version = catalog.get("catalog_version") or ""
    coverage_input = catalog["coverage"] if "coverage" in catalog else []
    coverage = _validate_coverage(coverage_input, creators, catalog_version)
    supplied_outcomes, outcome_errors = _collect_outcomes(catalog.get("outcomes") or [])
    seen_sources = set()
    opinions = []
    for opinion in catalog.get("opinions") or []:
        if not isinstance(opinion, dict):
            opinions.append({
                "raw": opinion,
                "validation_errors": ["not_mapping"],
                "is_confirmed": False,
                "classification": "mention",
                "outcome": {},
            })
            continue
        item = _validate_v2_opinion(opinion, creators, seen_sources)
        item["classification"] = classify_opinion(item)
        item["outcome"] = {}
        opinions.append(item)
    selected = _select_v2_outcome_samples(opinions)
    outcomes, association_errors = _associate_v2_outcomes(
        opinions,
        selected,
        supplied_outcomes,
        candles_by_symbol,
    )
    outcome_errors.extend(association_errors)
    _mark_current_effective(opinions)
    subjects_rows, subject_map, subject_errors = _validate_subjects(catalog.get("subjects") or [])
    activities, activity_errors = _validate_activities(catalog.get("activities") or [], subject_map)
    return {
        "schema_version": 2,
        "catalog_id": catalog.get("catalog_id") or "public-opinions",
        "catalog_version": catalog_version,
        "creators": creator_rows,
        "coverage": coverage,
        "opinions": opinions,
        "outcomes": outcomes,
        "outcome_errors": outcome_errors,
        "activity_schema_version": catalog.get("activity_schema_version") or 1,
        "subjects": subjects_rows,
        "subject_errors": subject_errors,
        "activities": activities,
        "activity_errors": activity_errors,
    }


def calculate_outcome(opinion, candles):
    if classify_opinion(opinion) != "explicit_recommendation":
        return {}
    start = _parse_date(opinion["published_at"])
    usable = [
        {"date": _parse_date(candle.get("date")), "close": _float(candle.get("close"))}
        for candle in candles
        if isinstance(candle, dict)
    ]
    usable = [
        candle for candle in usable
        if candle["date"] is not None and candle["close"] is not None
    ]
    usable.sort(key=lambda candle: candle["date"])
    usable = [candle for candle in usable if candle["date"] >= start]
    if len(usable) <= 60:
        return {}
    start_close = usable[0]["close"]
    if start_close <= 0:
        return {}
    prices = [candle["close"] for candle in usable[:61]]
    return {
        "return_5d": _ret(start_close, prices[5]),
        "return_20d": _ret(start_close, prices[20]),
        "return_60d": _ret(start_close, prices[60]),
        "max_drawdown": _max_drawdown(prices),
    }


def _validate_creators(creators):
    result = {}
    for creator in creators:
        creator = creator if isinstance(creator, dict) else {}
        creator_id = str((creator or {}).get("id") or "").strip()
        name = str((creator or {}).get("name") or "").strip()
        if not creator_id or not name:
            raise ValueError("creator requires id and name")
        if creator_id in result:
            raise ValueError(f"duplicate creator: {creator_id}")
        item = {"id": creator_id, "name": name}
        for key in (
            "platform",
            "coverage_since",
            "description",
            "official_url",
            "canonical_profile_url",
            "identity_status",
            "source_status",
            "handle",
        ):
            value = creator.get(key)
            if isinstance(value, str) and value.strip() and len(value) <= 500:
                item[key] = value.strip()
        result[creator_id] = item
    return result


def _validate_v2_creators(creators):
    result = {}
    rows = []
    for creator in creators:
        if not isinstance(creator, dict):
            rows.append({
                "raw": creator,
                "validation_errors": ["not_mapping"],
                "is_valid": False,
            })
            continue
        creator_id = str((creator or {}).get("id") or "").strip()
        name = str((creator or {}).get("name") or "").strip()
        errors = []
        if not creator_id:
            errors.append("missing_id")
        if not name:
            errors.append("missing_name")
        if creator_id and creator_id in result:
            errors.append("duplicate_creator")

        item = {"id": creator_id, "name": name}
        for key in (
            "platform",
            "coverage_since",
            "description",
            "official_url",
            "canonical_profile_url",
            "identity_status",
            "source_status",
            "handle",
        ):
            value = creator.get(key)
            if isinstance(value, str) and value.strip() and len(value) <= 500:
                item[key] = value.strip()
        item["validation_errors"] = errors
        item["is_valid"] = not errors
        rows.append(item)
        if not errors:
            result[creator_id] = item
    return result, rows


def _validate_coverage(coverage, creators, catalog_version):
    if not isinstance(coverage, list):
        return [{
            "raw_coverage": coverage,
            "validation_errors": ["coverage_not_list"],
            "is_current": False,
        }]
    rows = []
    for row in coverage:
        errors = []
        if not isinstance(row, dict):
            rows.append({
                "raw": row,
                "validation_errors": ["not_mapping"],
                "is_current": False,
            })
            continue
        item = dict(row)
        creator_id = str(item.get("creator_id") or "").strip()
        if creator_id not in creators:
            errors.append("unknown_creator")
        for key in (
            "source",
            "reviewed_through",
            "catalog_version",
            "sample_start",
            "sample_end",
            "status",
            "reviewer",
        ):
            if not str(item.get(key) or "").strip():
                errors.append(f"missing_{key}")
        if "gaps" not in item:
            errors.append("missing_gaps")
        if item.get("catalog_version") and item.get("catalog_version") != catalog_version:
            errors.append("catalog_version_mismatch")
        if not _has_timezone(item.get("checked_at")):
            errors.append("checked_at_timezone")
        if item.get("reviewed_through") and not _has_timezone(item.get("reviewed_through")):
            errors.append("reviewed_through_timezone")
        if item.get("sample_start") and _parse_date(item.get("sample_start")) is None:
            errors.append("sample_start_date")
        if item.get("sample_end") and _parse_date(item.get("sample_end")) is None:
            errors.append("sample_end_date")
        if item.get("last_success_at") and not _has_timezone(item.get("last_success_at")):
            errors.append("last_success_at_timezone")
        if "gaps" in item and not isinstance(item.get("gaps"), list):
            errors.append("gaps_list")
        if item.get("status") and item.get("status") not in _COVERAGE_STATUSES:
            errors.append("invalid_status")
        item["validation_errors"] = errors
        item["is_current"] = not errors
        rows.append(item)
    return rows


def _validate_opinion(opinion, creators):
    item = dict(opinion or {})
    for key in ("id", "creator_id", "symbol", "direction", "published_at", "text"):
        if not str(item.get(key) or "").strip():
            raise ValueError(f"opinion requires {key}")
        item[key] = str(item[key]).strip()
    if item["creator_id"] not in creators:
        raise ValueError(f"unknown creator: {item['creator_id']}")
    item["symbol"] = item["symbol"].upper()
    item["direction"] = item["direction"].lower()
    if item["direction"] not in _DIRECTIONS:
        raise ValueError(f"invalid direction: {item['direction']}")
    if _parse_date(item["published_at"]) is None:
        raise ValueError(f"invalid published_at: {item['published_at']}")
    return item


def _validate_v2_opinion(opinion, creators, seen_sources):
    item = dict(opinion or {})
    errors = []
    item["original_source_url"] = str(item.get("source_url") or "").strip()
    for key in (
        "id",
        "creator_id",
        "source_url",
        "source_kind",
        "published_at",
        "first_seen_at",
        "reviewed_at",
        "review_status",
        "source_status",
        "content_type",
        "stance",
        "recommendation_kind",
        "text",
    ):
        item[key] = str(item.get(key) or "").strip()
        if not item[key]:
            errors.append(f"missing_{key}")
    item["opinion_id"] = str(item.get("opinion_id") or "").strip()
    if not item["opinion_id"]:
        errors.append("missing_opinion_id")
    for key in (
        "origin_group_id",
        "continuation_of",
        "withdraws_id",
        "supersedes_id",
        "withdrawn_at",
        "source_platform",
        "acquisition_method",
    ):
        item[key] = str(item.get(key) or "").strip()
    for key in ("origin_group_id", "source_platform", "acquisition_method"):
        if not item[key]:
            errors.append(f"missing_{key}")
    if item.get("creator_id") not in creators:
        errors.append("unknown_creator")
    creator = creators.get(item.get("creator_id")) or {}
    if creator.get("identity_status") != "verified":
        errors.append("creator_identity_unverified")
    source = _normalize_source_url(item.get("source_url"), item.get("source_kind"))
    if source is None:
        errors.append("invalid_source_url")
    else:
        source_id, canonical_url, handle = source
        item["source_id"] = source_id
        item["source_url"] = canonical_url
        creator_handle = str(creator.get("handle") or "").strip().lower()
        if item.get("source_kind") == "x_post" and creator_handle and handle.lower() != creator_handle:
            errors.append("source_handle_mismatch")
        if source_id in seen_sources:
            errors.append("duplicate_source_id")
        seen_sources.add(source_id)
    item["market"] = str(item.get("market") or "").strip().upper()
    item["symbol"] = str(item.get("symbol") or "").strip().upper()
    item["company_id"] = str(item.get("company_id") or "").strip()
    if item["symbol"]:
        if not item["market"]:
            errors.append("unknown_market")
        if not _security_known(item["market"], item["symbol"]):
            errors.append("unknown_security")
    elif item["company_id"]:
        errors.append("unknown_company")
    else:
        errors.append("missing_security_or_company")
    for key in ("published_at", "first_seen_at", "reviewed_at"):
        if not _has_timezone(item.get(key)):
            errors.append(f"{key}_timezone")
    if item.get("review_status") != "confirmed":
        errors.append("not_reviewed")
    if item.get("source_status") != "available":
        errors.append("source_unavailable")
    if item.get("content_type") not in _CONTENT_TYPES:
        errors.append("invalid_content_type")
    if item.get("stance") not in _STANCES:
        errors.append("invalid_stance")
    if item.get("recommendation_kind") not in _RECOMMENDATION_KINDS:
        errors.append("invalid_recommendation_kind")
    parsed = parse_opinion_markers(item)
    item["horizon"] = str(item.get("horizon") or parsed["horizon"]).strip().lower()
    if item["horizon"] not in _HORIZONS:
        errors.append("invalid_horizon")
    conditions = item.get("conditions")
    if isinstance(conditions, list):
        item["conditions"] = [str(value).strip() for value in conditions if str(value).strip()]
    elif isinstance(conditions, str) and conditions.strip():
        item["conditions"] = [conditions.strip()]
    else:
        item["conditions"] = parsed["conditions"]
    if item.get("withdrawn_at") and not _has_timezone(item.get("withdrawn_at")):
        errors.append("withdrawn_at_timezone")
    item["direction"] = str(item.get("direction") or "hold").strip().lower()
    if item["direction"] not in _DIRECTIONS:
        errors.append("invalid_direction")
    item["validation_errors"] = errors
    item["is_confirmed"] = not errors
    return item


def _infer_content_type(lower):
    if any(term in lower for term in _FLOW_TERMS):
        return "flow_observation"
    if any(term in lower for term in _TRADE_DISCLOSURE_TERMS):
        return "trade_disclosure"
    if any(term in lower for term in _NEWS_RELAY_TERMS):
        return "news_relay"
    return "original_opinion"


def _infer_horizon(lower):
    if any(term in lower for term in _LONG_HORIZON_TERMS):
        return "long"
    if any(term in lower for term in _MEDIUM_HORIZON_TERMS):
        return "medium"
    if any(term in lower for term in _SHORT_HORIZON_TERMS):
        return "short"
    return "unspecified"


def _infer_stance(lower, text, content_type, negative):
    if content_type != "original_opinion":
        return "unclear"
    if "neutral" in lower or "中立" in text:
        return "neutral"
    if negative or "bearish" in lower or _has_short_position_signal(lower, text):
        return "bearish"
    if "bullish" in lower or "long" in lower or "看多" in text or "做多" in text:
        return "bullish"
    if "買" in text or "buy" in lower:
        return "bullish"
    if "賣" in text or "sell" in lower:
        return "bearish"
    return "unclear"


def _has_short_position_signal(lower, text):
    return (
        "short position" in lower
        or "shorting" in lower
        or "short the stock" in lower
        or "short nvda" in lower
        or "看空" in text
        or "做空" in text
    )


def _infer_recommendation_kind(lower, text, content_type, conditional, negative):
    if content_type != "original_opinion" or negative:
        return "mention"
    if conditional:
        return "conditional"
    explicit_terms = ("buy", "sell", "買進", "賣出", "加碼", "減碼", "做空")
    if any(term in lower or term in text for term in explicit_terms):
        return "explicit"
    return "mention"


def _should_calculate_v2_outcome(item, outcome_samples):
    if not item.get("is_confirmed"):
        return False
    if item.get("content_type") != "original_opinion":
        return False
    if classify_opinion(item) != "explicit_recommendation":
        return False
    if not item.get("market") or not item.get("symbol"):
        return False
    start = _parse_date(item.get("published_at"))
    if start is None:
        return False
    sampled_chains = outcome_samples.setdefault("_sampled_chains", set())
    chain_ids = {
        str(item.get("opinion_id") or item.get("id") or "").strip(),
        str(item.get("origin_group_id") or "").strip(),
        str(item.get("continuation_of") or "").strip(),
    }
    chain_ids.discard("")
    if sampled_chains.intersection(chain_ids):
        return False
    key = (
        item.get("creator_id"),
        item.get("market"),
        item.get("symbol"),
        item.get("horizon") or "unspecified",
        item.get("direction"),
    )
    starts = outcome_samples.setdefault(key, [])
    if any(0 <= (start - prior).days <= 60 for prior in starts):
        return False
    starts.append(start)
    sampled_chains.update(chain_ids)
    return True


def _select_v2_outcome_samples(opinions):
    outcome_samples = {}
    selected = []
    candidates = [
        item for item in opinions
        if isinstance(item, dict) and "raw" not in item
    ]
    for item in sorted(candidates, key=_opinion_sort_key):
        if _should_calculate_v2_outcome(item, outcome_samples):
            selected.append(item)
    return selected


def _associate_v2_outcomes(opinions, selected, supplied_outcomes, candles_by_symbol):
    opinions_by_id = {
        item.get("opinion_id"): item
        for item in opinions
        if isinstance(item, dict) and item.get("opinion_id")
    }
    selected_by_id = {item.get("opinion_id"): item for item in selected}
    supplied_by_id = {}
    errors = []
    for supplied in supplied_outcomes:
        opinion_id = supplied.get("opinion_id")
        index = supplied.get("__index")
        if opinion_id not in opinions_by_id:
            errors.append({
                "index": index,
                "opinion_id": opinion_id,
                "validation_errors": ["outcome_orphan"],
            })
            continue
        if opinion_id not in selected_by_id:
            errors.append({
                "index": index,
                "opinion_id": opinion_id,
                "validation_errors": ["outcome_not_eligible"],
            })
            continue
        if opinion_id in supplied_by_id:
            errors.append({
                "index": index,
                "opinion_id": opinion_id,
                "validation_errors": ["duplicate_outcome"],
            })
            continue
        supplied_by_id[opinion_id] = {
            key: value for key, value in supplied.items()
            if key not in {"opinion_id", "__index"}
        }

    outcomes = []
    for item in selected:
        opinion_id = item.get("opinion_id")
        supplied = supplied_by_id.get(opinion_id)
        outcome = (
            supplied if supplied is not None
            else calculate_outcome(item, candles_by_symbol.get(item.get("symbol")) or [])
        )
        item["outcome"] = outcome or {}
        if item["outcome"]:
            outcomes.append({"opinion_id": opinion_id, **item["outcome"]})
    return outcomes, errors


def _mark_current_effective(opinions):
    superseded = {
        item.get("supersedes_id")
        for item in opinions
        if isinstance(item, dict) and item.get("is_confirmed") and item.get("supersedes_id")
    }
    withdrawn = {
        item.get("withdraws_id")
        for item in opinions
        if isinstance(item, dict) and item.get("is_confirmed") and item.get("withdraws_id")
    }
    for item in opinions:
        if not isinstance(item, dict):
            continue
        item["is_current_effective"] = _is_current_stance_candidate(
            item,
            superseded=superseded,
            withdrawn=withdrawn,
        )


def _is_current_stance_candidate(item, superseded=None, withdrawn=None):
    if not isinstance(item, dict) or not item.get("is_confirmed"):
        return False
    superseded = superseded or set()
    withdrawn = withdrawn or set()
    opinion_id = item.get("opinion_id") or item.get("id")
    if opinion_id in superseded or opinion_id in withdrawn:
        return False
    if item.get("withdrawn_at") or item.get("withdraws_id"):
        return False
    if item.get("source_status") != "available" or item.get("review_status") != "confirmed":
        return False
    if item.get("content_type") != "original_opinion":
        return False
    if item.get("stance") not in {"bullish", "bearish", "neutral"}:
        return False
    if not item.get("market") or not item.get("symbol"):
        return False
    return True


def _stance_key(item):
    return (
        item.get("creator_id"),
        item.get("market"),
        item.get("symbol"),
        item.get("horizon") or "unspecified",
    )


def _opinion_sort_key(item):
    published = _parse_datetime(item.get("published_at"))
    reviewed = _parse_datetime(item.get("reviewed_at"))
    return (
        published.timestamp() if published else float("-inf"),
        reviewed.timestamp() if reviewed else float("-inf"),
        str(item.get("opinion_id") or item.get("id") or ""),
    )


def _normalize_source_url(value, source_kind):
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not parsed.hostname
    ):
        return None
    if source_kind != "x_post":
        if source_kind not in _SOURCE_KINDS:
            return None
        if parsed.hostname not in _SOURCE_HOSTS.get(source_kind, set()):
            return None
        if source_kind in {"youtube_video", "video"} and "youtube" in parsed.hostname:
            video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
            if video_id:
                canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", f"v={video_id}", ""))
                return (f"{source_kind}:{parsed.hostname}:{video_id}", canonical, "")
        canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
        return (f"{source_kind}:{canonical}", canonical, "")
    if (
        parsed.hostname not in {"x.com", "twitter.com"}
    ):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[1] != "status" or not parts[2].isdigit():
        return None
    handle = parts[0]
    post_id = parts[2]
    return (
        f"x:{post_id}",
        urlunsplit(("https", "x.com", f"/{handle}/status/{post_id}", "", "")),
        handle,
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


def _validate_outcome(outcome):
    for key, value in outcome.items():
        if key not in _OUTCOME_KEYS or _float(value) is None:
            raise ValueError(f"invalid outcome: {key}")


def _validate_outcomes(outcomes):
    if not isinstance(outcomes, list):
        raise ValueError("outcomes must be a list")
    for outcome in outcomes:
        opinion_id = str((outcome or {}).get("opinion_id") or "").strip()
        if not opinion_id:
            raise ValueError("outcome requires opinion_id")
        _validate_outcome({
            key: value for key, value in outcome.items()
            if key != "opinion_id"
        })


def _collect_outcomes(outcomes):
    if not isinstance(outcomes, list):
        return [], [{"index": None, "validation_errors": ["outcomes_not_list"]}]
    valid = []
    errors = []
    for index, outcome in enumerate(outcomes):
        item = dict(outcome or {}) if isinstance(outcome, dict) else {}
        row_errors = []
        opinion_id = str(item.get("opinion_id") or "").strip()
        if not opinion_id:
            row_errors.append("missing_opinion_id")
        for key, value in item.items():
            if key == "opinion_id":
                continue
            if key not in _OUTCOME_KEYS or _float(value) is None:
                row_errors.append(f"invalid_{key}")
        if row_errors:
            errors.append({
                "index": index,
                "opinion_id": opinion_id,
                "validation_errors": row_errors,
            })
        else:
            item["__index"] = index
            valid.append(item)
    return valid, errors


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _parse_datetime(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _has_timezone(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ret(start, end):
    return round((end / start) - 1, 6)


def _max_drawdown(prices):
    peak = prices[0]
    drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        drawdown = min(drawdown, (price / peak) - 1)
    return round(drawdown, 6)


_ACTIVITY_TYPES = {"trade_disclosure", "holding_snapshot", "self_reported_trade"}
_SUBJECT_KINDS = {"person", "household", "institution"}
_ACTIVITY_OWNERS = {"self", "spouse", "joint", "dependent", "unknown"}
_ACTIVITY_INSTRUMENTS = {"common_stock", "option", "other", "unknown"}
_ACTIVITY_ACTIONS = {"purchase", "sale", "exchange", "exercise", "holding", "other"}
_ACTIVITY_SOURCE_KINDS = {"house_ptr", "sec_13f", "x_post", "youtube_video", "official_site", "article", "video"}
_ACTIVITY_HOSTS = {
    "house_ptr": {"ethics.house.gov", "disclosure.house.gov", "clerk.house.gov", "financialdisclosure.house.gov"},
    "sec_13f": {"sec.gov", "www.sec.gov", "efts.sec.gov"},
    "x_post": {"x.com", "twitter.com"},
    "youtube_video": {"www.youtube.com", "youtube.com", "youtu.be"},
    "official_site": {"unusualwhales.com", "sikandmedia.com", "www.sikandmedia.com"},
    "article": {"reuters.com", "www.reuters.com", "bloomberg.com", "www.bloomberg.com",
                "cnbc.com", "www.cnbc.com", "ethics.house.gov", "sec.gov", "www.sec.gov"},
    "video": {"www.youtube.com", "youtube.com", "youtu.be"},
}
_ACTIVITY_RIGHTS = {"approved", "source_only", "pending"}
_ACTIVITY_REVIEW = {"confirmed", "pending_review", "rejected"}
_ACTIVITY_SOURCE_STATUS = {"available", "unavailable"}
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _activity_identity_allowed(url):
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    allowed = set()
    for hosts in _ACTIVITY_HOSTS.values():
        allowed.update(hosts)
    return parsed.hostname.lower() in allowed


def _activity_source_allowed(url, source_kind):
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    hosts = _ACTIVITY_HOSTS.get(source_kind)
    if hosts is None:
        return None
    if parsed.hostname.lower() not in hosts:
        return None
    if source_kind == "x_post":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3 or parts[1] != "status" or not parts[2].isdigit():
            return None
    return True


def _public_upper_bound(public_at, precision):
    try:
        text = str(public_at or "").strip()
        if not text:
            return None
        if precision == "timestamp":
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc)
        if precision == "date":
            date_part = text[:10]
            try:
                day = date.fromisoformat(date_part)
            except ValueError:
                return None
            try:
                full = datetime.fromisoformat(text.replace("Z", "+00:00"))
                tzinfo = full.tzinfo if full.tzinfo is not None else timezone.utc
            except ValueError:
                tzinfo = timezone.utc
            eod = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=tzinfo)
            return eod.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None
    return None


def _finite_number(value):
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    import math
    if not math.isfinite(number):
        return None
    return number


def _validate_subjects(subjects):
    rows = []
    mapping = {}
    errors = []
    seen = set()
    if subjects is None:
        return rows, mapping, errors
    if not isinstance(subjects, list):
        return ([{"raw_subjects": subjects, "validation_errors": ["subjects_not_list"],
                  "is_verified": False}],
                {}, [{"validation_errors": ["subjects_not_list"]}])
    for index, raw in enumerate(subjects or []):
        if not isinstance(raw, dict):
            rows.append({"raw": raw, "validation_errors": ["not_mapping"], "is_verified": False})
            errors.append({"index": index, "validation_errors": ["not_mapping"]})
            continue
        item = dict(raw)
        row_errors = []
        subject_id = str(item.get("subject_id") or "").strip()
        if not subject_id:
            row_errors.append("missing_subject_id")
        elif subject_id in seen:
            row_errors.append("duplicate_subject_id")
        seen.add(subject_id)
        if item.get("subject_kind") not in _SUBJECT_KINDS:
            row_errors.append("invalid_subject_kind")
        if not str(item.get("subject_name") or "").strip():
            row_errors.append("missing_subject_name")
        aliases = item.get("aliases")
        if aliases is None:
            item["aliases"] = []
        elif isinstance(aliases, list) and all(isinstance(v, str) for v in aliases):
            item["aliases"] = [v.strip() for v in aliases if v.strip()][:20]
        else:
            row_errors.append("invalid_aliases")
        if not _activity_identity_allowed(item.get("identity_source_url")):
            row_errors.append("invalid_identity_source_url")
        if item.get("identity_status") != "verified":
            row_errors.append("subject_identity_unverified")
        item["subject_id"] = subject_id
        item["validation_errors"] = row_errors
        item["is_verified"] = not row_errors
        rows.append(item)
        if subject_id and subject_id not in mapping:
            mapping[subject_id] = item
        if row_errors:
            errors.append({"index": index, "subject_id": subject_id, "validation_errors": row_errors})
    return rows, mapping, errors


def validate_activity(row, subjects):
    """回傳原始欄位、validation_errors、is_confirmed、available_at。"""
    item = dict(row or {}) if isinstance(row, dict) else {}
    errors = []
    if not isinstance(row, dict):
        return {"raw": row, "validation_errors": ["not_mapping"], "is_confirmed": False, "available_at": None}
    subjects = subjects if isinstance(subjects, dict) else {}

    activity_id = str(item.get("activity_id") or "").strip()
    if not activity_id:
        errors.append("missing_activity_id")
    elif len(activity_id) > 200:
        errors.append("invalid_activity_id")
    else:
        item["activity_id"] = activity_id

    if item.get("activity_type") not in _ACTIVITY_TYPES:
        errors.append("invalid_activity_type")

    subject_id = str(item.get("subject_id") or "").strip()
    subject = subjects.get(subject_id)
    if not subject_id or subject is None:
        errors.append("unknown_subject")
    elif not subject.get("is_verified"):
        errors.append("subject_identity_unverified")
    else:
        item["subject_id"] = subject_id

    owner = str(item.get("owner") or "").strip()
    if owner not in _ACTIVITY_OWNERS:
        errors.append("invalid_owner")
    else:
        item["owner"] = owner
        owner_name = str(item.get("owner_name") or "").strip()
        if owner in {"self", "spouse", "joint", "dependent"} and not owner_name:
            errors.append("missing_owner_name")
        if len(owner_name) > 200:
            errors.append("invalid_owner_name")

    publisher = str(item.get("publisher_creator_id") or "").strip()
    item["publisher_creator_id"] = publisher

    market = str(item.get("market") or "").strip().upper()
    symbol = str(item.get("symbol") or "").strip().upper()
    security_name = str(item.get("security_name") or "").strip()
    item["market"] = market
    item["symbol"] = symbol
    if market or symbol:
        if market not in {"TW", "US"}:
            errors.append("unknown_market")
        elif symbol and not _security_known(market, symbol):
            errors.append("unknown_security")
        elif not symbol and security_name:
            errors.append("unknown_security")
        elif not symbol and not security_name:
            errors.append("missing_security_or_company")
    elif security_name:
        errors.append("unknown_security")
    else:
        errors.append("missing_security_or_company")

    if item.get("instrument_type") not in _ACTIVITY_INSTRUMENTS:
        errors.append("invalid_instrument_type")
    if item.get("action") not in _ACTIVITY_ACTIONS:
        errors.append("invalid_action")

    activity_type = item.get("activity_type")
    transaction_raw = item.get("transaction_date")
    holdings_raw = item.get("holdings_as_of")
    transaction_date = None
    holdings_as_of = None
    if isinstance(transaction_raw, str) and transaction_raw.strip():
        try:
            transaction_date = date.fromisoformat(transaction_raw.strip()[:10])
            if transaction_raw.strip()[:10] != transaction_date.isoformat():
                raise ValueError("bad date")
        except ValueError:
            errors.append("invalid_transaction_date")
            transaction_date = None
    elif transaction_raw not in (None, ""):
        errors.append("invalid_transaction_date")
    if isinstance(holdings_raw, str) and holdings_raw.strip():
        try:
            holdings_as_of = date.fromisoformat(holdings_raw.strip()[:10])
            if holdings_raw.strip()[:10] != holdings_as_of.isoformat():
                raise ValueError("bad date")
        except ValueError:
            errors.append("invalid_holdings_as_of")
            holdings_as_of = None
    elif holdings_raw not in (None, ""):
        errors.append("invalid_holdings_as_of")

    if activity_type == "holding_snapshot":
        if holdings_as_of is None:
            errors.append("missing_holdings_as_of")
        if transaction_raw not in (None, ""):
            errors.append("transaction_date_for_holding")
        if item.get("action") not in {"holding", "other"}:
            errors.append("invalid_action_for_holding")
    elif activity_type in {"trade_disclosure", "self_reported_trade"}:
        if holdings_raw not in (None, ""):
            errors.append("holdings_as_of_for_trade")

    option_type = str(item.get("option_type") or "").strip().lower()
    strike_raw = item.get("strike")
    expiry_raw = item.get("expiry")
    if item.get("instrument_type") == "common_stock":
        if option_type or strike_raw not in (None, "") or (isinstance(expiry_raw, str) and expiry_raw.strip()):
            errors.append("option_fields_for_equity")
    elif item.get("instrument_type") == "option":
        if option_type and option_type not in {"call", "put"}:
            errors.append("invalid_option_type")
        if strike_raw not in (None, ""):
            if _finite_number(strike_raw) is None or float(strike_raw) <= 0:
                errors.append("invalid_strike")
        if isinstance(expiry_raw, str) and expiry_raw.strip():
            try:
                parsed_expiry = date.fromisoformat(expiry_raw.strip()[:10])
                if expiry_raw.strip()[:10] != parsed_expiry.isoformat():
                    raise ValueError("bad")
            except ValueError:
                errors.append("invalid_expiry")
        elif expiry_raw not in (None, ""):
            errors.append("invalid_expiry")

    public_at = str(item.get("public_at") or "").strip()
    precision = str(item.get("public_time_precision") or "").strip()
    if precision not in {"timestamp", "date"}:
        errors.append("invalid_public_time_precision")
    public_upper = _public_upper_bound(public_at, precision) if precision in {"timestamp", "date"} else None
    if public_upper is None:
        errors.append("invalid_public_at")

    first_seen = None
    reviewed = None
    try:
        first_seen = datetime.fromisoformat(str(item.get("first_seen_at") or "").replace("Z", "+00:00"))
        if first_seen.tzinfo is None or first_seen.utcoffset() is None:
            raise ValueError("naive")
        first_seen = first_seen.astimezone(timezone.utc)
    except (ValueError, TypeError):
        errors.append("first_seen_at_timezone")
    try:
        reviewed = datetime.fromisoformat(str(item.get("reviewed_at") or "").replace("Z", "+00:00"))
        if reviewed.tzinfo is None or reviewed.utcoffset() is None:
            raise ValueError("naive")
        reviewed = reviewed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        errors.append("reviewed_at_timezone")

    available = None
    if public_upper is not None and first_seen is not None and reviewed is not None:
        available = max(public_upper, first_seen, reviewed)
        item["available_at"] = available.isoformat().replace("+00:00", "Z")
        item["public_at_upper_bound"] = public_upper.isoformat().replace("+00:00", "Z")
    else:
        item["available_at"] = None
        errors.append("missing_available_time")

    if public_upper is not None:
        public_day = public_upper.date()
        if transaction_date is not None and transaction_date > public_day:
            errors.append("transaction_after_public")
        if holdings_as_of is not None and holdings_as_of > public_day:
            errors.append("holdings_after_public")

    amount_min_raw = item.get("amount_min")
    amount_max_raw = item.get("amount_max")
    currency = str(item.get("currency") or "").strip().upper()
    has_amount = amount_min_raw not in (None, "") or amount_max_raw not in (None, "")
    amount_min = _finite_number(amount_min_raw) if has_amount and amount_min_raw not in (None, "") else None
    amount_max = _finite_number(amount_max_raw) if has_amount and amount_max_raw not in (None, "") else None
    if has_amount:
        if amount_min_raw not in (None, "") and (amount_min is None or amount_min < 0):
            errors.append("invalid_amount_min")
        if amount_max_raw not in (None, "") and (amount_max is None or amount_max < 0):
            errors.append("invalid_amount_max")
        if not _CURRENCY.match(currency):
            errors.append("invalid_currency")
        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            errors.append("invalid_amount_range")
    elif currency:
        if not _CURRENCY.match(currency):
            errors.append("invalid_currency")

    quantity_raw = item.get("quantity")
    if quantity_raw not in (None, ""):
        quantity = _finite_number(quantity_raw)
        if quantity is None or quantity <= 0:
            errors.append("invalid_quantity")
    reported_raw = item.get("reported_value")
    if reported_raw not in (None, ""):
        if _finite_number(reported_raw) is None:
            errors.append("invalid_reported_value")

    source_kind = str(item.get("source_kind") or "").strip()
    if source_kind not in _ACTIVITY_SOURCE_KINDS:
        errors.append("invalid_source_kind")
    else:
        item["source_kind"] = source_kind
        if not _activity_source_allowed(item.get("source_url"), source_kind):
            errors.append("invalid_source_url")
    if not str(item.get("source_document_id") or "").strip():
        errors.append("missing_source_document_id")
    if not str(item.get("source_locator") or "").strip():
        errors.append("missing_source_locator")
    if not _HEX64.match(str(item.get("source_sha256") or "").strip()):
        errors.append("invalid_source_hash")
    if not str(item.get("reviewer") or "").strip():
        errors.append("missing_reviewer")
    if item.get("rights_status") not in _ACTIVITY_RIGHTS:
        errors.append("invalid_rights_status")
    elif item.get("rights_status") != "approved":
        errors.append("rights_not_approved")
    if item.get("review_status") not in _ACTIVITY_REVIEW:
        errors.append("invalid_review_status")
    elif item.get("review_status") != "confirmed":
        errors.append("not_reviewed")
    if item.get("source_status") not in _ACTIVITY_SOURCE_STATUS:
        errors.append("invalid_source_status")
    elif item.get("source_status") != "available":
        errors.append("source_unavailable")

    if not str(item.get("summary") or "").strip():
        errors.append("missing_summary")
    if not isinstance(item.get("limitations"), str) or not item.get("limitations").strip():
        errors.append("missing_limitations")

    item["validation_errors"] = errors
    item["is_confirmed"] = not errors
    return item


def _validate_activities(rows, subject_map):
    validated = []
    errors = []
    seen_ids = set()
    if rows is None:
        return validated, errors
    if not isinstance(rows, list):
        return ([{"raw": rows, "validation_errors": ["activities_not_list"],
                  "is_confirmed": False, "available_at": None}],
                [{"validation_errors": ["activities_not_list"]}])
    for index, raw in enumerate(rows or []):
        if not isinstance(raw, dict):
            validated.append({"raw": raw, "validation_errors": ["not_mapping"],
                              "is_confirmed": False, "available_at": None})
            errors.append({"index": index, "validation_errors": ["not_mapping"]})
            continue
        item = validate_activity(raw, subject_map)
        activity_id = str(item.get("activity_id") or "")
        if activity_id:
            if activity_id in seen_ids:
                item["validation_errors"] = list(item.get("validation_errors") or []) + ["duplicate_activity_id"]
                item["is_confirmed"] = False
            else:
                seen_ids.add(activity_id)
        if item.get("validation_errors"):
            errors.append({"index": index, "activity_id": item.get("activity_id"),
                           "validation_errors": list(item["validation_errors"])})
        validated.append(item)
    return validated, errors


def query_activities(catalog, *, subject_id, market, symbol, cutoff_at, window_days):
    """只回傳截止當時已可用的核對活動，依公開時間倒序。"""
    if not isinstance(catalog, dict):
        raise ValueError("catalog must be a mapping")
    if not isinstance(cutoff_at, datetime) or cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    if window_days is not None and (not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 0):
        raise ValueError("invalid window_days")
    cutoff_utc = cutoff_at.astimezone(timezone.utc)
    market_filter = str(market).strip().upper() if market not in (None, "") else None
    symbol_filter = str(symbol).strip().upper() if symbol not in (None, "") else None
    subject_filter = str(subject_id).strip() if subject_id not in (None, "") else None

    candidates = []
    for item in catalog.get("activities") or []:
        if not isinstance(item, dict) or not item.get("is_confirmed"):
            continue
        available = _parse_datetime(item.get("available_at"))
        if available is None:
            continue
        available_utc = available.astimezone(timezone.utc)
        if available_utc > cutoff_utc:
            continue
        public_upper = _public_upper_bound(item.get("public_at"), item.get("public_time_precision"))
        if public_upper is None:
            continue
        if subject_filter is not None and str(item.get("subject_id") or "").strip() != subject_filter:
            continue
        if market_filter is not None and str(item.get("market") or "").strip().upper() != market_filter:
            continue
        if symbol_filter is not None and str(item.get("symbol") or "").strip().upper() != symbol_filter:
            continue
        if window_days is not None:
            from datetime import timedelta as _td
            window_start = cutoff_utc - _td(days=window_days)
            if public_upper < window_start or public_upper > cutoff_utc:
                continue
        candidates.append((public_upper, str(item.get("activity_id") or ""), item))

    blocked = set()
    for item in catalog.get("activities") or []:
        if not isinstance(item, dict) or not item.get("is_confirmed"):
            continue
        available = _parse_datetime(item.get("available_at"))
        if available is None or available.astimezone(timezone.utc) > cutoff_utc:
            continue
        for key in ("supersedes_id", "withdraws_id"):
            target = str(item.get(key) or "").strip()
            if target:
                blocked.add(target)

    deduped = {}
    for public_upper, activity_id, item in candidates:
        if activity_id in blocked:
            continue
        if activity_id and activity_id not in deduped:
            deduped[activity_id] = (public_upper, item)
        elif not activity_id:
            deduped.setdefault(id(item), (public_upper, item))

    ordered = sorted(deduped.values(), key=lambda pair: (pair[0].timestamp(), str(pair[1].get("activity_id") or "")), reverse=True)
    # Reverse secondary ordering: public desc, id asc. Python stable sort in two passes.
    ordered = sorted(deduped.values(), key=lambda pair: str(pair[1].get("activity_id") or ""))
    ordered = sorted(ordered, key=lambda pair: pair[0].timestamp(), reverse=True)
    return [item for _, item in ordered]
