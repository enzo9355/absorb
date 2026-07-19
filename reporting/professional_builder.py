"""Build an institutional post-close report from verified observation metadata."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .professional_schema import ProfessionalPostCloseReport, compute_content_sha256


_AI_DISCLOSURE = (
    "內容由 Gemini 根據 ABSORB 可取得的市場、產業、個股及量化研究資料整理，"
    "不構成個人化投資建議，亦不保證未來結果。"
)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _market_state(ma20_breadth_pct: Any) -> str:
    if type(ma20_breadth_pct) not in (int, float):
        return "資料不足"
    if ma20_breadth_pct < 40:
        return "提高防守"
    if ma20_breadth_pct <= 60:
        return "中性觀察"
    return "風險改善"


def _format_pct(value: Any) -> str:
    return "資料不足" if type(value) not in (int, float) else f"{value:+.2f}%"


def _executive_summary(
    market: Mapping[str, Any], industries: list[dict[str, Any]]
) -> dict[str, Any]:
    breadth = market.get("ma20_breadth_pct")
    daily_return = market.get("return_1d_pct")
    state = _market_state(breadth)
    breadth_text = (
        "資料不足" if type(breadth) not in (int, float) else f"{breadth:.1f}%"
    )
    ranked = [
        item
        for item in industries
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and type(item.get("relative_return_5d_pct")) in (int, float)
    ]
    ranked.sort(key=lambda item: item["relative_return_5d_pct"], reverse=True)
    edge_count = min(3, max(1, len(ranked) // 2)) if ranked else 0
    strongest = [item["name"] for item in ranked[:edge_count]]
    weakest = (
        [item["name"] for item in reversed(ranked[-edge_count:])]
        if edge_count
        else []
    )
    supporting = []
    opposing = []
    if type(breadth) in (int, float):
        target = supporting if breadth >= 50 else opposing
        target.append(f"站上 MA20 比例為 {breadth:.1f}%")
    if type(daily_return) in (int, float):
        target = supporting if daily_return >= 0 else opposing
        target.append(f"市場單日報酬為 {daily_return:+.2f}%")
    if not supporting:
        supporting.append("目前沒有足夠資料形成明確正向證據")
    if not opposing:
        opposing.append("目前沒有足夠資料形成明確反向證據")
    return {
        "market_state": state,
        "one_line_conclusion": (
            f"市場單日報酬 {_format_pct(daily_return)}，站上 MA20 比例 {breadth_text}；"
            f"目前規則式風險狀態為「{state}」。"
        ),
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "largest_risk": (
            "市場廣度持續惡化"
            if state == "提高防守"
            else "市場風險狀態快速反轉"
        ),
        "strongest_industries": strongest,
        "weakest_industries": weakest,
        "next_session_watch_conditions": [
            "觀察站上 MA20 比例是否改善",
            "觀察最強產業是否獲得量能與廣度確認",
            "觀察市場波動率是否進一步擴張",
        ],
        "ai_reference_summary": None,
    }


def _industry_section(items: list[Any]) -> dict[str, Any]:
    normalized = []
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        available_count = item.get("available_count")
        component_count = item.get("component_count")
        coverage = None
        if (
            type(available_count) is int
            and type(component_count) is int
            and component_count > 0
        ):
            coverage = available_count / component_count
        normalized.append(
            {
                "name": item["name"],
                "available_count": available_count,
                "component_count": component_count,
                "coverage": coverage,
                "relative_return_5d_pct": item.get("relative_return_5d_pct"),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["relative_return_5d_pct"] is not None,
            item["relative_return_5d_pct"]
            if type(item["relative_return_5d_pct"]) in (int, float)
            else float("-inf"),
        ),
        reverse=True,
    )
    for rank, item in enumerate(normalized, 1):
        item["rank"] = rank
    return {"ranking": normalized}


def build_professional_post_close_report(
    metadata: Mapping[str, Any], *, code_commit_sha: str
) -> ProfessionalPostCloseReport:
    """Convert verified observation post-close metadata into the canonical report."""

    metadata = _require_mapping(metadata, "metadata")
    if metadata.get("schema_version") != 2:
        raise ValueError("metadata schema_version must be 2")
    if metadata.get("report_type") != "post_close":
        raise ValueError("professional report builder only accepts post_close metadata")
    if metadata.get("product_mode") != "observation" or metadata.get("market") != "TW":
        raise ValueError("metadata must be a TW observation report")
    capability = _require_mapping(
        metadata.get("prediction_capability"), "prediction_capability"
    )
    if capability.get("probability_allowed") is not False:
        raise ValueError("probability output must remain disabled")
    if capability.get("strong_action_allowed") is not False:
        raise ValueError("strong action output must remain disabled")

    content = _require_mapping(metadata.get("content"), "content")
    market = _require_mapping(content.get("market_observation"), "market_observation")
    quality = _require_mapping(content.get("data_quality"), "data_quality")
    industries = content.get("industry_observations")
    stock_events = content.get("stock_events")
    etfs = content.get("etf_observations")
    daily_focus = content.get("daily_focus")
    if not all(
        isinstance(value, list)
        for value in (industries, stock_events, etfs, daily_focus)
    ):
        raise ValueError("observation content lists are invalid")

    source_date = str(metadata.get("source_market_date") or "")
    applicable_date = str(metadata.get("applicable_trading_date") or "")
    published_at = str(metadata.get("published_at") or "")
    industry_data = _industry_section(industries)
    document = {
        "schema_version": 1,
        "kind": "absorb-professional-post-close-report",
        "identity": {
            "schema_version": 1,
            "report_type": "post_close",
            "product_tier": "institutional",
            "product_mode": "observation_with_research",
            "market": "TW",
            "source_market_date": source_date,
            "applicable_trading_date": applicable_date,
            "published_at": published_at,
            "generated_at": published_at,
            "source_manifest": metadata.get("source_manifest"),
            "source_manifest_sha256": metadata.get("source_manifest_sha256"),
            "content_sha256": "",
            "report_id": f"TW-{source_date.replace('-', '')}-post-close-institutional",
            "generator_version": "professional-report/1",
            "code_commit_sha": code_commit_sha,
            "model_version": None,
            "feature_schema_version": "observation-v2",
            "recommendation_policy_version": "observation-policy/v1",
        },
        "executive_summary": _executive_summary(market, industry_data["ranking"]),
        "key_events": [
            {
                "headline": str(value),
                "description": str(value),
                "data_as_of": source_date,
                "source": "verified_observation",
            }
            for value in daily_focus[:8]
            if isinstance(value, str) and value.strip()
        ],
        "market": {
            "status": "available",
            "data_as_of": source_date,
            "data": copy.deepcopy(dict(market)),
        },
        "capital_flows": {
            "status": "unavailable",
            "reason": "法人流向尚未納入目前的已驗證 Observation Artifact",
            "data": {},
        },
        "industries": {
            "status": "available",
            "data_as_of": source_date,
            "data": industry_data,
        },
        "securities": {
            "status": "available",
            "data_as_of": source_date,
            "data": {
                "stock_events": copy.deepcopy(stock_events),
                "etf_observations": copy.deepcopy(etfs),
                "positive_observations": [],
                "risk_observations": [],
                "high_anomaly_observations": copy.deepcopy(stock_events),
            },
        },
        "quantitative_research": {
            "status": "unavailable",
            "reason": "模型 Promotion 維持 BLOCKED；不發布未通過驗證的機率或交易背書",
            "data": {},
        },
        "validation": {
            "status": "available",
            "data_as_of": source_date,
            "data": {
                "gates": {
                    "ranking": "UNAVAILABLE",
                    "calibration": "UNAVAILABLE",
                    "quality": "UNAVAILABLE",
                    "transaction_value": "UNAVAILABLE",
                    "promotion": "BLOCKED",
                },
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
                "gate_detail_status": "not_present_in_observation_metadata",
            },
        },
        "next_session": {
            "status": "available",
            "data_as_of": source_date,
            "data": {
                "positive": ["市場廣度回升且主要產業量能同步改善"],
                "neutral": ["市場廣度維持區間，產業輪動缺乏一致方向"],
                "negative": ["市場廣度續降且波動率擴張"],
                "watch_conditions": [
                    "站上 MA20 比例",
                    "最強產業量能與內部廣度",
                    "20 日已實現波動率",
                ],
            },
        },
        "governance": {
            "status": "available",
            "data_as_of": source_date,
            "data": {
                "coverage": quality.get("coverage"),
                "symbol_count": (
                    quality.get("symbol_count")
                    if quality.get("symbol_count") is not None
                    else quality.get("available_count")
                ),
                "failure_count": quality.get("failure_count"),
                "source_manifest": metadata.get("source_manifest"),
                "source_manifest_sha256": metadata.get("source_manifest_sha256"),
                "failed_symbols": copy.deepcopy(quality.get("failed_symbols") or []),
            },
        },
        "ai_reference": {
            "status": "unavailable",
            "reason": "Gemini 尚未針對此 Canonical Report 產生參考解讀",
            "data": {"disclaimer": _AI_DISCLOSURE},
        },
    }
    document["identity"]["content_sha256"] = compute_content_sha256(document)
    return ProfessionalPostCloseReport.from_document(document)
