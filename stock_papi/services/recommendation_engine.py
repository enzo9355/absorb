"""Web、LINE 與報告共用的確定性 AI 量化解方。"""

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Literal


Scope = Literal["market", "industry", "stock"]


@dataclass(frozen=True)
class RecommendationThresholds:
    bullish_probability: float = 60.0
    weak_probability: float = 45.0
    overbought_rsi: float = 70.0
    oversold_rsi: float = 30.0
    unusual_volume_ratio: float = 2.0
    low_volume_ratio: float = 0.8
    elevated_volatility: float = 0.03
    minimum_industry_coverage: float = 0.8
    minimum_sample_count: int = 12
    medium_sample_count: int = 24
    complete_sample_count: int = 48
    maximum_business_age: int = 1


@dataclass(frozen=True)
class RecommendationInput:
    scope: Scope
    entity_id: str
    probability: float | None = None
    trend: str | None = None
    data_as_of: datetime.date | None = None
    current_date: datetime.date | None = None
    rsi: float | None = None
    volume_ratio: float | None = None
    foreign_net_5: float | None = None
    volatility: float | None = None
    sample_count: int | None = None
    industry_coverage: float | None = None
    rotation: str | None = None
    near_rotation_boundary: bool = False
    market_action: str | None = None
    data_quality_warning: bool = False
    source_disagreement: bool = False
    max_drawdown: float | None = None
    strategy_return: float | None = None
    buy_hold_return: float | None = None


@dataclass(frozen=True)
class RecommendationResult:
    scope: Scope
    entity_id: str
    action: str
    level: str
    headline: str
    confidence: str
    supporting_reasons: tuple[str, ...]
    risk_reasons: tuple[str, ...]
    suggested_action: str
    invalidation_conditions: tuple[str, ...]
    unheld_guidance: str
    held_guidance: str
    data_as_of: datetime.date | None
    source_metrics: dict[str, Any] = field(compare=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "entity_id": self.entity_id,
            "action": self.action,
            "level": self.level,
            "headline": self.headline,
            "confidence": self.confidence,
            "supporting_reasons": list(self.supporting_reasons),
            "risk_reasons": list(self.risk_reasons),
            "suggested_action": self.suggested_action,
            "invalidation_conditions": list(self.invalidation_conditions),
            "unheld_guidance": self.unheld_guidance,
            "held_guidance": self.held_guidance,
            "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
            "source_metrics": dict(self.source_metrics),
        }


def _number(value: Any, *, low: float | None = None, high: float | None = None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if low is not None and number < low:
        return None
    if high is not None and number > high:
        return None
    return number


def _display_number(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"


def _business_age(start: datetime.date, end: datetime.date) -> int:
    if end <= start:
        return 0
    current = start + datetime.timedelta(days=1)
    age = 0
    while current <= end:
        if current.weekday() < 5:
            age += 1
        current += datetime.timedelta(days=1)
    return age


def _confidence(sample_count: int | None, thresholds: RecommendationThresholds) -> str:
    if sample_count is None or sample_count < thresholds.minimum_sample_count:
        return "可信度低"
    if sample_count < thresholds.medium_sample_count:
        return "可信度有限"
    if sample_count < thresholds.complete_sample_count:
        return "可信度中等"
    return "相對完整"


def _is_bullish(trend: str | None) -> bool:
    return bool(trend and ("多頭" in trend or "站上 MA20" in trend))


def _is_bearish(trend: str | None) -> bool:
    return bool(trend and ("空頭" in trend or "跌破 MA20" in trend))


def _result_text(scope: Scope, action: str, *, conflicted: bool, overheated: bool):
    if scope == "market":
        mapping = {
            "積極選股": ("模型與市場趨勢同向，可積極篩選強勢標的", "保留選股紀律，避免追逐單一急漲標的。"),
            "逢回布局": ("市場結構偏多，但較適合等待拉回", "分批觀察強勢產業，避免一次投入全部資金。"),
            "控制追價": ("市場訊號尚未形成一致優勢", "降低追價速度，等待模型與趨勢重新同向。"),
            "提高防守": ("模型與趨勢偏弱，應優先控制風險", "降低整體曝險，保留現金並等待結構改善。"),
        }
        headline, suggested = mapping[action]
        return headline, suggested, suggested, "既有部位優先檢查風險與停損條件。"
    if scope == "industry":
        mapping = {
            "優先關注": ("模型、輪動與資料品質一致，可列為優先研究方向", "先從產業內相對強勢且資料完整的標的開始研究。"),
            "分批觀察": ("方向偏多但仍有降級風險，適合分批觀察", "等待輪動位置或過熱訊號改善後再提高關注。"),
            "等待確認": ("產業訊號尚未形成一致結論", "等待機率、輪動與樣本品質重新一致。"),
            "降低曝險": ("產業動能轉弱，宜降低曝險", "減少新增部位並檢查既有持股風險。"),
            "暫時避開": ("模型與輪動偏弱，暫時不宜新增曝險", "等待產業脫離弱勢區再重新評估。"),
        }
        headline, suggested = mapping[action]
        return headline, suggested, suggested, "既有部位宜降低集中度並設定失效條件。"

    if action == "優先布局":
        headline = "模型與中期趨勢同向，且資料與歷史樣本相對完整"
    elif action == "分批布局":
        headline = "模型與趨勢偏多，但短線不宜追高" if overheated else "方向偏多，但仍應分批控制進場風險"
    elif action == "持有觀察":
        headline = "趨勢尚可，但目前沒有足夠優勢支持明顯加碼"
    elif action == "等待確認":
        headline = "模型與趨勢出現分歧，先等待訊號重新一致" if conflicted else "目前資料不足以支持明確行動"
    elif action == "降低部位":
        headline = "部分核心訊號轉弱，應先降低部位風險"
    else:
        headline = "模型與趨勢偏弱，暫時不宜新增部位"
    suggested = {
        "優先布局": "仍應分批建立部位，並保留風險預算。",
        "分批布局": "等待拉回後分二至三次建立部位，不建議一次投入全部資金。",
        "持有觀察": "維持觀察，不因單一機率明顯加碼。",
        "等待確認": "等待股價與 MA20 趨勢、模型機率重新同向。",
        "降低部位": "降低曝險並檢查停損條件，不逆勢攤平。",
        "暫時避開": "暫不新增部位，等待模型與趨勢改善。",
    }[action]
    return headline, suggested, suggested, (
        "可續抱但不宜明顯加碼，並持續檢查失效條件。"
        if action in {"優先布局", "分批布局", "持有觀察"}
        else "優先降低風險，等待訊號改善後再評估。"
    )


def build_recommendation(
    source: RecommendationInput,
    thresholds: RecommendationThresholds | None = None,
) -> RecommendationResult:
    settings = thresholds or RecommendationThresholds()
    probability = _number(source.probability, low=0, high=100)
    rsi = _number(source.rsi, low=0, high=100)
    volume = _number(source.volume_ratio, low=0)
    volatility = _number(source.volatility, low=0)
    coverage = _number(source.industry_coverage, low=0, high=1)
    supporting = []
    risks = []
    blockers = []

    if probability is None:
        blockers.append("五日上漲機率缺失")
    else:
        supporting.append(f"五日上漲機率 {_display_number(probability)}%")
    bullish = _is_bullish(source.trend)
    bearish = _is_bearish(source.trend)
    if bullish:
        supporting.append("站上 MA20")
    elif bearish:
        risks.append("跌破 MA20")
    else:
        blockers.append("MA20 趨勢資料缺失")

    if source.data_as_of is None:
        blockers.append("資料截止日期缺失")
    elif source.current_date and _business_age(source.data_as_of, source.current_date) > settings.maximum_business_age:
        blockers.append("資料已超過一個市場工作日")
    if source.sample_count is None or source.sample_count < settings.minimum_sample_count:
        blockers.append("相似歷史訊號少於 12 次")
    if source.data_quality_warning:
        blockers.append("資料源價差警示")
    if source.source_disagreement:
        blockers.append("重要資料來源不一致")
    if source.scope == "industry" and (coverage is None or coverage < settings.minimum_industry_coverage):
        blockers.append("產業資料覆蓋不足 80%")

    conflicted = probability is not None and ((probability >= settings.bullish_probability and bearish) or (probability <= settings.weak_probability and bullish))
    if conflicted:
        risks.append("模型機率與 MA20 趨勢分歧")
    overheated = rsi is not None and rsi >= settings.overbought_rsi
    if overheated:
        risks.append(f"RSI {_display_number(rsi)}，短線偏熱")
    if volume is not None and volume >= settings.unusual_volume_ratio:
        risks.append("量能異常放大")
    elif volume is not None and volume < settings.low_volume_ratio:
        risks.append("量能不足")
    if source.foreign_net_5 is not None and source.foreign_net_5 < 0:
        risks.append("外資近五日賣超")
    if volatility is not None and volatility >= settings.elevated_volatility:
        risks.append("價格波動程度升高")
    if source.market_action == "提高防守" and source.scope != "market":
        risks.append("整體市場目前提高防守")
    if source.near_rotation_boundary:
        risks.append("產業接近輪動分界")
    risks = blockers + risks

    modifier = any((overheated, source.near_rotation_boundary, source.market_action == "提高防守", source.foreign_net_5 is not None and source.foreign_net_5 < 0, volume is not None and volume >= settings.unusual_volume_ratio, volatility is not None and volatility >= settings.elevated_volatility))
    if source.scope == "market":
        if blockers:
            action, level = "控制追價", "insufficient"
        elif probability <= settings.weak_probability or bearish:
            action, level = "提高防守", "bearish"
        elif probability >= settings.bullish_probability and bullish:
            action, level = ("逢回布局", "cautious_bullish") if modifier else ("積極選股", "bullish")
        else:
            action, level = "控制追價", "neutral"
    elif source.scope == "industry":
        if blockers or conflicted:
            action, level = "等待確認", "insufficient" if blockers else "neutral"
        elif probability >= settings.bullish_probability and source.rotation in {"leading", "improving"}:
            action, level = ("分批觀察", "cautious_bullish") if modifier else ("優先關注", "bullish")
        elif probability <= settings.weak_probability and source.rotation in {"weakening", "lagging"}:
            action, level = "暫時避開", "bearish"
        elif probability <= settings.weak_probability or source.rotation in {"weakening", "lagging"}:
            action, level = "降低曝險", "cautious_bearish"
        else:
            action, level = "等待確認", "neutral"
    else:
        if blockers or conflicted:
            action, level = "等待確認", "insufficient" if blockers else "neutral"
        elif probability >= settings.bullish_probability and bullish:
            action, level = ("分批布局", "cautious_bullish") if modifier else ("優先布局", "bullish")
        elif probability <= settings.weak_probability and bearish:
            action, level = "暫時避開", "bearish"
        elif probability <= settings.weak_probability or bearish:
            action, level = "降低部位", "cautious_bearish"
        else:
            action, level = "持有觀察", "neutral"

    headline, suggested, unheld, held = _result_text(
        source.scope, action, conflicted=conflicted, overheated=overheated
    )
    invalidation = []
    if probability is not None and probability >= settings.bullish_probability:
        invalidation.append("五日上漲機率降至 60% 以下")
    if bullish:
        invalidation.append("股價跌破 MA20")
    if not invalidation:
        invalidation.append("模型機率與 MA20 趨勢未重新形成一致")

    return RecommendationResult(
        scope=source.scope,
        entity_id=source.entity_id,
        action=action,
        level=level,
        headline=headline,
        confidence=("可信度低" if blockers else _confidence(source.sample_count, settings)),
        supporting_reasons=tuple(supporting[:4]),
        risk_reasons=tuple(dict.fromkeys(risks)) or ("未觸發額外風險警示",),
        suggested_action=suggested,
        invalidation_conditions=tuple(invalidation),
        unheld_guidance=unheld,
        held_guidance=held,
        data_as_of=source.data_as_of,
        source_metrics={
            "probability": probability,
            "trend": source.trend,
            "rsi": rsi,
            "volume_ratio": volume,
            "foreign_net_5": source.foreign_net_5,
            "volatility": volatility,
            "sample_count": source.sample_count,
            "industry_coverage": coverage,
            "rotation": source.rotation,
            "max_drawdown": source.max_drawdown,
            "strategy_return": source.strategy_return,
            "buy_hold_return": source.buy_hold_return,
        },
    )


def recommend_analysis(
    data: dict[str, Any], *, current_date: datetime.date | None = None
) -> RecommendationResult:
    """將既有 stock analysis payload 映射成唯一推薦輸入。"""
    backtest = data.get("bt") if isinstance(data.get("bt"), dict) else {}
    foreign = (
        data.get("foreign_flow")
        if isinstance(data.get("foreign_flow"), dict)
        else {}
    )
    try:
        data_as_of = datetime.date.fromisoformat(str(data.get("as_of") or ""))
    except ValueError:
        data_as_of = None
    code = str(data.get("code") or "")
    return build_recommendation(
        RecommendationInput(
            scope="market" if code == "TAIEX" else "stock",
            entity_id=code,
            probability=data.get("prob"),
            trend=data.get("trend"),
            data_as_of=data_as_of,
            current_date=current_date or datetime.date.today(),
            rsi=data.get("rsi"),
            volume_ratio=data.get("volume_ratio"),
            foreign_net_5=foreign.get("net_5"),
            volatility=data.get("volatility"),
            sample_count=backtest.get("trades"),
            industry_coverage=data.get("industry_coverage"),
            rotation=data.get("rotation"),
            near_rotation_boundary=data.get("near_rotation_boundary") is True,
            market_action=data.get("market_action"),
            data_quality_warning=data.get("data_quality_warning") is True,
            source_disagreement=data.get("source_disagreement") is True,
            max_drawdown=backtest.get("mdd"),
            strategy_return=backtest.get("strat_cum"),
            buy_hold_return=backtest.get("bh_cum"),
        )
    )
