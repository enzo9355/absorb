"""將已驗證日報資料投影成公開 HTML 報告所需的安全資料。"""

from reporting.interpretation import interpret_backtest
from stock_papi.services.recommendation_engine import (
    RecommendationInput,
    build_recommendation,
)


def _trend_from_rotation(rotation):
    if rotation in {"leading", "improving", "領先", "改善"}:
        return "多頭"
    if rotation in {"weakening", "lagging", "轉弱", "落後"}:
        return "空頭"
    return None


def _market_trend(report):
    breadth = report.market.ma60_breadth
    if breadth is None:
        return None
    return "多頭" if breadth >= 0.5 else "空頭"


def _public_recommendation(result):
    value = result.to_dict()
    return {
        key: value[key]
        for key in (
            "action", "level", "headline", "confidence",
            "supporting_reasons", "risk_reasons", "suggested_action",
            "invalidation_conditions", "unheld_guidance", "held_guidance",
            "data_as_of",
        )
    }


def build_public_report(report):
    """只使用 point-in-time 日報物件建立可公開、可序列化的摘要。"""
    report_date = report.report_date
    market = _public_recommendation(build_recommendation(RecommendationInput(
        scope="market",
        entity_id="TAIEX",
        probability=report.market.average_probability,
        trend=_market_trend(report),
        data_as_of=report_date,
        current_date=report_date,
        sample_count=report.model_quality.pooled_oos_samples,
        data_quality_warning=(report.market.data_warning_ratio or 0) > 0,
    )))

    backtest_by_industry = {item.industry: item for item in report.backtests}
    industries = []
    for industry in report.industries:
        backtest = backtest_by_industry.get(industry.name)
        recommendation = _public_recommendation(build_recommendation(
            RecommendationInput(
                scope="industry",
                entity_id=industry.name,
                probability=industry.average_probability,
                trend=_trend_from_rotation(industry.rotation),
                data_as_of=report_date,
                current_date=report_date,
                sample_count=backtest.valid_signals if backtest else None,
                industry_coverage=industry.coverage,
                rotation=industry.rotation,
                near_rotation_boundary=industry.near_boundary,
                market_action=market["action"],
            )
        ))
        industries.append({
            "name": industry.name,
            "probability": industry.average_probability,
            "rotation": industry.rotation,
            "coverage": industry.coverage,
            "action": recommendation["action"],
            "headline": recommendation["headline"],
            "risk": recommendation["risk_reasons"][0],
            "confidence": recommendation["confidence"],
        })

    stock_by_symbol = {stock.symbol: stock for stock in report.source.stocks}
    stocks = []
    for item in report.watchlist:
        stock = stock_by_symbol.get(item["symbol"])
        stock_backtest = stock.backtest if stock else {}
        recommendation = _public_recommendation(build_recommendation(
            RecommendationInput(
                scope="stock",
                entity_id=item["symbol"],
                probability=item.get("probability"),
                trend=item.get("trend"),
                data_as_of=report_date,
                current_date=report_date,
                rsi=item.get("rsi"),
                volume_ratio=item.get("volume_ratio"),
                foreign_net_5=item.get("foreign_net_5"),
                sample_count=stock_backtest.get("trades"),
                market_action=market["action"],
            )
        ))
        stocks.append({
            "symbol": item["symbol"],
            "name": item["name"],
            "industries": list(item.get("industries") or []),
            "probability": item.get("probability"),
            "action": recommendation["action"],
            "headline": recommendation["headline"],
            "supporting_reasons": recommendation["supporting_reasons"],
            "risks": recommendation["risk_reasons"],
            "confidence": recommendation["confidence"],
        })

    comparable = next((item for item in report.backtests if item.sufficient), None)
    if comparable:
        metrics = {
            "strat_cum": comparable.cumulative_return * 100 if comparable.cumulative_return is not None else None,
            "bh_cum": comparable.buy_hold_return * 100 if comparable.buy_hold_return is not None else None,
            "mdd": comparable.max_drawdown * 100 if comparable.max_drawdown is not None else None,
            "win_rate": comparable.win_rate * 100 if comparable.win_rate is not None else None,
            "cash_period_ratio": comparable.cash_period_ratio,
            "sharpe": comparable.sharpe,
            "brier": report.model_quality.brier_score,
        }
        backtest = {
            "industry": comparable.industry,
            "sample_quality": comparable.sample_quality,
            "periods": comparable.rebalance_periods,
            "interpretation": interpret_backtest(metrics),
            "average_profit": comparable.average_profit,
            "average_loss": comparable.average_loss,
            "expected_return": comparable.expected_return,
            "payoff_ratio": comparable.payoff_ratio,
            "profit_factor": comparable.profit_factor,
            "longest_winning_streak": comparable.longest_winning_streak,
            "longest_losing_streak": comparable.longest_losing_streak,
            "cost_sensitivity": comparable.cost_sensitivity,
            "yearly_returns": comparable.yearly_returns,
        }
    else:
        backtest = {
            "industry": None,
            "sample_quality": "可信度低",
            "periods": 0,
            "interpretation": interpret_backtest({}),
        }

    return {
        "schema_version": 1,
        "market_recommendation": market,
        "key_points": list(report.summary[:3]),
        "industries": industries,
        "stocks": stocks,
        "backtest": backtest,
        "model_quality": {
            "samples": report.model_quality.pooled_oos_samples,
            "direction_accuracy": report.model_quality.direction_accuracy,
            "brier_score": report.model_quality.brier_score,
            "calibration_bins": report.model_quality.calibration_bins,
        },
    }
