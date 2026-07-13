"""Analytics Layer：日頻績效、成本前後比較與交易統計。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean, pstdev
from typing import Sequence

from .contracts import DailyLedger, TradeExecution


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """單一 Equity 序列的績效指標。"""

    cumulative_return: float
    annualized_return: float
    maximum_drawdown: float
    sharpe_ratio: float


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """成本前與成本後的日頻績效比較。"""

    before_cost: PerformanceMetrics
    after_cost: PerformanceMetrics
    turnover: float
    trade_count: int
    risk_free_rate: float
    trading_days_per_year: int


def _metrics(
    values: Sequence[float],
    initial_cash: float,
    risk_free_rate: float,
    trading_days_per_year: int,
) -> PerformanceMetrics:
    if not values:
        return PerformanceMetrics(0.0, 0.0, 0.0, 0.0)
    cumulative_return = values[-1] / initial_cash - 1.0
    periods = len(values)
    annualized_return = (
        (values[-1] / initial_cash) ** (trading_days_per_year / periods) - 1.0
        if values[-1] > 0.0
        else -1.0
    )
    peak = initial_cash
    maximum_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        maximum_drawdown = min(maximum_drawdown, value / peak - 1.0)
    returns: list[float] = []
    previous = initial_cash
    for value in values:
        returns.append(value / previous - 1.0)
        previous = value
    daily_risk_free = risk_free_rate / trading_days_per_year
    excess_returns = [value - daily_risk_free for value in returns]
    deviation = pstdev(excess_returns) if len(excess_returns) > 1 else 0.0
    sharpe_ratio = (
        fmean(excess_returns) / deviation * math.sqrt(trading_days_per_year)
        if deviation > 0.0
        else 0.0
    )
    return PerformanceMetrics(
        cumulative_return=cumulative_return,
        annualized_return=annualized_return,
        maximum_drawdown=maximum_drawdown,
        sharpe_ratio=sharpe_ratio,
    )


def build_performance_report(
    ledgers: Sequence[DailyLedger],
    executions: Sequence[TradeExecution],
    *,
    initial_cash: float,
    risk_free_rate: float = 0.0,
    trading_days_per_year: int = 252,
) -> PerformanceReport:
    """以 252 個交易日與年化無風險利率為預設日頻假設。"""
    if initial_cash <= 0.0 or trading_days_per_year <= 0:
        raise ValueError("績效報告設定不合法")
    ordered = tuple(sorted(ledgers, key=lambda item: item.valuation_time))
    if tuple(ledgers) != ordered:
        raise ValueError("DailyLedger 必須依時間排序")
    net_equity = [item.equity for item in ordered]
    gross_equity = [item.gross_equity for item in ordered]
    average_equity = fmean(net_equity) if net_equity else initial_cash
    turnover = (
        sum(execution.notional for execution in executions) / average_equity
        if average_equity > 0.0
        else 0.0
    )
    return PerformanceReport(
        before_cost=_metrics(
            gross_equity, initial_cash, risk_free_rate, trading_days_per_year
        ),
        after_cost=_metrics(
            net_equity, initial_cash, risk_free_rate, trading_days_per_year
        ),
        turnover=turnover,
        trade_count=len(executions),
        risk_free_rate=risk_free_rate,
        trading_days_per_year=trading_days_per_year,
    )
