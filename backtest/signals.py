"""Signal Layer：將既有 OOS AI_P 轉成不含成交假設的訊號。"""

from __future__ import annotations

import math

from .contracts import FeatureFrame, Signal, SignalAction


class LegacySignalAdapter:
    """讀取既有 calc_all 後的 OOS AI_P，不重訓或改變模型規則。"""

    def __init__(
        self,
        entry_threshold: float,
        model_version: str,
        target_weight: float = 1.0,
    ) -> None:
        if not 0.0 <= entry_threshold <= 100.0:
            raise ValueError("entry_threshold 必須介於 0 與 100")
        if not model_version or not 0.0 <= target_weight <= 1.0:
            raise ValueError("LegacySignalAdapter 設定不合法")
        self._entry_threshold = entry_threshold
        self._model_version = model_version
        self._target_weight = target_weight

    def generate(self, features: FeatureFrame) -> tuple[Signal, ...]:
        signals: list[Signal] = []
        for row in features.rows:
            probability = row.values.get("AI_P")
            if probability is None or not math.isfinite(probability):
                continue
            action = (
                SignalAction.BUY
                if probability >= self._entry_threshold
                else SignalAction.HOLD
            )
            signals.append(
                Signal(
                    symbol=row.symbol,
                    signal_time=row.data_available_time,
                    data_available_time=row.data_available_time,
                    action=action,
                    signal_value=probability,
                    target_weight=self._target_weight if action is SignalAction.BUY else 0.0,
                    model_version=self._model_version,
                    feature_version=row.feature_version,
                )
            )
        return tuple(signals)
