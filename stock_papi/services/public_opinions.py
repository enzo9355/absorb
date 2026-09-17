"""Public opinion catalog helpers."""

from datetime import date, datetime
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
    return {
        "schema_version": 2,
        "catalog_id": catalog.get("catalog_id") or "public-opinions",
        "catalog_version": catalog_version,
        "creators": creator_rows,
        "coverage": coverage,
        "opinions": opinions,
        "outcomes": outcomes,
        "outcome_errors": outcome_errors,
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
