import datetime
import math
import statistics
from collections import defaultdict

from .config import ReportConfig
from .schemas import IndustryBacktestResult, StockSnapshot, finite_number
from stock_papi.quant.backtest import summarize_trade_returns


def _date(row: dict) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(row.get("Date") or "").split("T", 1)[0])
    except ValueError:
        return None


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def _curve(returns: list[float]) -> list[float]:
    equity = 1.0
    values = []
    for value in returns:
        equity *= 1.0 + value
        values.append(equity)
    return values


def _drawdowns(curve: list[float]) -> list[float]:
    peak = 1.0
    result = []
    for equity in curve:
        peak = max(peak, equity)
        result.append(equity / peak - 1.0)
    return result


def _market_forward_return(
    dates: list[datetime.date],
    start: int,
    horizon: int,
    factors: dict[datetime.date, list[float]],
) -> float:
    values = []
    for day in dates[start + 1 : start + horizon + 1]:
        observations = factors.get(day, [])
        if not observations:
            return 0.0
        values.append(statistics.median(observations))
    return _compound(values)


def backtest_industry(
    industry: str,
    stocks: list[StockSnapshot],
    config: ReportConfig | None = None,
    *,
    market_stocks: list[StockSnapshot] | None = None,
) -> IndustryBacktestResult:
    """以統一交易日曆建立五日、等權、非重疊的產業回測。"""
    settings = config or ReportConfig()
    rows_by_symbol: dict[str, dict[datetime.date, dict]] = {}
    calendar = set()
    for stock in stocks:
        rows = {}
        for row in stock.daily:
            day = _date(row)
            if day is not None:
                rows[day] = row
                calendar.add(day)
        rows_by_symbol[stock.symbol] = rows
    dates = sorted(calendar)

    factor_rows: dict[datetime.date, list[float]] = defaultdict(list)
    for stock in market_stocks or stocks:
        for row in stock.daily:
            day = _date(row)
            value = finite_number(row.get("MARKET_RET_1"))
            if day is not None and value is not None:
                factor_rows[day].append(value)

    period_returns: list[float] = []
    buy_hold_returns: list[float] = []
    market_returns: list[float] = []
    rebalance_dates: list[datetime.date] = []
    positions: list[int] = []
    gross_period_returns: list[float | None] = []
    valid_signals = 0
    observed_oos = False
    coverage_values = []
    horizon = settings.prediction_horizon

    for index in range(0, max(0, len(dates) - horizon), horizon):
        day = dates[index]
        future_day = dates[index + horizon]
        complete = []
        available_probabilities = []
        for stock in stocks:
            current = rows_by_symbol.get(stock.symbol, {}).get(day)
            future = rows_by_symbol.get(stock.symbol, {}).get(future_day)
            current_close = finite_number((current or {}).get("Close"))
            future_close = finite_number((future or {}).get("Close"))
            if current_close is None or future_close is None or current_close <= 0:
                continue
            probability = finite_number(current.get("AI_P"))
            complete.append((stock, current_close, future_close, probability))
            if probability is not None:
                available_probabilities.append(probability)
        coverage_values.append(len(complete) / len(stocks) if stocks else 0.0)
        if available_probabilities:
            observed_oos = True
        if not observed_oos or not complete:
            continue

        selected_returns = [
            future / current - 1.0
            for _stock, current, future, probability in complete
            if probability is not None and probability >= settings.entry_threshold
        ]
        benchmark_returns = [future / current - 1.0 for _stock, current, future, _p in complete]
        position_count = len(selected_returns)
        strategy_return = (
            statistics.fmean(selected_returns) - settings.round_trip_cost
            if selected_returns
            else 0.0
        )
        gross_period_returns.append(
            statistics.fmean(selected_returns) if selected_returns else None
        )
        period_returns.append(strategy_return)
        buy_hold_returns.append(statistics.fmean(benchmark_returns))
        market_returns.append(_market_forward_return(dates, index, horizon, factor_rows))
        rebalance_dates.append(day)
        positions.append(position_count)
        valid_signals += position_count

    periods = len(period_returns)
    sufficient = periods >= settings.min_backtest_periods
    entry_returns = [
        value for value, count in zip(period_returns, positions) if count > 0
    ]
    entry_periods = len(entry_returns)
    winning_periods = sum(value > 0 for value in entry_returns)
    losing_periods = entry_periods - winning_periods
    cash_periods = periods - entry_periods
    all_cash = periods > 0 and entry_periods == 0
    if periods < 12:
        sample_quality = "資料不足"
    elif periods < 24:
        sample_quality = "低樣本"
    elif periods < 48:
        sample_quality = "中等樣本"
    else:
        sample_quality = "較完整樣本"
    strategy_curve = _curve(period_returns)
    buy_hold_curve = _curve(buy_hold_returns)
    market_curve = _curve(market_returns)
    drawdowns = _drawdowns(strategy_curve)
    average_positions = statistics.fmean(positions) if positions else None
    cash_ratio = positions.count(0) / periods if periods else None
    coverage = statistics.fmean(coverage_values) if coverage_values else None
    trade_summary = summarize_trade_returns(
        entry_returns,
        gross_period_returns=gross_period_returns,
        round_trip_cost=settings.round_trip_cost,
        total_periods=periods,
    )
    yearly_periods: dict[int, list[float]] = defaultdict(list)
    for day, value in zip(rebalance_dates, period_returns):
        yearly_periods[day.year].append(value)
    yearly_returns = {
        year: _compound(values) for year, values in sorted(yearly_periods.items())
    }

    if sufficient:
        buy_hold = _compound(buy_hold_returns)
        market = _compound(market_returns)
    else:
        buy_hold = market = None

    if sufficient and not all_cash:
        cumulative = _compound(period_returns)
        annualization = 252 / horizon
        mean_return = statistics.fmean(period_returns)
        volatility = statistics.pstdev(period_returns) if periods > 1 else 0.0
        downside = [value for value in period_returns if value < 0]
        downside_deviation = statistics.pstdev(downside) if len(downside) > 1 else 0.0
        annualized_return = (
            (1.0 + cumulative) ** (annualization / periods) - 1.0
            if 1.0 + cumulative > 0
            else -1.0
        )
        annualized_volatility = volatility * math.sqrt(annualization)
        sharpe = mean_return / volatility * math.sqrt(annualization) if volatility else None
        sortino = (
            mean_return / downside_deviation * math.sqrt(annualization)
            if downside_deviation
            else None
        )
        win_rate = winning_periods / entry_periods
        max_drawdown = min(drawdowns, default=0.0)
        excess = cumulative - market
    else:
        cumulative = annualized_return = annualized_volatility = None
        max_drawdown = sharpe = sortino = win_rate = None
        excess = None

    return IndustryBacktestResult(
        industry=industry,
        sufficient=sufficient,
        start_date=rebalance_dates[0] if rebalance_dates else None,
        end_date=rebalance_dates[-1] if rebalance_dates else None,
        rebalance_dates=rebalance_dates,
        period_returns=period_returns,
        buy_hold_period_returns=buy_hold_returns,
        market_period_returns=market_returns,
        strategy_curve=strategy_curve,
        buy_hold_curve=buy_hold_curve,
        market_curve=market_curve,
        drawdown_curve=drawdowns,
        valid_signals=valid_signals,
        cumulative_return=cumulative,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        sortino=sortino,
        win_rate=win_rate,
        average_positions=average_positions,
        cash_period_ratio=cash_ratio,
        buy_hold_return=buy_hold,
        market_return=market,
        excess_return=excess,
        coverage=coverage,
        rebalance_periods=periods,
        entry_periods=entry_periods,
        winning_periods=winning_periods,
        losing_periods=losing_periods,
        cash_periods=cash_periods,
        sample_quality=sample_quality,
        low_sample_warning=12 <= periods < 24,
        all_cash=all_cash,
        strategy_status=("全程空手" if all_cash else "有進場" if entry_periods else "資料不足"),
        average_profit=trade_summary["average_profit"],
        average_loss=trade_summary["average_loss"],
        expected_return=trade_summary["expected_return"],
        payoff_ratio=trade_summary["payoff_ratio"],
        profit_factor=trade_summary["profit_factor"],
        longest_winning_streak=trade_summary["longest_winning_streak"],
        longest_losing_streak=trade_summary["longest_losing_streak"],
        cost_sensitivity=trade_summary["cost_sensitivity"],
        yearly_returns=yearly_returns,
    )
