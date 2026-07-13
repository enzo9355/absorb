import datetime
import statistics
from collections import Counter, defaultdict

from .config import ReportConfig
from .industry_backtest import backtest_industry
from .schemas import (
    DailyIndustryReport,
    IndustrySnapshot,
    LoadedReportSource,
    MarketSnapshot,
    ModelQualitySnapshot,
    StockSnapshot,
    finite_number,
)
from .summaries import deterministic_summary


ROTATION_LABELS = {
    "leading": "領先",
    "improving": "改善",
    "weakening": "衰退",
    "lagging": "落後",
    "insufficient": "資料不足",
}

ROTATION_NEUTRAL_THRESHOLD_PCT = 0.20


def classify_rotation(relative_5d: float, relative_20d: float) -> str:
    """依五日與二十日相對報酬分類輪動階段。"""
    if relative_5d > 0 and relative_20d > 0:
        return "leading"
    if relative_5d > 0 and relative_20d <= 0:
        return "improving"
    if relative_5d <= 0 and relative_20d > 0:
        return "weakening"
    return "lagging"


def is_near_rotation_boundary(
    relative_5d: float,
    relative_20d: float,
    threshold: float = ROTATION_NEUTRAL_THRESHOLD_PCT / 100,
) -> bool:
    """任一相對報酬落在正負中性帶時，標示接近分界。"""
    return abs(relative_5d) <= threshold or abs(relative_20d) <= threshold


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _ratio(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _stock_return(stock: StockSnapshot, periods: int) -> float | None:
    if len(stock.daily) <= periods:
        return None
    latest = finite_number(stock.daily[-1].get("Close"))
    earlier = finite_number(stock.daily[-1 - periods].get("Close"))
    if latest is None or earlier is None or earlier <= 0:
        return None
    return latest / earlier - 1.0


def _foreign_net_5(stock: StockSnapshot) -> float | None:
    values = [
        value
        for value in (
            finite_number(row.get("ForeignNet")) for row in stock.daily[-5:]
        )
        if value is not None
    ]
    return sum(values) if values else None


def _industry_sample_quality(samples: int) -> str:
    if samples <= 2:
        return "極小樣本"
    if samples <= 4:
        return "小樣本"
    return "一般樣本"


def _signal_profile(probability: float | None, rotation: str, config: ReportConfig) -> str:
    if probability is None or rotation == "insufficient":
        return "資料不足"
    if probability >= config.entry_threshold:
        return {
            "leading": "趨勢延續",
            "improving": "轉強觀察",
            "weakening": "動能分歧",
            "lagging": "反轉觀察",
        }[rotation]
    if probability <= config.weak_threshold:
        return {
            "leading": "轉弱風險",
            "improving": "訊號分歧",
            "weakening": "弱勢觀察",
            "lagging": "弱勢延續",
        }[rotation]
    return "中性觀察"


def _ma20_status(close: float | None, ma20: float | None, config: ReportConfig) -> str:
    if close is None or ma20 is None or ma20 <= 0:
        return "資料不足"
    if abs(close / ma20 - 1.0) <= config.ma_near_threshold:
        return "接近 MA20"
    return "站上 MA20" if close > ma20 else "跌破 MA20"


def _market_snapshot(
    stocks: list[StockSnapshot], config: ReportConfig, as_of: datetime.date
) -> tuple[MarketSnapshot, list[str]]:
    warnings = []
    returns: dict[int, float | None] = {}
    for periods, field in ((1, "MARKET_RET_1"), (5, "MARKET_RET_5"), (20, "MARKET_RET_20")):
        values = [finite_number(stock.latest.get(field)) for stock in stocks]
        finite = [value for value in values if value is not None]
        returns[periods] = statistics.median(finite) if finite else None
        if finite and max(finite) - min(finite) > config.market_factor_tolerance:
            warnings.append(f"{field} 市場因子在股票間差異過大。")

    by_date: dict[str, list[float]] = defaultdict(list)
    for stock in stocks:
        for row in stock.daily:
            date_text = str(row.get("Date") or "").split("T", 1)[0]
            value = finite_number(row.get("MARKET_RET_1"))
            if date_text and value is not None:
                by_date[date_text].append(value)
    daily_market = [statistics.median(by_date[key]) for key in sorted(by_date)[-60:]]
    if len(daily_market) >= 60:
        equity = 1.0
        for value in daily_market:
            equity *= 1.0 + value
        returns[60] = equity - 1.0
    else:
        returns[60] = None

    probabilities = [finite_number(stock.latest.get("AI_P")) for stock in stocks]
    probabilities = [value for value in probabilities if value is not None]
    breadth = []
    ma60_breadth = []
    high_scores = []
    data_warnings = []
    option_missing = []
    volatilities = []
    volume_ratios = []
    advancing = declining = new_highs = new_lows = 0
    for stock in stocks:
        close = finite_number(stock.latest.get("Close"))
        ma20 = finite_number(stock.latest.get("MA20"))
        ma60 = finite_number(stock.latest.get("MA60"))
        probability = finite_number(stock.latest.get("AI_P"))
        if close is not None and ma20 is not None:
            breadth.append(close > ma20)
        if close is not None and ma60 is not None:
            ma60_breadth.append(close > ma60)
        if probability is not None:
            high_scores.append(probability >= config.entry_threshold)
        warning = finite_number(stock.latest.get("DATA_PRICE_WARNING"))
        missing = finite_number(stock.latest.get("OPTION_DATA_MISSING"))
        volatility = finite_number(stock.latest.get("MARKET_VOL_20"))
        if warning is not None:
            data_warnings.append(warning > 0)
        if missing is not None:
            option_missing.append(missing > 0)
        if volatility is not None:
            volatilities.append(volatility)
        volume_ratio = finite_number(stock.latest.get("VOL_RATIO"))
        if volume_ratio is not None:
            volume_ratios.append(volume_ratio)
        return_1d = _stock_return(stock, 1)
        if return_1d is not None:
            if return_1d > 0:
                advancing += 1
            elif return_1d < 0:
                declining += 1
        closes = [
            value
            for value in (finite_number(row.get("Close")) for row in stock.daily[-20:])
            if value is not None
        ]
        if close is not None and len(closes) >= 20:
            new_highs += close >= max(closes)
            new_lows += close <= min(closes)

    change_keys = (
        "return_1d", "return_5d", "return_20d", "return_60d",
        "volatility_20d", "bullish_breadth", "ma60_breadth",
        "high_score_ratio", "advancing_count", "declining_count",
        "new_high_20d_count", "new_low_20d_count", "average_volume_ratio",
    )

    return MarketSnapshot(
        returns=returns,
        volatility_20d=statistics.median(volatilities) if volatilities else None,
        average_probability=_mean(probabilities),
        bullish_breadth=_ratio(breadth),
        ma60_breadth=_ratio(ma60_breadth),
        high_score_ratio=_ratio(high_scores),
        advancing_count=advancing,
        declining_count=declining,
        new_high_20d_count=new_highs,
        new_low_20d_count=new_lows,
        average_volume_ratio=_mean(volume_ratios),
        model_versions=dict(Counter(stock.model_version for stock in stocks)),
        data_warning_ratio=_ratio(data_warnings),
        option_missing_ratio=_ratio(option_missing),
        freshness_days=max(0, (datetime.date.today() - as_of).days),
        changes={key: None for key in change_keys},
    ), warnings


def _industry_snapshot(
    name: str,
    components: list[str],
    stock_by_symbol: dict[str, StockSnapshot],
    market: MarketSnapshot,
    config: ReportConfig,
) -> IndustrySnapshot:
    stocks = [stock_by_symbol[symbol] for symbol in components if symbol in stock_by_symbol]
    returns = {}
    samples = {}
    for periods in (1, 5, 20, 60):
        values = [_stock_return(stock, periods) for stock in stocks]
        finite = [value for value in values if value is not None]
        returns[periods] = _mean(finite)
        samples[periods] = len(finite)
    probabilities = [finite_number(stock.latest.get("AI_P")) for stock in stocks]
    probabilities = [value for value in probabilities if value is not None]
    breadth = []
    volumes = []
    institutions = []
    for stock in stocks:
        close = finite_number(stock.latest.get("Close"))
        ma20 = finite_number(stock.latest.get("MA20"))
        if close is not None and ma20 is not None:
            breadth.append(close > ma20)
        volume = finite_number(stock.latest.get("VOL_RATIO"))
        institution = finite_number(stock.latest.get("INST_NET_RATIO"))
        if volume is not None:
            volumes.append(volume)
        if institution is not None:
            institutions.append(institution)
    relative_5d = (
        returns[5] - market.returns[5]
        if returns[5] is not None and market.returns[5] is not None
        else None
    )
    relative_20d = (
        returns[20] - market.returns[20]
        if returns[20] is not None and market.returns[20] is not None
        else None
    )
    rotation = (
        classify_rotation(relative_5d, relative_20d)
        if relative_5d is not None and relative_20d is not None
        else "insufficient"
    )
    average_probability = _mean(probabilities)
    near_boundary = (
        is_near_rotation_boundary(
            relative_5d,
            relative_20d,
            config.rotation_neutral_threshold_pct / 100,
        )
        if relative_5d is not None and relative_20d is not None
        else False
    )
    return IndustrySnapshot(
        name=name,
        symbols=[stock.symbol for stock in stocks],
        component_count=len(components),
        coverage=len(stocks) / len(components) if components else 0.0,
        returns=returns,
        valid_samples=samples,
        relative_return_5d=relative_5d,
        relative_return_20d=relative_20d,
        rotation=rotation,
        average_probability=average_probability,
        median_probability=statistics.median(probabilities) if probabilities else None,
        bullish_breadth=_ratio(breadth),
        high_score_ratio=_ratio([value >= config.entry_threshold for value in probabilities]),
        average_volume_ratio=_mean(volumes),
        average_institution_ratio=_mean(institutions),
        model_versions=dict(Counter(stock.model_version for stock in stocks)),
        rank=0,
        previous_rank=None,
        rank_change=None,
        probability_change=None,
        previous_rotation=None,
        rotation_changed=None,
        sample_quality=_industry_sample_quality(len(probabilities)),
        near_boundary=near_boundary,
        signal_profile=_signal_profile(average_probability, rotation, config),
    )


def _risk_hints(stock: StockSnapshot, coverage: float, config: ReportConfig) -> list[str]:
    latest = stock.latest
    hints = []
    rsi = finite_number(latest.get("RSI"))
    close = finite_number(latest.get("Close"))
    ma20 = finite_number(latest.get("MA20"))
    volume = finite_number(latest.get("VOL_RATIO"))
    foreign = _foreign_net_5(stock)
    if rsi is not None and rsi >= 70:
        hints.append("RSI 過熱")
    elif rsi is not None and rsi <= 30:
        hints.append("RSI 超賣")
    trend = _ma20_status(close, ma20, config)
    if trend == "跌破 MA20":
        hints.append("跌破 MA20")
    if volume is not None and volume >= 2.0:
        hints.append("量能異常放大")
    elif volume is not None and volume < 0.8:
        hints.append("量能不足")
    if foreign is not None and foreign < 0:
        hints.append("外資近五日賣超")
    volatility = finite_number(latest.get("MARKET_VOL_20"))
    if volatility is not None and volatility >= 0.03:
        hints.append("波動率升高")
    if (finite_number(latest.get("DATA_PRICE_WARNING")) or 0) > 0:
        hints.append("資料源價差警示")
    probability = finite_number(latest.get("AI_P"))
    if probability is not None and (
        (probability >= config.entry_threshold and trend == "跌破 MA20")
        or (probability <= config.weak_threshold and trend == "站上 MA20")
    ):
        hints.append("模型機率與近期趨勢分歧")
    if coverage < 0.8:
        hints.append("產業樣本偏少")
    return hints or ["未觸發額外風險警示"]


def _model_quality(stocks: list[StockSnapshot], config: ReportConfig) -> ModelQualitySnapshot:
    observations: list[tuple[float, int]] = []
    horizon = config.prediction_horizon
    for stock in stocks:
        rows = stock.daily
        for index in range(max(0, len(rows) - horizon)):
            probability = finite_number(rows[index].get("AI_P"))
            current = finite_number(rows[index].get("Close"))
            future = finite_number(rows[index + horizon].get("Close"))
            if probability is None or current is None or future is None or current <= 0:
                continue
            observations.append((probability / 100.0, int(future > current)))
    if not observations:
        return ModelQualitySnapshot(0, None, None, 0, None, [])
    correct = [int((probability >= 0.5) == bool(actual)) for probability, actual in observations]
    high_scores = [actual for probability, actual in observations if probability >= config.entry_threshold / 100]
    bins = []
    for lower in range(0, 100, 10):
        bucket = [
            (probability, actual)
            for probability, actual in observations
            if lower / 100 <= probability < (lower + 10) / 100
            or (lower == 90 and probability == 1.0)
        ]
        if bucket:
            bins.append({
                "range": f"{lower}-{lower + 10}%",
                "samples": len(bucket),
                "average_probability": statistics.fmean(item[0] for item in bucket),
                "actual_up_rate": statistics.fmean(item[1] for item in bucket),
            })
    return ModelQualitySnapshot(
        pooled_oos_samples=len(observations),
        direction_accuracy=statistics.fmean(correct),
        brier_score=statistics.fmean(
            (probability - actual) ** 2 for probability, actual in observations
        ),
        high_score_samples=len(high_scores),
        high_score_win_rate=statistics.fmean(high_scores) if high_scores else None,
        calibration_bins=bins,
    )


def build_daily_report(
    source: LoadedReportSource,
    industry_map: dict[str, list[str]],
    config: ReportConfig | None = None,
    *,
    previous_source: LoadedReportSource | None = None,
) -> DailyIndustryReport:
    """將已驗證股票快照轉換成完整產業分析與回測資料。"""
    settings = config or ReportConfig()
    market, warnings = _market_snapshot(
        source.stocks, settings, source.manifest.market_as_of
    )
    stock_by_symbol = {stock.symbol: stock for stock in source.stocks}

    def industry_snapshots(
        stocks: dict[str, StockSnapshot], snapshot: MarketSnapshot
    ) -> list[IndustrySnapshot]:
        items = []
        for name, raw_components in industry_map.items():
            if name in {"全市場", "ETF專區"}:
                continue
            components = [str(symbol) for symbol in raw_components]
            if components:
                items.append(
                    _industry_snapshot(name, components, stocks, snapshot, settings)
                )
        items.sort(
            key=lambda item: (
                item.average_probability is not None,
                item.average_probability or float("-inf"),
                item.name,
            ),
            reverse=True,
        )
        for rank, item in enumerate(items, 1):
            item.rank = rank
        return items

    industries = industry_snapshots(stock_by_symbol, market)
    previous_by_symbol: dict[str, StockSnapshot] = {}
    previous_industries: list[IndustrySnapshot] = []
    if previous_source is not None:
        previous_market, previous_warnings = _market_snapshot(
            previous_source.stocks,
            settings,
            previous_source.manifest.market_as_of,
        )
        previous_by_symbol = {
            stock.symbol: stock for stock in previous_source.stocks
        }
        previous_industries = industry_snapshots(previous_by_symbol, previous_market)
        warnings.extend(f"前期：{item}" for item in previous_warnings)
        current_values = {
            "return_1d": market.returns[1],
            "return_5d": market.returns[5],
            "return_20d": market.returns[20],
            "return_60d": market.returns[60],
            "volatility_20d": market.volatility_20d,
            "bullish_breadth": market.bullish_breadth,
            "ma60_breadth": market.ma60_breadth,
            "high_score_ratio": market.high_score_ratio,
            "advancing_count": market.advancing_count,
            "declining_count": market.declining_count,
            "new_high_20d_count": market.new_high_20d_count,
            "new_low_20d_count": market.new_low_20d_count,
            "average_volume_ratio": market.average_volume_ratio,
        }
        previous_values = {
            "return_1d": previous_market.returns[1],
            "return_5d": previous_market.returns[5],
            "return_20d": previous_market.returns[20],
            "return_60d": previous_market.returns[60],
            "volatility_20d": previous_market.volatility_20d,
            "bullish_breadth": previous_market.bullish_breadth,
            "ma60_breadth": previous_market.ma60_breadth,
            "high_score_ratio": previous_market.high_score_ratio,
            "advancing_count": previous_market.advancing_count,
            "declining_count": previous_market.declining_count,
            "new_high_20d_count": previous_market.new_high_20d_count,
            "new_low_20d_count": previous_market.new_low_20d_count,
            "average_volume_ratio": previous_market.average_volume_ratio,
        }
        market.changes = {
            key: (
                current_values[key] - previous_values[key]
                if current_values[key] is not None and previous_values[key] is not None
                else None
            )
            for key in current_values
        }
        previous_industry_map = {item.name: item for item in previous_industries}
        for item in industries:
            previous = previous_industry_map.get(item.name)
            if previous is None:
                continue
            item.previous_rank = previous.rank
            item.rank_change = previous.rank - item.rank
            item.probability_change = (
                item.average_probability - previous.average_probability
                if item.average_probability is not None
                and previous.average_probability is not None
                else None
            )
            item.previous_rotation = previous.rotation
            item.rotation_changed = previous.rotation != item.rotation

    backtests = [
        backtest_industry(
            item.name,
            [stock_by_symbol[symbol] for symbol in item.symbols],
            settings,
            market_stocks=source.stocks,
        )
        for item in industries
    ]

    memberships: dict[str, list[str]] = defaultdict(list)
    coverages = {}
    for industry in industries:
        coverages[industry.name] = industry.coverage
        for symbol in industry.symbols:
            memberships[symbol].append(industry.name)
    candidates = []
    for stock in source.stocks:
        probability = finite_number(stock.latest.get("AI_P"))
        if probability is None:
            continue
        industry_names = memberships.get(stock.symbol, [])
        coverage = min((coverages[name] for name in industry_names), default=0.0)
        close = finite_number(stock.latest.get("Close"))
        ma20 = finite_number(stock.latest.get("MA20"))
        previous_stock = previous_by_symbol.get(stock.symbol)
        previous_probability = (
            finite_number(previous_stock.latest.get("AI_P"))
            if previous_stock is not None
            else None
        )
        candidates.append({
            "symbol": stock.symbol,
            "name": stock.name,
            "industries": industry_names,
            "probability": probability,
            "previous_probability": previous_probability,
            "probability_change": (
                probability - previous_probability
                if previous_probability is not None
                else None
            ),
            "new_high_score": (
                previous_probability is not None
                and previous_probability < settings.entry_threshold <= probability
            ),
            "exited_high_score": (
                previous_probability is not None
                and probability < settings.entry_threshold <= previous_probability
            ),
            "trend": _ma20_status(close, ma20, settings),
            "return_5d": _stock_return(stock, 5),
            "rsi": finite_number(stock.latest.get("RSI")),
            "volume_ratio": finite_number(stock.latest.get("VOL_RATIO")),
            "foreign_net_5": _foreign_net_5(stock),
            "risks": _risk_hints(stock, coverage, settings),
            "as_of": stock.as_of.isoformat(),
        })
    candidates.sort(key=lambda item: (item["probability"], item["symbol"]), reverse=True)
    current_high_scores = {
        stock.symbol
        for stock in source.stocks
        if (finite_number(stock.latest.get("AI_P")) or float("-inf"))
        >= settings.entry_threshold
    }
    previous_high_scores = {
        stock.symbol
        for stock in previous_source.stocks
        if (finite_number(stock.latest.get("AI_P")) or float("-inf"))
        >= settings.entry_threshold
    } if previous_source is not None else set()
    bullish_industries = [
        item
        for item in industries
        if item.average_probability is not None
        and item.average_probability >= settings.entry_threshold
    ]
    weak_industries = [
        item
        for item in reversed(industries)
        if item.average_probability is not None
        and item.average_probability <= settings.weak_threshold
    ]
    comparison_available = previous_source is not None
    new_high_scores = sorted(current_high_scores - previous_high_scores) if comparison_available else []
    exited_high_scores = sorted(previous_high_scores - current_high_scores) if comparison_available else []
    summary = deterministic_summary(
        market,
        industries,
        bullish_industries,
        weak_industries,
        warnings,
        comparison_available=comparison_available,
        new_high_scores=new_high_scores,
        exited_high_scores=exited_high_scores,
    )
    return DailyIndustryReport(
        source=source,
        report_date=source.manifest.market_as_of,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        market=market,
        industries=industries,
        backtests=backtests,
        model_quality=_model_quality(source.stocks, settings),
        watchlist=candidates[: settings.max_watchlist],
        bullish_industries=bullish_industries,
        weak_industries=weak_industries,
        comparison_available=comparison_available,
        new_high_score_symbols=new_high_scores,
        exited_high_score_symbols=exited_high_scores,
        summary=summary,
        warnings=warnings,
    )
