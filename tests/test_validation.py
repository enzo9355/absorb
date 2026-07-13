"""Phase 2B 的 Walk-forward、Parity 與偏差治理測試。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from backtest.contracts import (
    BacktestConfig,
    ExecutionStatus,
    FeatureFrame,
    FeatureRow,
    MarketBar,
    Order,
    OrderSide,
    TimedObservation,
    TradeExecution,
    TradingStatus,
)
from backtest.data import CurrentUniverseFallback
from backtest.engine import BacktestEngine
from backtest.execution import VolumeAwareExecutionModel, taiwan_cost_config
from backtest.features import PointInTimeFeatureBuilder
from backtest.parity_checker import (
    LegacyBaseline,
    LegacyParityChecker,
    ParityMismatchError,
)
from backtest.portfolio import PortfolioBook
from backtest.signals import LegacySignalAdapter
from backtest.validation import (
    OOSPrediction,
    OOSPredictionReplay,
    PredictionOrigin,
    TimeSeriesWalkForwardSplitter,
    WalkForwardFold,
    WalkForwardMode,
)


UTC = timezone.utc


def bar(day: int, *, status: TradingStatus = TradingStatus.NORMAL, volume: float = 1000.0) -> MarketBar:
    """建立收盤後可得、下一日開盤可撮合的日頻行情。"""
    market_time = datetime(2026, 1, day, 13, 30, tzinfo=UTC)
    return MarketBar(
        symbol="2330",
        market_time=market_time,
        data_available_time=market_time + timedelta(minutes=1),
        tradable_at=datetime(2026, 1, day, 9, 0, tzinfo=UTC),
        open_price=100.0 + day,
        high_price=102.0 + day,
        low_price=99.0 + day,
        close_price=101.0 + day,
        volume=volume,
        status=status,
    )


def feature_rows(count: int) -> tuple[FeatureRow, ...]:
    """建立排序且帶時區的合成日頻特徵。"""
    rows: list[FeatureRow] = []
    for day in range(1, count + 1):
        feature_time = datetime(2026, 2, day, 13, 30, tzinfo=UTC)
        available_time = feature_time + timedelta(minutes=1)
        rows.append(
            FeatureRow(
                symbol="2330",
                feature_time=feature_time,
                data_available_time=available_time,
                source_available_through=available_time,
                feature_version="legacy-v1",
                values={"AI_P": 65.0},
            )
        )
    return tuple(rows)


def oos_observation(day: int) -> TimedObservation:
    """模擬既有引擎當日產生的 OOS AI_P。"""
    available_time = datetime(2026, 1, day, 13, 31, tzinfo=UTC)
    return TimedObservation(
        symbol="2330",
        market_time=datetime(2026, 1, day, 13, 30, tzinfo=UTC),
        published_at=available_time,
        data_available_time=available_time,
        source="legacy-oos",
        values={"AI_P": 65.0},
        carry_forward=False,
    )


class ValidationTests(unittest.TestCase):
    def test_splitter_enforces_five_day_gap_and_rejects_overlap(self) -> None:
        rows = feature_rows(20)
        splitter = TimeSeriesWalkForwardSplitter(
            train_window_days=5,
            test_window_days=3,
            gap_days=5,
            mode=WalkForwardMode.ROLLING,
        )

        folds = splitter.split(rows)

        self.assertEqual(folds[0].train_indices, (0, 1, 2, 3, 4))
        self.assertEqual(folds[0].test_indices, (10, 11, 12))
        self.assertGreater(
            rows[folds[0].test_indices[0]].data_available_time,
            rows[9].data_available_time,
        )
        invalid = WalkForwardFold(
            index=0,
            train_indices=(0, 1, 2, 3, 4),
            test_indices=(9, 10, 11),
        )
        with self.assertRaises(ValueError):
            splitter.validate_fold(rows, invalid)

    def test_oos_replay_rejects_post_hoc_prediction_and_wrong_fold(self) -> None:
        rows = feature_rows(20)
        splitter = TimeSeriesWalkForwardSplitter(
            train_window_days=5,
            test_window_days=3,
        )
        fold = splitter.split(rows)[0]
        post_hoc = OOSPrediction(
            symbol="2330",
            feature_time=rows[10].feature_time,
            data_available_time=rows[10].data_available_time,
            prediction_time=rows[10].data_available_time,
            probability=65.0,
            model_version="post-hoc",
            fold_index=fold.index,
            origin=PredictionOrigin.POST_HOC,
        )
        with self.assertRaises(ValueError):
            OOSPredictionReplay((post_hoc,))

        predictions = tuple(
            OOSPrediction(
                symbol=row.symbol,
                feature_time=row.feature_time,
                data_available_time=row.data_available_time,
                prediction_time=row.data_available_time,
                probability=65.0,
                model_version="legacy-oos-v1",
                fold_index=fold.index,
            )
            for row in (rows[index] for index in fold.test_indices)
        )
        replay = OOSPredictionReplay(predictions)
        self.assertEqual(replay.replay_fold(fold, rows), predictions)
        wrong_fold = (replace(predictions[0], fold_index=fold.index + 1),) + predictions[1:]
        with self.assertRaises(ValueError):
            OOSPredictionReplay(wrong_fold).replay_fold(fold, rows)

    def test_delisting_force_closes_at_last_valid_close(self) -> None:
        started_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        book = PortfolioBook(1000.0, started_at)
        buy = TradeExecution(
            symbol="2330",
            side=OrderSide.BUY,
            order_time=started_at,
            signal_time=started_at,
            fill_time=started_at + timedelta(minutes=1),
            reference_price=100.0,
            fill_price=100.0,
            requested_quantity=5.0,
            filled_quantity=5.0,
            commission=0.0,
            tax=0.0,
            slippage=0.0,
            notional=500.0,
        )
        book.apply(buy)

        settlement = book.force_close_delisted(
            "2330",
            120.0,
            datetime(2026, 1, 2, 13, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 13, 31, tzinfo=UTC),
        )

        self.assertIsNotNone(settlement)
        self.assertEqual(book.state.positions, {})
        self.assertEqual(book.state.cash, 1100.0)

    def test_engine_settles_existing_position_on_delisting_bar(self) -> None:
        engine = BacktestEngine(
            PointInTimeFeatureBuilder(),
            LegacySignalAdapter(entry_threshold=60.0, model_version="legacy-oos-v1"),
            VolumeAwareExecutionModel(taiwan_cost_config()),
            BacktestConfig(initial_cash=10000.0, requested_quantity=10.0),
        )
        delisted = bar(3, status=TradingStatus.DELISTED, volume=0.0)

        result = engine.run(
            bars=(bar(1), bar(2), delisted),
            cutoff=delisted.data_available_time,
            observations=(oos_observation(1),),
        )

        self.assertEqual(result.final_state.positions, {})
        self.assertEqual(result.fills[-1].fill_price, bar(2).close_price)
        self.assertEqual(result.fills[-1].side, OrderSide.SELL)

    def test_suspension_returns_rejection_without_portfolio_change(self) -> None:
        order_time = datetime(2026, 1, 1, 13, 31, tzinfo=UTC)
        order = Order(
            symbol="2330",
            order_time=order_time,
            signal_time=order_time,
            data_available_time=order_time,
            side=OrderSide.BUY,
            requested_quantity=10.0,
            volatility=0.0,
            reason="test",
        )
        halted = bar(2, status=TradingStatus.SUSPENDED, volume=0.0)
        rejection = VolumeAwareExecutionModel(taiwan_cost_config()).execute(order, halted)

        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.status, ExecutionStatus.REJECTED)
        self.assertEqual(rejection.filled_quantity, 0.0)
        book = PortfolioBook(1000.0, order_time)
        with self.assertRaisesRegex(ValueError, "拒絕訂單"):
            book.apply(rejection)
        self.assertEqual(book.state.cash, 1000.0)
        self.assertEqual(book.state.positions, {})

    def test_parity_checker_rejects_feature_mismatch(self) -> None:
        engine = BacktestEngine(
            PointInTimeFeatureBuilder(),
            LegacySignalAdapter(entry_threshold=60.0, model_version="legacy-oos-v1"),
            VolumeAwareExecutionModel(taiwan_cost_config()),
            BacktestConfig(initial_cash=10000.0, requested_quantity=10.0),
        )
        result = engine.run(
            bars=(bar(1), bar(2)),
            cutoff=bar(2).data_available_time,
            observations=(oos_observation(1),),
        )
        first_feature = result.features.rows[0]
        prediction = OOSPrediction(
            symbol=first_feature.symbol,
            feature_time=first_feature.feature_time,
            data_available_time=first_feature.data_available_time,
            prediction_time=result.signals[0].signal_time,
            probability=result.signals[0].signal_value,
            model_version=result.signals[0].model_version,
            fold_index=0,
        )
        baseline = LegacyBaseline(
            features=result.features,
            oos_predictions=(prediction,),
            executions=result.fills,
            daily_ledger=result.daily_ledger,
            report=result.report,
            market_bars=(bar(1), bar(2)),
        )
        self.assertTrue(LegacyParityChecker().compare(baseline, result).accepted)

        changed_feature = replace(first_feature, values={"AI_P": 0.0})
        mismatched = replace(
            baseline,
            features=FeatureFrame((changed_feature,) + result.features.rows[1:]),
        )
        with self.assertRaises(ParityMismatchError):
            LegacyParityChecker().compare(mismatched, result)

    def test_current_universe_fallback_warns_about_survivorship_bias(self) -> None:
        source = CurrentUniverseFallback(("2330", "2317"))
        with self.assertLogs("backtest.data", level="WARNING") as logs:
            symbols = source.get_active_symbols(datetime(2026, 1, 1, tzinfo=UTC))

        self.assertEqual(symbols, ["2317", "2330"])
        self.assertIn("生存者偏差", logs.output[0])
        self.assertEqual(source.gap_markers[0].kind, "UNIVERSE_MEMBERSHIP")


if __name__ == "__main__":
    unittest.main()
