"""Walk-forward 劃分與 OOS 預測回放防護。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Sequence

from .contracts import FeatureRow, Signal, require_timezone


class WalkForwardMode(str, Enum):
    """訓練視窗可固定滾動，或從起點持續擴張。"""

    ROLLING = "ROLLING"
    ANCHORED = "ANCHORED"


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """一個訓練集、Gap 與 OOS 測試集的索引描述。"""

    index: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


class TimeSeriesWalkForwardSplitter:
    """以交易列數計算的 Walk-forward splitter，強制最少五日隔離。"""

    def __init__(
        self,
        *,
        train_window_days: int,
        test_window_days: int,
        gap_days: int = 5,
        mode: WalkForwardMode = WalkForwardMode.ROLLING,
    ) -> None:
        if train_window_days <= 0 or test_window_days <= 0:
            raise ValueError("訓練與測試視窗必須大於零")
        if gap_days < 5:
            raise ValueError("gap_days 至少必須為 5 個交易日")
        self._train_window_days = train_window_days
        self._test_window_days = test_window_days
        self._gap_days = gap_days
        self._mode = mode

    def split(
        self,
        rows: Sequence[FeatureRow],
        signals: Sequence[Signal] = (),
    ) -> tuple[WalkForwardFold, ...]:
        """產生不含殘缺測試視窗的 folds，並逐一驗證隔離規則。"""
        ordered_rows = tuple(rows)
        if tuple(sorted(ordered_rows, key=lambda row: row.data_available_time)) != ordered_rows:
            raise ValueError("FeatureRow 必須依 data_available_time 排序")
        folds: list[WalkForwardFold] = []
        train_end = self._train_window_days - 1
        fold_index = 0
        while train_end < len(ordered_rows):
            test_start = train_end + self._gap_days + 1
            test_end = test_start + self._test_window_days
            if test_end > len(ordered_rows):
                break
            train_start = (
                0
                if self._mode is WalkForwardMode.ANCHORED
                else max(0, train_end - self._train_window_days + 1)
            )
            fold = WalkForwardFold(
                index=fold_index,
                train_indices=tuple(range(train_start, train_end + 1)),
                test_indices=tuple(range(test_start, test_end)),
            )
            self.validate_fold(ordered_rows, fold, signals)
            folds.append(fold)
            fold_index += 1
            train_end = test_end - 1
        return tuple(folds)

    def validate_fold(
        self,
        rows: Sequence[FeatureRow],
        fold: WalkForwardFold,
        signals: Sequence[Signal] = (),
    ) -> None:
        """拒絕 test 列被移入 train 或跨越 Gap 的資料切分。"""
        if not fold.train_indices or not fold.test_indices:
            raise ValueError("訓練集與測試集不可為空")
        if tuple(sorted(fold.train_indices)) != fold.train_indices:
            raise ValueError("train_indices 必須排序")
        if tuple(sorted(fold.test_indices)) != fold.test_indices:
            raise ValueError("test_indices 必須排序")
        if set(fold.train_indices) & set(fold.test_indices):
            raise ValueError("訓練集與測試集不可重疊")
        if min(fold.train_indices) < 0 or max(fold.test_indices) >= len(rows):
            raise ValueError("fold 索引超出 FeatureRow 範圍")
        train_end = max(fold.train_indices)
        test_start = min(fold.test_indices)
        if test_start - train_end - 1 < self._gap_days:
            raise ValueError("訓練集與測試集之間的 Gap 不足")
        gap_boundary = rows[train_end + self._gap_days].data_available_time
        for index in fold.test_indices:
            if rows[index].data_available_time <= gap_boundary:
                raise ValueError("測試特徵可得時間未跨越 Gap")
        test_times = {rows[index].data_available_time for index in fold.test_indices}
        for signal in signals:
            require_timezone(signal.signal_time, "signal_time")
            if signal.data_available_time in test_times and signal.signal_time <= gap_boundary:
                raise ValueError("測試訊號可得時間未跨越 Gap")


class PredictionOrigin(str, Enum):
    """回放預測的來源，僅接受 Walk-forward OOS 結果。"""

    OOS = "OOS"
    POST_HOC = "POST_HOC"


@dataclass(frozen=True, slots=True)
class OOSPrediction:
    """特定 fold 於當時生成的單筆模型機率。"""

    symbol: str
    feature_time: datetime
    data_available_time: datetime
    prediction_time: datetime
    probability: float
    model_version: str
    fold_index: int
    origin: PredictionOrigin = PredictionOrigin.OOS

    def __post_init__(self) -> None:
        if not self.symbol or not self.model_version:
            raise ValueError("OOS 預測必要欄位不可為空")
        for name in ("feature_time", "data_available_time", "prediction_time"):
            require_timezone(getattr(self, name), name)
        if self.data_available_time > self.prediction_time:
            raise ValueError("預測時間不可早於資料可得時間")
        if not math.isfinite(self.probability) or not 0.0 <= self.probability <= 100.0:
            raise ValueError("probability 必須介於 0 與 100")
        if self.fold_index < 0:
            raise ValueError("fold_index 不可為負")


class OOSPredictionReplay:
    """只依 fold 載入對應 OOS 預測，拒絕事後模型輸出。"""

    def __init__(self, predictions: Sequence[OOSPrediction]) -> None:
        self._predictions: dict[tuple[str, datetime], OOSPrediction] = {}
        for prediction in predictions:
            if prediction.origin is not PredictionOrigin.OOS:
                raise ValueError("禁止將 POST_HOC 預測混入歷史回放")
            key = (prediction.symbol, prediction.feature_time)
            if key in self._predictions:
                raise ValueError("同一 symbol 與 feature_time 不可有重複 OOS 預測")
            self._predictions[key] = prediction

    def replay_fold(
        self,
        fold: WalkForwardFold,
        rows: Sequence[FeatureRow],
    ) -> tuple[OOSPrediction, ...]:
        """回傳指定 fold 的完整 OOS 預測，缺漏或錯 fold 一律拒收。"""
        result: list[OOSPrediction] = []
        for index in fold.test_indices:
            row = rows[index]
            prediction = self._predictions.get((row.symbol, row.feature_time))
            if prediction is None:
                raise ValueError("測試列缺少對應 OOS 預測")
            if prediction.fold_index != fold.index:
                raise ValueError("OOS 預測屬於錯誤的 Walk-forward fold")
            if prediction.data_available_time != row.data_available_time:
                raise ValueError("OOS 預測與特徵資料可得時間不一致")
            result.append(prediction)
        return tuple(result)
