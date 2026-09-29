"""Traceable facts and fixed descriptive wording; no model-generated prose."""

import hashlib
import json


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_facts(features, events):
    if isinstance(events, dict):
        events = events.get("events")
    if not isinstance(features, (list, tuple)) or not isinstance(events, (list, tuple)):
        raise ValueError("features and events must be sequences")
    versions = {
        row.get("event_version_id")
        for row in events
        if isinstance(row, dict) and isinstance(row.get("event_version_id"), str)
    }
    facts = []
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("feature must be a mapping")
        source_ids = feature.get("source_event_version_ids")
        if not isinstance(source_ids, list) or any(not isinstance(item, str) for item in source_ids):
            raise ValueError("feature source_event_version_ids must be a string list")
        if set(source_ids) - versions:
            raise ValueError("feature references an unknown event version")
        fact = {**feature, "fact_schema_version": 1}
        fact["fact_id"] = hashlib.sha256(_json_bytes(fact)).hexdigest()
        facts.append(fact)
    return facts


def _fact_text(fact, label):
    if not isinstance(fact, dict) or fact.get("status") != "available":
        return f"來源核對不完整，未提供完整{label}筆數。"
    value = fact.get("value")
    if type(value) is not int or value < 0:
        return f"目前沒有可用的{label}筆數。"
    if value == 0:
        return f"近 30 日未觀察到符合條件的申報{label}揭露。"
    return f"近 30 日共有 {value} 筆申報{label}揭露。"


def render_summary(facts, rule_version, template_version):
    if not isinstance(facts, (list, tuple)) or any(not isinstance(row, dict) for row in facts):
        raise ValueError("facts must be a sequence of mappings")
    if any(not isinstance(value, str) or not value.strip() for value in (rule_version, template_version)):
        raise ValueError("rule_version and template_version are required")
    by_name = {}
    for fact in facts:
        fact_id = fact.get("fact_id")
        payload = {key: value for key, value in fact.items() if key != "fact_id"}
        if (
            not isinstance(fact_id, str)
            or hashlib.sha256(_json_bytes(payload)).hexdigest() != fact_id
        ):
            raise ValueError("fact_id does not match fact content")
        name = fact.get("feature_name")
        if not isinstance(name, str) or name in by_name:
            raise ValueError("facts require unique feature names")
        by_name[name] = fact
    instruments = {fact.get("instrument_id") for fact in facts}
    cutoffs = {fact.get("decision_cutoff_at") for fact in facts}
    if len(instruments) > 1 or len(cutoffs) > 1:
        raise ValueError("summary facts must share one instrument and cutoff")

    purchase = by_name.get("disclosed_purchase_count_30d")
    sale = by_name.get("disclosed_sale_count_30d")
    cluster = by_name.get("purchase_cluster_30d")
    breakout = by_name.get("price_breakout_state")
    slots = {
        "purchase_activity": {
            "fact_id": purchase.get("fact_id") if purchase else None,
            "text": _fact_text(purchase, "買入") if purchase else "買入資料不可用。",
        },
        "sale_activity": {
            "fact_id": sale.get("fact_id") if sale else None,
            "text": _fact_text(sale, "賣出") if sale else "賣出資料不可用。",
        },
    }
    if cluster is None or cluster.get("status") != "available" or type(cluster.get("value")) is not bool:
        cluster_text = "主體關係或來源核對不完整，無法判定買入群聚。"
    elif cluster["value"]:
        cluster_text = "符合至少三個已核實獨立主體買入揭露的描述條件。"
    else:
        cluster_text = "未符合至少三個已核實獨立主體買入揭露的描述條件。"
    slots["purchase_cluster"] = {
        "fact_id": cluster.get("fact_id") if cluster else None,
        "text": cluster_text,
    }

    if breakout is None or breakout.get("status") != "available":
        price_text = "價格資料不足，無法核對前 20 個交易日高點。"
    elif breakout.get("value") == "above_prior_high":
        price_text = f"截至 {breakout.get('source_available_through') or '未知日期'}，收盤價高於此前 20 個交易日最高收盤價。"
    elif breakout.get("value") == "not_above_prior_high":
        price_text = f"截至 {breakout.get('source_available_through') or '未知日期'}，收盤價未高於此前 20 個交易日最高收盤價。"
    else:
        price_text = "價格資料不足，無法核對前 20 個交易日高點。"
    slots["price_context"] = {
        "fact_id": breakout.get("fact_id") if breakout else None,
        "text": price_text,
    }

    summary = {
        "schema_version": 1,
        "instrument_id": next(iter(instruments), None),
        "decision_cutoff_at": next(iter(cutoffs), None),
        "rule_version": rule_version.strip(),
        "template_version": template_version.strip(),
        "slots": slots,
        "disclaimer": "以上為申報與價格資料的描述，不代表投資建議或因果關係。",
    }
    summary["summary_id"] = hashlib.sha256(_json_bytes(summary)).hexdigest()
    return summary
