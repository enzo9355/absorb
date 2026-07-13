"""Portfolio Layer：只根據確認成交更新多頭現金帳戶。"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from .contracts import (
    DailyLedger,
    ExecutionStatus,
    OrderSide,
    PortfolioState,
    TradeExecution,
    require_timezone,
)


class PortfolioBook:
    """以不可變狀態快照管理現金、部位與損益。"""

    def __init__(self, initial_cash: float, started_at: datetime) -> None:
        require_timezone(started_at, "started_at")
        self._state = PortfolioState(
            cash=initial_cash,
            positions={},
            average_costs={},
            equity=initial_cash,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            cumulative_costs=0.0,
            updated_at=started_at,
        )

    @property
    def state(self) -> PortfolioState:
        return self._state

    def apply(self, execution: TradeExecution) -> PortfolioState:
        """只接受成交結果，未成交訂單永遠不會進入這個方法。"""
        if execution.status is not ExecutionStatus.FILLED:
            raise ValueError("Portfolio 不可套用拒絕訂單")
        positions = dict(self._state.positions)
        average_costs = dict(self._state.average_costs)
        quantity = positions.get(execution.symbol, 0.0)
        average_cost = average_costs.get(execution.symbol, 0.0)
        total_cost = execution.notional + execution.commission + execution.tax
        cash = self._state.cash
        realized_pnl = self._state.realized_pnl

        if execution.side is OrderSide.BUY:
            if total_cost > cash + 1e-9:
                raise ValueError("現金不足，拒絕產生負現金")
            new_quantity = quantity + execution.filled_quantity
            average_costs[execution.symbol] = (
                quantity * average_cost + total_cost
            ) / new_quantity
            positions[execution.symbol] = new_quantity
            cash -= total_cost
        else:
            if execution.filled_quantity > quantity + 1e-9:
                raise ValueError("未開放放空，賣出數量不可超過既有部位")
            proceeds = execution.notional - execution.commission - execution.tax
            realized_pnl += proceeds - average_cost * execution.filled_quantity
            new_quantity = quantity - execution.filled_quantity
            cash += proceeds
            if new_quantity <= 1e-9:
                positions.pop(execution.symbol, None)
                average_costs.pop(execution.symbol, None)
            else:
                positions[execution.symbol] = new_quantity

        self._state = PortfolioState(
            cash=max(0.0, cash),
            positions=positions,
            average_costs=average_costs,
            equity=self._state.equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=self._state.unrealized_pnl,
            cumulative_costs=(
                self._state.cumulative_costs
                + execution.commission
                + execution.tax
                + execution.slippage
            ),
            updated_at=execution.fill_time,
        )
        return self._state

    def force_close_delisted(
        self,
        symbol: str,
        last_valid_close: float,
        market_time: datetime,
        settlement_time: datetime,
    ) -> TradeExecution | None:
        """下市日以最後有效收盤價結清部位，避免殘留無法估值的持倉。"""
        require_timezone(market_time, "market_time")
        require_timezone(settlement_time, "settlement_time")
        if settlement_time <= market_time:
            raise ValueError("下市結算時間必須晚於市場時間")
        quantity = self._state.positions.get(symbol, 0.0)
        if quantity <= 0.0:
            return None
        if last_valid_close < 0.0:
            raise ValueError("last_valid_close 不可為負")
        execution = TradeExecution(
            symbol=symbol,
            side=OrderSide.SELL,
            order_time=market_time,
            signal_time=market_time,
            fill_time=settlement_time,
            reference_price=last_valid_close,
            fill_price=last_valid_close,
            requested_quantity=quantity,
            filled_quantity=quantity,
            commission=0.0,
            tax=0.0,
            slippage=0.0,
            notional=last_valid_close * quantity,
        )
        self.apply(execution)
        return execution

    def mark_to_market(
        self, prices: Mapping[str, float], valuation_time: datetime
    ) -> DailyLedger:
        """以收盤價估值；成本前 Equity 只回加已發生的交易成本。"""
        require_timezone(valuation_time, "valuation_time")
        market_value = 0.0
        unrealized_pnl = 0.0
        for symbol, quantity in self._state.positions.items():
            if symbol not in prices:
                raise ValueError(f"缺少 {symbol} 的估值價格")
            price = float(prices[symbol])
            if price < 0.0:
                raise ValueError("估值價格不可為負")
            market_value += price * quantity
            unrealized_pnl += (price - self._state.average_costs[symbol]) * quantity
        equity = self._state.cash + market_value
        self._state = PortfolioState(
            cash=self._state.cash,
            positions=self._state.positions,
            average_costs=self._state.average_costs,
            equity=equity,
            realized_pnl=self._state.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            cumulative_costs=self._state.cumulative_costs,
            updated_at=valuation_time,
        )
        return DailyLedger(
            valuation_time=valuation_time,
            cash=self._state.cash,
            equity=equity,
            gross_equity=equity + self._state.cumulative_costs,
            realized_pnl=self._state.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            cumulative_costs=self._state.cumulative_costs,
        )
