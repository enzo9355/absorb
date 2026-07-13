"""新舊回測的分階段 Parity Checker 與拒收規則。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .analytics import PerformanceReport
from .contracts import (
    DailyLedger,
    ExecutionStatus,
    FeatureFrame,
    MarketBar,
    Signal,
    TradeExecution,
)
from .engine import BacktestResult
from .validation import OOSPrediction


class ParityMismatchError(AssertionError):
    """非預期差異，必須阻斷新引擎取代或發布。"""


@dataclass(frozen=True, slots=True)
class LegacyBaseline:
    """舊引擎輸出的特徵、OOS 機率、交易與績效基準。"""

    features: FeatureFrame
    oos_predictions: tuple[OOSPrediction, ...]
    executions: tuple[TradeExecution, ...]
    daily_ledger: tuple[DailyLedger, ...]
    report: PerformanceReport
    market_bars: tuple[MarketBar, ...] = ()


@dataclass(frozen=True, slots=True)
class ParityPolicy:
    """明確列出可接受的執行層預期差異。"""

    allow_execution_timing: bool = True
    allow_liquidity_rejection: bool = True
    allow_cost_delta: bool = True


@dataclass(frozen=True, slots=True)
class ParityReport:
    """Parity 比對結果，將可接受與拒收差異分開保存。"""

    expected_differences: tuple[str, ...]
    unexpected_differences: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.unexpected_differences


class LegacyParityChecker:
    """先鎖定特徵與 OOS 機率，再處理可預期的成交與績效變化。"""

    def __init__(self, policy: ParityPolicy | None = None) -> None:
        self._policy = policy or ParityPolicy()

    def compare(
        self,
        legacy: LegacyBaseline,
        current: BacktestResult,
    ) -> ParityReport:
        self._assert_feature_parity(legacy.features, current.features)
        self._assert_prediction_parity(legacy.oos_predictions, current.signals)
        self._assert_execution_market_alignment(current, legacy.market_bars)
        self._assert_account_invariants(current)
        expected, unexpected = self._compare_executions(legacy.executions, current)
        self._compare_performance(legacy, current, expected, unexpected)
        report = ParityReport(tuple(expected), tuple(unexpected))
        if not report.accepted:
            raise ParityMismatchError("; ".join(report.unexpected_differences))
        return report

    @staticmethod
    def _assert_feature_parity(legacy: FeatureFrame, current: FeatureFrame) -> None:
        legacy_rows = {(row.symbol, row.feature_time): row for row in legacy.rows}
        current_rows = {(row.symbol, row.feature_time): row for row in current.rows}
        if legacy_rows.keys() != current_rows.keys():
            raise ParityMismatchError("Stage 1：特徵日期或標的不一致")
        for key, legacy_row in legacy_rows.items():
            current_row = current_rows[key]
            if (
                legacy_row.data_available_time != current_row.data_available_time
                or legacy_row.feature_version != current_row.feature_version
                or dict(legacy_row.values) != dict(current_row.values)
            ):
                raise ParityMismatchError(f"Stage 1：特徵不一致 {key}")

    @staticmethod
    def _assert_prediction_parity(
        legacy_predictions: Sequence[OOSPrediction],
        current_signals: Sequence[Signal],
    ) -> None:
        legacy_by_key = {
            (item.symbol, item.prediction_time): item for item in legacy_predictions
        }
        current_by_key = {
            (item.symbol, item.signal_time): item for item in current_signals
        }
        if legacy_by_key.keys() != current_by_key.keys():
            raise ParityMismatchError("Stage 1：OOS 預測日期或標的不一致")
        for key, legacy_prediction in legacy_by_key.items():
            current_signal = current_by_key[key]
            if (
                legacy_prediction.probability != current_signal.signal_value
                or legacy_prediction.model_version != current_signal.model_version
                or legacy_prediction.data_available_time
                != current_signal.data_available_time
            ):
                raise ParityMismatchError(f"Stage 1：OOS 預測不一致 {key}")

    def _compare_executions(
        self,
        legacy_executions: Sequence[TradeExecution],
        current: BacktestResult,
    ) -> tuple[list[str], list[str]]:
        expected: list[str] = []
        unexpected: list[str] = []
        if current.rejections:
            if self._policy.allow_liquidity_rejection:
                expected.append("Stage 2：停牌、下市或流動性限制拒絕訂單")
            else:
                unexpected.append("Stage 2：新引擎拒絕了舊引擎成交的訂單")
        legacy_fills = tuple(item for item in legacy_executions if item.status is ExecutionStatus.FILLED)
        for index in range(max(len(legacy_fills), len(current.fills))):
            legacy = legacy_fills[index] if index < len(legacy_fills) else None
            current_fill = current.fills[index] if index < len(current.fills) else None
            if legacy is None or current_fill is None:
                if current.rejections and self._policy.allow_liquidity_rejection:
                    continue
                unexpected.append(f"Stage 2：第 {index} 筆成交數量不一致")
                continue
            if legacy.symbol != current_fill.symbol or legacy.side is not current_fill.side:
                unexpected.append(f"Stage 2：第 {index} 筆成交標的或方向不一致")
                continue
            timing_changed = legacy.fill_time != current_fill.fill_time
            if timing_changed:
                if self._policy.allow_execution_timing and current_fill.fill_time > legacy.fill_time:
                    expected.append(f"Stage 2：第 {index} 筆成交延後至可交易時點")
                else:
                    unexpected.append(f"Stage 2：第 {index} 筆成交時間非預期變更")
            if legacy.filled_quantity != current_fill.filled_quantity:
                if (
                    self._policy.allow_liquidity_rejection
                    and current_fill.filled_quantity < legacy.filled_quantity
                ):
                    expected.append(f"Stage 2：第 {index} 筆成交量受流動性限制")
                else:
                    unexpected.append(f"Stage 2：第 {index} 筆成交量不一致")
            if legacy.fill_price != current_fill.fill_price and not timing_changed:
                unexpected.append(f"Stage 2：第 {index} 筆成交價不一致")
            if (
                legacy.commission,
                legacy.tax,
                legacy.slippage,
            ) != (
                current_fill.commission,
                current_fill.tax,
                current_fill.slippage,
            ):
                if self._policy.allow_cost_delta:
                    expected.append(f"Stage 2：第 {index} 筆逐筆成本與舊固定成本不同")
                else:
                    unexpected.append(f"Stage 2：第 {index} 筆成本不一致")
        return expected, unexpected

    @staticmethod
    def _assert_execution_market_alignment(
        current: BacktestResult,
        market_bars: Sequence[MarketBar],
    ) -> None:
        by_fill_time = {
            (bar.symbol, bar.tradable_at): bar for bar in market_bars
        }
        for execution in current.fills:
            bar = by_fill_time.get((execution.symbol, execution.fill_time))
            if bar is not None and execution.reference_price != bar.open_price:
                raise ParityMismatchError("Stage 2：成交參考價未對齊交易 Bar 的 Open")

    @staticmethod
    def _assert_account_invariants(current: BacktestResult) -> None:
        for execution in (*current.fills, *current.rejections):
            if execution.fill_time <= execution.order_time:
                raise ParityMismatchError("成交時間早於或等於訂單時間")
        for rejection in current.rejections:
            if (
                rejection.status is not ExecutionStatus.REJECTED
                or rejection.filled_quantity != 0.0
                or rejection.notional != 0.0
            ):
                raise ParityMismatchError("拒絕訂單含有成交結果")
        for ledger in current.daily_ledger:
            if ledger.cash < 0.0:
                raise ParityMismatchError("未開槓桿帳戶出現負現金")
        state = current.final_state
        if state.cash < 0.0 or state.equity < state.cash:
            raise ParityMismatchError("帳戶現金或淨值不符合未開槓桿限制")

    @staticmethod
    def _compare_performance(
        legacy: LegacyBaseline,
        current: BacktestResult,
        expected: list[str],
        unexpected: list[str],
    ) -> None:
        ledgers_match = legacy.daily_ledger == current.daily_ledger
        report_match = legacy.report == current.report
        if ledgers_match and report_match:
            return
        if expected:
            expected.append("Stage 3：成交時點、流動性或成本修正造成績效偏離")
            return
        unexpected.append("Stage 3：每日 Equity 或績效指標不一致")
