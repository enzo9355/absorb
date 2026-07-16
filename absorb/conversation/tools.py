from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from absorb.conversation.tool_registry import ToolRegistry, ToolSpec


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _distance(price, average):
    price, average = _finite(price), _finite(average)
    return None if price is None or average in {None, 0.0} else (price - average) / average


def resolve_entities(query: str, search_stock: Callable[[str], tuple[str | None, str | None]]):
    candidates = [query.strip()]
    candidates += [
        part.strip()
        for part in re.split(r"(?:和|與|及|、|，|,|/|\bvs\.?\b)", query, flags=re.IGNORECASE)
        if part.strip()
    ]
    candidates += re.findall(r"(?<!\d)\d{4,5}(?!\d)|(?<![A-Za-z])[A-Za-z][A-Za-z0-9.-]{0,9}(?![A-Za-z])", query)
    seen = set()
    resolved = []
    for candidate in candidates:
        try:
            symbol, name = search_stock(candidate)
        except Exception:
            continue
        symbol = str(symbol or "").upper()
        if symbol in {"AI", "API", "LINE", "LLM", "WEB", "TW", "US"} and query.strip().upper() != symbol:
            continue
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        market = "TW" if symbol == "TAIEX" or symbol.isdigit() else "US"
        resolved.append({"market": market, "symbol": symbol, "name": str(name or symbol)})
        if len(resolved) == 2:
            break
    if not resolved and any(term in query for term in ("台股", "大盤", "加權指數", "盤勢")):
        resolved.append({"market": "TW", "symbol": "TAIEX", "name": "台股大盤"})
    return resolved


def normalize_stock_analysis(data: dict[str, Any]) -> dict[str, Any]:
    recommendation = data.get("recommendation") if isinstance(data.get("recommendation"), dict) else {}
    foreign = data.get("foreign_flow") if isinstance(data.get("foreign_flow"), dict) else {}
    backtest = data.get("bt") if isinstance(data.get("bt"), dict) else {}
    price = _finite(data.get("price"))
    probability = _finite(data.get("prob"))
    bootstrap = data.get("baseline_status") == "initial_backtest_bootstrap"
    symbol = str(data.get("code") or "").upper()
    as_of = recommendation.get("data_as_of") or data.get("as_of")
    limitations = []
    required = {
        "probability_change_1d": data.get("probability_change_1d"),
        "probability_change_5d": data.get("probability_change_5d"),
        "return_1d": data.get("return_1d"),
        "return_5d": data.get("return_5d"),
        "ma60_distance": _distance(price, data.get("ma60")),
        "volume_ratio": data.get("volume_ratio"),
        "volatility": data.get("volatility"),
        "model_version": data.get("model_version"),
        "backtest_as_of": data.get("backtest_as_of"),
    }
    limitations.extend(f"{key} unavailable" for key, value in required.items() if value is None)
    stale = data.get("stale") is True or recommendation.get("level") == "insufficient"
    quality = "stale" if stale else ("partial" if limitations else "available")
    return {
        "market": "TW" if symbol == "TAIEX" or symbol.isdigit() else "US",
        "symbol": symbol,
        "name": data.get("name"),
        "instrument_type": data.get("instrument_type") or ("market" if symbol == "TAIEX" else "stock"),
        "data_as_of": str(as_of) if as_of else None,
        "generated_at": data.get("generated_at"),
        "data_quality": quality,
        "stale": stale,
        "latest_price": price,
        "five_day_probability": (
            None if bootstrap or probability is None else probability / 100
        ),
        "model_direction_score": (
            probability / 100 if bootstrap and probability is not None else None
        ),
        "model_output_label": data.get("model_output_label"),
        "calibration_notice": data.get("calibration_notice"),
        "baseline_status": data.get("baseline_status"),
        "strong_action_allowed": data.get("strong_action_allowed", not bootstrap),
        "probability_change_1d": _finite(required["probability_change_1d"]),
        "probability_change_5d": _finite(required["probability_change_5d"]),
        "action_label": recommendation.get("action"),
        "confidence": recommendation.get("confidence"),
        "return_1d": _finite(required["return_1d"]),
        "return_5d": _finite(required["return_5d"]),
        "rsi": _finite(data.get("rsi")),
        "ma20_distance": _distance(price, data.get("ma20")),
        "ma60_distance": _finite(required["ma60_distance"]),
        "volume_ratio": _finite(required["volume_ratio"]),
        "volatility": _finite(required["volatility"]),
        "institutional_flow": {
            "foreign_5d": _finite(foreign.get("net_5")) if foreign.get("available") else None,
            "investment_trust_5d": _finite(data.get("investment_trust_5d")),
            "dealer_5d": _finite(data.get("dealer_5d")),
        },
        "primary_industry": data.get("primary_industry"),
        "related_industries": list(data.get("related_industries") or [])[:5],
        "industry_action": data.get("industry_action"),
        "market_action": data.get("market_action"),
        "supporting_evidence": list(recommendation.get("supporting_reasons") or [])[:4],
        "opposing_evidence": list(recommendation.get("risk_reasons") or [])[:4],
        "reasonable_action": recommendation.get("suggested_action"),
        "invalidation_conditions": list(recommendation.get("invalidation_conditions") or [])[:4],
        "model_version": required["model_version"],
        "backtest_as_of": required["backtest_as_of"],
        "backtest_sample_count": None if bootstrap else backtest.get("trades"),
        "limitations": limitations[:12],
    }


def build_registry(
    *, analyze, sector_ranking=None, report_lookup=None,
    watchlist_lookup=None, alerts_lookup=None,
):
    def stock_analysis(market, symbol):
        data = analyze(symbol)
        if not isinstance(data, dict):
            return {"market": market, "symbol": symbol, "data_quality": "unavailable", "limitations": ["analysis unavailable"]}
        return normalize_stock_analysis(data)

    def compare(market, symbols):
        items = [stock_analysis(market, symbol) for symbol in symbols[:2]]
        quality = "available" if items and all(item.get("data_quality") == "available" for item in items) else "partial"
        return {"market": market, "items": items, "data_quality": quality}

    def prediction_items(data, sessions):
        raw = data.get("prediction_development") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raw = data.get("probability_history") if isinstance(data, dict) else None
        items = []
        for item in list(raw or [])[-max(1, min(int(sessions), 20)):]:
            if not isinstance(item, dict):
                continue
            probability = item.get("five_day_probability")
            if probability is None:
                probability = item.get("probability")
            items.append({
                "source_market_date": item.get("source_market_date") or item.get("date"),
                "five_day_probability": _finite(probability),
                "action_label": item.get("action_label"),
                "status": item.get("status"),
                "model_version": item.get("model_version"),
                "actual_return": _finite(item.get("actual_return")),
                "direction_correct": item.get("direction_correct")
                if isinstance(item.get("direction_correct"), bool) else None,
                "evaluated_on": item.get("evaluated_on"),
                "invalid_reason": item.get("invalid_reason") or item.get("reason"),
            })
        return items

    def prediction_history(market, symbol, sessions=5):
        data = analyze(symbol)
        items = prediction_items(data, sessions)
        return {
            "market": market, "symbol": symbol, "items": items,
            "data_quality": "available" if items else "unavailable",
            "limitations": [] if items else ["prediction history unavailable"],
        }

    def stock_industries(market, symbol):
        result = stock_analysis(market, symbol)
        return {
            "market": market,
            "symbol": symbol,
            "primary_industry": result.get("primary_industry"),
            "related_industries": result.get("related_industries", []),
            "data_quality": result.get("data_quality", "unavailable"),
        }

    def market_outlook(market="TW"):
        symbol = "TAIEX" if market == "TW" else "SPY"
        return stock_analysis(market, symbol)

    def industry_ranking(market="TW", limit=5):
        if sector_ranking is None:
            return {"market": market, "data_quality": "unavailable", "items": [], "limitations": ["industry ranking unavailable"]}
        return {"market": market, "items": list(sector_ranking())[: max(1, min(int(limit), 10))]}

    def industry_analysis(market="TW", industry_id=None):
        ranked = industry_ranking(market, 10)
        wanted = str(industry_id or "").strip()
        items = [item for item in ranked["items"] if str(item.get("industry")) == wanted]
        return {
            "market": market,
            "industry_id": wanted,
            "items": items,
            "data_quality": "available" if items else "unavailable",
            "limitations": [] if items else ["industry analysis unavailable"],
        }

    def industry_prediction_history(market="TW", industry_id=None, sessions=5):
        analysis = industry_analysis(market, industry_id)
        source = analysis["items"][0] if analysis.get("items") else {}
        items = prediction_items(source, sessions)
        return {
            "market": market,
            "industry_id": str(industry_id or ""),
            "items": items,
            "data_quality": "available" if items else "unavailable",
            "limitations": [] if items else ["industry prediction history unavailable"],
        }

    def prediction_settlement(forecast_id):
        return {
            "forecast_id": forecast_id,
            "data_quality": "unavailable",
            "limitations": ["prediction settlement is not published to the conversation service"],
        }

    def recent_prediction_results(market, entity_type, entity_id, limit=5):
        if entity_type == "industry":
            history = industry_prediction_history(market, entity_id, limit)
        else:
            history = prediction_history(market, entity_id, limit)
        items = [
            item for item in history.get("items", [])
            if item.get("status") in {"matured", "invalid"}
            or item.get("actual_return") is not None
            or item.get("direction_correct") is not None
        ][:limit]
        return {
            "market": market,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "items": items,
            "data_quality": "available" if items else "unavailable",
            "limitations": [] if items else ["recent prediction results unavailable"],
        }

    def latest_report(market="TW", report_type="post_close"):
        if report_lookup is None:
            return {"market": market, "report_type": report_type, "data_quality": "unavailable", "limitations": ["report unavailable"]}
        value = report_lookup(report_type)
        return value if isinstance(value, dict) else {"market": market, "report_type": report_type, "data_quality": "unavailable"}

    def model_performance(market="TW"):
        report = latest_report(market, "weekly_model")
        return {
            "market": market,
            "title": report.get("title"),
            "summary": list(report.get("summary") or [])[:5],
            "published_at": report.get("published_at"),
            "data_quality": report.get("data_quality", "unavailable"),
            "limitations": list(report.get("limitations") or [])[:5],
        }

    def data_quality(market="TW"):
        symbol = "TAIEX" if market == "TW" else "SPY"
        result = stock_analysis(market, symbol)
        return {
            "market": market,
            "data_as_of": result.get("data_as_of"),
            "data_quality": result.get("data_quality", "unavailable"),
            "stale": result.get("stale") is True,
            "limitations": result.get("limitations", []),
        }

    def user_watchlist():
        if watchlist_lookup is None:
            return {"items": [], "data_quality": "unavailable", "limitations": ["watchlist unavailable"]}
        items = list(watchlist_lookup().get("watchlist", []))[:12]
        return {
            "items": [
                {"symbol": item.get("code"), "name": item.get("name")}
                for item in items if isinstance(item, dict)
            ],
            "data_quality": "available",
        }

    def watchlist_analysis():
        watchlist = user_watchlist()
        items = []
        for item in watchlist.get("items", [])[:5]:
            symbol = str(item.get("symbol") or "")
            if symbol:
                items.append(stock_analysis("TW" if symbol.isdigit() else "US", symbol))
        return {"items": items, "data_quality": "available" if items else watchlist.get("data_quality", "unavailable")}

    def user_alerts():
        if alerts_lookup is None:
            return {"items": [], "data_quality": "unavailable", "limitations": ["alerts unavailable"]}
        items = list(alerts_lookup().get("alerts", []))[:20]
        return {
            "items": [
                {
                    "symbol": item.get("code"), "name": item.get("name"),
                    "kind": item.get("kind"), "value": _finite(item.get("value")),
                }
                for item in items if isinstance(item, dict)
            ],
            "data_quality": "available",
        }

    return ToolRegistry(
        (
            ToolSpec("get_stock_snapshot", stock_analysis, "取得個股最新快照", ("market", "symbol"), ("market", "symbol")),
            ToolSpec("get_stock_analysis", stock_analysis, "取得個股完整量化分析", ("market", "symbol"), ("market", "symbol")),
            ToolSpec("get_stock_prediction_history", prediction_history, "取得個股歷史預測", ("market", "symbol", "sessions"), ("market", "symbol")),
            ToolSpec("get_stock_risk_context", stock_analysis, "取得個股追價與風險資料", ("market", "symbol"), ("market", "symbol")),
            ToolSpec("get_stock_industries", stock_industries, "取得個股所屬產業", ("market", "symbol"), ("market", "symbol")),
            ToolSpec("compare_stocks", compare, "比較兩檔已解析股票", ("market", "symbols"), ("market", "symbols")),
            ToolSpec("get_market_outlook", market_outlook, "取得市場展望", ("market",), ("market",)),
            ToolSpec("get_market_prediction_history", lambda market="TW", sessions=5: prediction_history(market, "TAIEX" if market == "TW" else "SPY", sessions), "取得市場歷史預測", ("market", "sessions"), ("market",)),
            ToolSpec("get_industry_analysis", industry_analysis, "取得已解析產業分析", ("market", "industry_id"), ("market", "industry_id")),
            ToolSpec("get_industry_ranking", industry_ranking, "取得產業強弱排名", ("market", "limit"), ("market",)),
            ToolSpec("get_industry_prediction_history", industry_prediction_history, "取得產業歷史預測", ("market", "industry_id", "sessions"), ("market", "industry_id")),
            ToolSpec("get_latest_post_close_report", lambda market="TW": latest_report(market, "post_close"), "取得最新盤後報告", ("market",), ("market",)),
            ToolSpec("get_latest_pre_market_report", lambda market="TW": latest_report(market, "pre_market"), "取得最新盤前更新", ("market",), ("market",)),
            ToolSpec("get_latest_weekly_model_report", lambda market="TW": latest_report(market, "weekly_model"), "取得最新模型週報", ("market",), ("market",)),
            ToolSpec("get_model_performance", model_performance, "取得近期模型驗證摘要", ("market",), ("market",)),
            ToolSpec("get_prediction_settlement", prediction_settlement, "取得單筆已發布預測結算", ("forecast_id",), ("forecast_id",)),
            ToolSpec("get_recent_prediction_results", recent_prediction_results, "取得近期成熟預測結果", ("market", "entity_type", "entity_id", "limit"), ("market", "entity_type", "entity_id")),
            ToolSpec("get_data_quality_status", data_quality, "取得資料日期與品質", ("market",), ("market",)),
            ToolSpec("get_user_watchlist", user_watchlist, "取得登入使用者關注清單", access="authenticated"),
            ToolSpec("get_watchlist_analysis", watchlist_analysis, "分析登入使用者關注清單", access="authenticated"),
            ToolSpec("get_user_alerts", user_alerts, "取得登入使用者提醒", access="authenticated"),
        )
    )
