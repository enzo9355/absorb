"""Phase 2A 回測核心的時點正確與簿記測試。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from backtest.contracts import (
    BacktestConfig,
    MarketBar,
    Order,
    OrderSide,
    TimedObservation,
    TradingStatus,
)
from backtest.engine import BacktestEngine, compare_shadow_signals
from backtest.execution import VolumeAwareExecutionModel, taiwan_cost_config
from backtest.features import PointInTimeFeatureBuilder
from backtest.portfolio import PortfolioBook
from backtest.signals import LegacySignalAdapter


UTC = timezone.utc


def session(day: int, *, open_price: float, close_price: float, volume: float = 1000.0, status: TradingStatus = TradingStatus.NORMAL) -> MarketBar:
    """建立一根日頻行情：收盤後才可取得 Close，開盤時可撮合前日訂單。"""
    market_time = datetime(2026, 7, day, 13, 30, tzinfo=UTC)
    return MarketBar(
        symbol="2330",
        market_time=market_time,
        data_available_time=market_time + timedelta(minutes=1),
        tradable_at=datetime(2026, 7, day, 9, 0, tzinfo=UTC),
        open_price=open_price,
        high_price=max(open_price, close_price),
        low_price=min(open_price, close_price),
        close_price=close_price,
        volume=volume,
        status=status,
    )


def probability_observation(day: int, probability: float = 65.0) -> TimedObservation:
    """模擬既有 calc_all 產出的當日 OOS AI_P。"""
    available_at = datetime(2026, 7, day, 13, 31, tzinfo=UTC)
    return TimedObservation(
        symbol="2330",
        market_time=datetime(2026, 7, day, 13, 30, tzinfo=UTC),
        published_at=available_at,
        data_available_time=available_at,
        source="legacy-oos",
        values={"AI_P": probability},
        carry_forward=False,
    )


class LookAheadBiasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bars = (
            session(1, open_price=100.0, close_price=101.0),
            session(2, open_price=102.0, close_price=103.0),
            session(3, open_price=104.0, close_price=105.0),
        )
        self.engine = BacktestEngine(
            PointInTimeFeatureBuilder(),
            LegacySignalAdapter(entry_threshold=60.0, model_version="legacy-oos-v1"),
            VolumeAwareExecutionModel(taiwan_cost_config()),
            BacktestConfig(initial_cash=10000.0, requested_quantity=10.0),
        )

    def test_future_data_mutation_does_not_affect_past(self) -> None:
        """修改 t+1 收盤價時，截止 t 的特徵、訊號、成交與帳戶必須不變。"""
        cutoff = self.bars[1].data_available_time
        baseline = self.engine.run(
            bars=self.bars,
            cutoff=cutoff,
            observations=(probability_observation(1),),
        )
        changed_bars = self.bars[:2] + (replace(self.bars[2], close_price=9999.0, high_price=9999.0),)
        changed = self.engine.run(
            bars=changed_bars,
            cutoff=cutoff,
            observations=(probability_observation(1),),
        )

        self.assertEqual(baseline.features, changed.features)
        self.assertEqual(baseline.signals, changed.signals)
        self.assertEqual(baseline.fills, changed.fills)
        self.assertEqual(baseline.daily_ledger, changed.daily_ledger)

    def test_observation_is_hidden_until_its_actual_available_time(self) -> None:
        """發布時間較晚的非價格資料不可寫入先前交易日的特徵。"""
        delayed = TimedObservation(
            symbol="2330",
            market_time=self.bars[0].market_time,
            published_at=self.bars[1].data_available_time,
            data_available_time=self.bars[1].data_available_time,
            source="revenue",
            values={"REVENUE": 123.0},
        )
        result = self.engine.run(
            bars=self.bars,
            cutoff=self.bars[0].data_available_time,
            observations=(delayed,),
        )

        self.assertNotIn("REVENUE", result.features.rows[0].values)
        self.assertEqual(result.signals, ())

    def test_close_signal_fills_on_next_session_open(self) -> None:
        """使用日收盤生成的訊號只能在下一個交易日 Open 成交。"""
        result = self.engine.run(
            bars=self.bars[:2],
            cutoff=self.bars[1].data_available_time,
            observations=(probability_observation(1),),
        )

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(len(result.signals), 1)
        fill = result.fills[0]
        self.assertEqual(fill.fill_time, self.bars[1].tradable_at)
        self.assertEqual(fill.fill_price, self.bars[1].open_price)
        self.assertGreater(fill.fill_time, fill.order_time)
        self.assertGreater(
            result.report.before_cost.cumulative_return,
            result.report.after_cost.cumulative_return,
        )
        self.assertEqual(result.report.trade_count, 1)

    def test_suspension_or_zero_volume_never_creates_fill(self) -> None:
        """停牌與零成交量不得被回測器虛構成交易。"""
        halted = replace(self.bars[1], status=TradingStatus.SUSPENDED, volume=0.0)
        result = self.engine.run(
            bars=(self.bars[0], halted),
            cutoff=halted.data_available_time,
            observations=(probability_observation(1),),
        )

        self.assertEqual(result.fills, ())
        self.assertEqual(result.daily_ledger[-1].cash, 10000.0)

    def test_portfolio_changes_only_after_fill_and_rejects_negative_cash(self) -> None:
        """Portfolio 不接收 Order，且現金不足的 Fill 會被拒絕。"""
        book = PortfolioBook(100.0, self.bars[0].market_time)
        order = Order(
            symbol="2330",
            order_time=self.bars[0].data_available_time,
            signal_time=self.bars[0].data_available_time,
            data_available_time=self.bars[0].data_available_time,
            side=OrderSide.BUY,
            requested_quantity=10.0,
            volatility=0.0,
            reason="test",
        )
        fill = VolumeAwareExecutionModel(taiwan_cost_config()).execute(order, self.bars[1])

        self.assertIsNotNone(fill)
        with self.assertRaisesRegex(ValueError, "現金不足"):
            book.apply(fill)
        self.assertEqual(book.state.positions, {})
        self.assertEqual(book.state.cash, 100.0)

    def test_shadow_comparison_checks_signal_before_performance(self) -> None:
        """Shadow 模式先釐清訊號差異，再討論成交與績效差異。"""
        result = self.engine.run(
            bars=self.bars[:2],
            cutoff=self.bars[1].data_available_time,
            observations=(probability_observation(1),),
        )

        self.assertTrue(compare_shadow_signals(result.signals, result.signals).matched)
        changed = tuple(replace(signal, signal_value=0.0) for signal in result.signals)
        self.assertFalse(compare_shadow_signals(result.signals, changed).matched)


if __name__ == "__main__":
    unittest.main()
