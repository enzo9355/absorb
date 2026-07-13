"""Execution Layer：無狀態的撮合、成本與滑價計算。"""

from __future__ import annotations

from .contracts import (
    ExecutionStatus,
    ExecutionCostConfig,
    MarketBar,
    Order,
    OrderSide,
    TradeExecution,
    TradingStatus,
)


def taiwan_cost_config(
    *,
    commission_discount: float = 1.0,
    minimum_commission: float = 0.0,
    participation_rate: float = 0.1,
    base_slippage: float = 0.0,
    impact_coefficient: float = 0.0,
) -> ExecutionCostConfig:
    """台股費率預設與舊引擎 0.585% 往返成本相容。"""
    return ExecutionCostConfig(
        commission_rate=0.001425,
        commission_discount=commission_discount,
        minimum_commission=minimum_commission,
        sell_tax_rate=0.003,
        participation_rate=participation_rate,
        base_slippage=base_slippage,
        impact_coefficient=impact_coefficient,
    )


def us_cost_config(
    *,
    per_share_commission: float = 0.005,
    participation_rate: float = 0.1,
    base_slippage: float = 0.0,
    impact_coefficient: float = 0.0,
) -> ExecutionCostConfig:
    """美股按股收費設定，也可傳入 0 代表零佣金。"""
    return ExecutionCostConfig(
        per_share_commission=per_share_commission,
        participation_rate=participation_rate,
        base_slippage=base_slippage,
        impact_coefficient=impact_coefficient,
    )


class VolumeAwareExecutionModel:
    """不持有 Portfolio 狀態的日頻 Open 撮合模型。"""

    def __init__(self, config: ExecutionCostConfig) -> None:
        self._config = config

    def execute(self, order: Order, bar: MarketBar) -> TradeExecution | None:
        if order.symbol != bar.symbol or bar.tradable_at <= order.order_time:
            return None
        if bar.status is not TradingStatus.NORMAL or bar.volume <= 0.0:
            return self._rejected(order, bar)

        filled_quantity = min(
            order.requested_quantity,
            bar.volume * self._config.participation_rate,
        )
        if filled_quantity <= 0.0:
            return self._rejected(order, bar)

        volume_ratio = order.requested_quantity / bar.volume
        slippage_rate = (
            self._config.base_slippage
            + self._config.impact_coefficient * order.volatility * volume_ratio
        )
        price_multiplier = 1.0 + slippage_rate if order.side is OrderSide.BUY else 1.0 - slippage_rate
        fill_price = max(0.0, bar.open_price * price_multiplier)
        notional = fill_price * filled_quantity
        slippage = abs(fill_price - bar.open_price) * filled_quantity
        percentage_commission = (
            notional
            * self._config.commission_rate
            * self._config.commission_discount
        )
        commission = (
            max(self._config.minimum_commission, percentage_commission)
            if percentage_commission > 0.0
            else 0.0
        ) + self._config.per_share_commission * filled_quantity
        tax = (
            notional * self._config.sell_tax_rate
            if order.side is OrderSide.SELL
            else 0.0
        )
        return TradeExecution(
            symbol=order.symbol,
            side=order.side,
            order_time=order.order_time,
            signal_time=order.signal_time,
            fill_time=bar.tradable_at,
            reference_price=bar.open_price,
            fill_price=fill_price,
            requested_quantity=order.requested_quantity,
            filled_quantity=filled_quantity,
            commission=commission,
            tax=tax,
            slippage=slippage,
            notional=notional,
        )

    @staticmethod
    def _rejected(order: Order, bar: MarketBar) -> TradeExecution:
        """保留拒絕紀錄，讓上層能證明訂單未改變 Portfolio。"""
        return TradeExecution(
            symbol=order.symbol,
            side=order.side,
            order_time=order.order_time,
            signal_time=order.signal_time,
            fill_time=bar.tradable_at,
            reference_price=bar.open_price,
            fill_price=0.0,
            requested_quantity=order.requested_quantity,
            filled_quantity=0.0,
            commission=0.0,
            tax=0.0,
            slippage=0.0,
            notional=0.0,
            status=ExecutionStatus.REJECTED,
        )
