"""Feature Layer：以 cutoff 為界的特徵計算與時間對齊。"""

from __future__ import annotations

from datetime import datetime
from statistics import pstdev
from typing import Sequence

from .contracts import (
    FeatureFrame,
    FeatureRow,
    MarketBar,
    TimedObservation,
    require_timezone,
)
from .data import bars_available_until


def assert_point_in_time(
    feature: FeatureRow, input_available_times: Sequence[datetime]
) -> None:
    """確認一列特徵的所有來源都在該列可得前已發布。"""
    for value in input_available_times:
        require_timezone(value, "input_available_time")
        if value > feature.data_available_time:
            raise AssertionError("Feature 使用了未來可得資料")


class PointInTimeFeatureBuilder:
    """最小日頻特徵器，僅以當下與過去資料計算。"""

    def __init__(self, feature_version: str = "pit-v1", volatility_window: int = 5) -> None:
        if not feature_version or volatility_window < 2:
            raise ValueError("特徵設定不合法")
        self._feature_version = feature_version
        self._volatility_window = volatility_window

    def build(
        self,
        bars: Sequence[MarketBar],
        observations: Sequence[TimedObservation],
        cutoff: datetime,
    ) -> FeatureFrame:
        require_timezone(cutoff, "cutoff")
        available_bars = bars_available_until(bars, cutoff)
        if len({bar.symbol for bar in available_bars}) > 1:
            raise ValueError("PointInTimeFeatureBuilder 一次只接受一個標的")
        rows: list[FeatureRow] = []
        close_history: list[float] = []
        return_history: list[float] = []

        for bar in available_bars:
            close_history.append(bar.close_price)
            daily_return = 0.0
            if len(close_history) > 1 and close_history[-2] != 0.0:
                daily_return = close_history[-1] / close_history[-2] - 1.0
            return_history.append(daily_return)
            values = {
                "Close": bar.close_price,
                "RET_1": daily_return,
                "VOLATILITY": (
                    pstdev(return_history[-self._volatility_window:])
                    if len(return_history) >= self._volatility_window
                    else 0.0
                ),
            }
            source_times = [bar.data_available_time]
            for observation in sorted(observations, key=lambda item: item.data_available_time):
                if observation.symbol != bar.symbol:
                    continue
                if observation.data_available_time > bar.data_available_time:
                    continue
                if not observation.carry_forward and observation.market_time != bar.market_time:
                    continue
                values.update(observation.values)
                source_times.append(observation.data_available_time)
            feature = FeatureRow(
                symbol=bar.symbol,
                feature_time=bar.market_time,
                data_available_time=bar.data_available_time,
                source_available_through=max(source_times),
                feature_version=self._feature_version,
                values=values,
            )
            assert_point_in_time(feature, source_times)
            rows.append(feature)
        return FeatureFrame(tuple(rows))
