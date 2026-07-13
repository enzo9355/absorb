"""六層回測調度器與新舊訊號 Shadow 比對。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest
from typing import Sequence

from .analytics import PerformanceReport, build_performance_report
from .contracts import (
    BacktestConfig,
    DailyLedger,
    ExecutionStatus,
    ExecutionModel,
    FeatureBuilder,
    FeatureFrame,
    MarketBar,
    Order,
    OrderSide,
    Signal,
    SignalAction,
    SignalProvider,
    TimedObservation,
    TradeExecution,
    TradingStatus,
    PortfolioState,
    require_timezone,
)
from .data import bars_available_until
from .portfolio import PortfolioBook


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """一次 cutoff 回放的全部可追溯輸出。"""

    features: FeatureFrame
    signals: tuple[Signal, ...]
    orders: tuple[Order, ...]
    fills: tuple[TradeExecution, ...]
    rejections: tuple[TradeExecution, ...]
    daily_ledger: tuple[DailyLedger, ...]
    final_state: PortfolioState
    report: PerformanceReport


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """新舊訊號層的比對結果，成交與績效另行比較。"""

    matched: bool
    mismatches: tuple[str, ...]


def compare_shadow_signals(
    legacy_signals: Sequence[Signal], shadow_signals: Sequence[Signal]
) -> ShadowComparison:
    """先比對日期、方向、機率與版本，避免直接拿績效掩蓋訊號差異。"""
    mismatches: list[str] = []
    for index, pair in enumerate(zip_longest(legacy_signals, shadow_signals)):
        legacy, shadow = pair
        if legacy == shadow:
            continue
        if legacy is None or shadow is None:
            mismatches.append(f"第 {index} 筆訊號數量不一致")
            continue
        if (
            legacy.symbol,
            legacy.signal_time,
            legacy.action,
            legacy.signal_value,
            legacy.model_version,
            legacy.feature_version,
        ) != (
            shadow.symbol,
            shadow.signal_time,
            shadow.action,
            shadow.signal_value,
            shadow.model_version,
            shadow.feature_version,
        ):
            mismatches.append(f"第 {index} 筆訊號內容不一致")
    return ShadowComparison(matched=not mismatches, mismatches=tuple(mismatches))


class BacktestEngine:
    """依 Data -> Feature -> Signal -> Execution -> Portfolio -> Analytics 調度。"""

    def __init__(
        self,
        feature_builder: FeatureBuilder,
        signal_provider: SignalProvider,
        execution_model: ExecutionModel,
        config: BacktestConfig,
    ) -> None:
        self._feature_builder = feature_builder
        self._signal_provider = signal_provider
        self._execution_model = execution_model
        self._config = config

    def run(
        self,
        *,
        bars: Sequence[MarketBar],
        cutoff: datetime,
        observations: Sequence[TimedObservation] = (),
    ) -> BacktestResult:
        require_timezone(cutoff, "cutoff")
        available_bars = bars_available_until(bars, cutoff)
        features = self._feature_builder.build(available_bars, observations, cutoff)
        signals = self._signal_provider.generate(features)
        if tuple(sorted(signals, key=lambda signal: signal.signal_time)) != signals:
            raise ValueError("SignalProvider 必須依 signal_time 排序")
        started_at = available_bars[0].market_time if available_bars else cutoff
        portfolio = PortfolioBook(self._config.initial_cash, started_at)
        orders: list[Order] = []
        fills: list[TradeExecution] = []
        rejections: list[TradeExecution] = []
        ledgers: list[DailyLedger] = []
        pending_orders: list[Order] = []
        last_valid_closes: dict[str, float] = {}
        signal_index = 0

        for bar in available_bars:
            while (
                signal_index < len(signals)
                and signals[signal_index].signal_time <= bar.data_available_time
            ):
                signal = signals[signal_index]
                signal_index += 1
                order = self._order_from_signal(signal)
                if order is not None:
                    orders.append(order)
                    pending_orders.append(order)

            still_pending: list[Order] = []
            for order in pending_orders:
                if bar.tradable_at <= order.order_time:
                    still_pending.append(order)
                    continue
                execution = self._execution_model.execute(order, bar)
                if execution is None:
                    still_pending.append(order)
                    continue
                if execution.status is ExecutionStatus.REJECTED:
                    rejections.append(execution)
                    continue
                portfolio.apply(execution)
                fills.append(execution)
            pending_orders = still_pending
            if bar.status is TradingStatus.NORMAL and bar.volume > 0.0:
                last_valid_closes[bar.symbol] = bar.close_price
            if bar.status is TradingStatus.DELISTED:
                last_close = last_valid_closes.get(bar.symbol)
                if last_close is not None:
                    settlement = portfolio.force_close_delisted(
                        bar.symbol,
                        last_close,
                        bar.market_time,
                        bar.data_available_time,
                    )
                    if settlement is not None:
                        fills.append(settlement)
            ledgers.append(
                portfolio.mark_to_market(
                    {bar.symbol: bar.close_price}, bar.data_available_time
                )
            )

        report = build_performance_report(
            ledgers,
            fills,
            initial_cash=self._config.initial_cash,
            risk_free_rate=self._config.risk_free_rate,
            trading_days_per_year=self._config.trading_days_per_year,
        )
        return BacktestResult(
            features=features,
            signals=signals,
            orders=tuple(orders),
            fills=tuple(fills),
            rejections=tuple(rejections),
            daily_ledger=tuple(ledgers),
            final_state=portfolio.state,
            report=report,
        )

    def _order_from_signal(self, signal: Signal) -> Order | None:
        if signal.action is SignalAction.HOLD:
            return None
        side = OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL
        return Order(
            symbol=signal.symbol,
            order_time=signal.signal_time,
            signal_time=signal.signal_time,
            data_available_time=signal.data_available_time,
            side=side,
            requested_quantity=self._config.requested_quantity,
            volatility=0.0,
            reason=f"{signal.model_version}:{signal.feature_version}",
        )
