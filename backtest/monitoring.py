"""資料管線監控指標、告警分流與可插拔通知管道。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .contracts import EventSeverity, PipelineEvent, require_timezone


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MetricGapMarker:
    """缺少歷史或當次指標來源時的明確標記。"""

    metric_name: str
    reason: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.metric_name or not self.reason:
            raise ValueError("MetricGapMarker 欄位不可為空")
        require_timezone(self.timestamp, "timestamp")


@dataclass(frozen=True, slots=True)
class PipelineMetrics:
    """單次資料管線執行可輸出的最小健康度指標。"""

    collected_at: datetime
    data_freshness_seconds: float
    pipeline_execution_time_seconds: float
    total_symbols_processed: int
    symbol_coverage_ratio: float
    schema_drift_detected: bool
    validation_failure_count: int
    consecutive_yfinance_failure_count: int
    gap_markers: tuple[MetricGapMarker, ...] = ()

    def __post_init__(self) -> None:
        require_timezone(self.collected_at, "collected_at")
        if self.data_freshness_seconds < 0 or self.pipeline_execution_time_seconds < 0:
            raise ValueError("時間指標不可為負數")
        if self.total_symbols_processed < 0 or self.validation_failure_count < 0:
            raise ValueError("計數指標不可為負數")
        if self.consecutive_yfinance_failure_count < 0:
            raise ValueError("yfinance 失敗次數不可為負數")
        if not 0.0 <= self.symbol_coverage_ratio <= 1.0:
            raise ValueError("symbol_coverage_ratio 必須介於 0 與 1")


class PipelineMetricsCollector:
    """以當次批次資訊累積監控指標，不回填不存在的歷史資料。"""

    def __init__(self) -> None:
        self._started_at: datetime | None = None
        self._latest_market_time: datetime | None = None
        self._total_symbols_processed = 0
        self._successful_symbols = 0
        self._schema_drift_detected = False
        self._validation_failure_count = 0
        self._consecutive_yfinance_failure_count = 0

    def begin(self, started_at: datetime) -> None:
        require_timezone(started_at, "started_at")
        self._started_at = started_at

    def record_latest_market_time(self, market_time: datetime) -> None:
        require_timezone(market_time, "market_time")
        if self._latest_market_time is None or market_time > self._latest_market_time:
            self._latest_market_time = market_time

    def record_symbol_result(self, *, published: bool) -> None:
        self._total_symbols_processed += 1
        if published:
            self._successful_symbols += 1

    def record_validation_failure(self) -> None:
        self._validation_failure_count += 1

    def mark_schema_drift(self) -> None:
        self._schema_drift_detected = True

    def record_yfinance_failure(self) -> None:
        self._consecutive_yfinance_failure_count += 1

    def record_yfinance_success(self) -> None:
        self._consecutive_yfinance_failure_count = 0

    def snapshot(
        self,
        *,
        universe_size: int | None,
        collected_at: datetime | None = None,
    ) -> PipelineMetrics:
        """回傳當前指標；缺少資料時以零值與 Gap Marker 明確標示。"""
        if universe_size is not None and universe_size < 0:
            raise ValueError("universe_size 不可為負數")
        now = collected_at or datetime.now(timezone.utc)
        require_timezone(now, "collected_at")
        markers: list[MetricGapMarker] = []

        if self._latest_market_time is None:
            freshness = 0.0
            markers.append(MetricGapMarker("data_freshness_seconds", "尚無最新行情時間", now))
        else:
            freshness = max(0.0, (now - self._latest_market_time).total_seconds())

        if self._started_at is None:
            execution_time = 0.0
            markers.append(MetricGapMarker("pipeline_execution_time_seconds", "尚未記錄批次開始時間", now))
        else:
            execution_time = max(0.0, (now - self._started_at).total_seconds())

        if universe_size is None or universe_size == 0:
            coverage = 0.0
            markers.append(MetricGapMarker("symbol_coverage_ratio", "尚無 Universe 標的數", now))
        else:
            coverage = min(1.0, self._successful_symbols / universe_size)

        return PipelineMetrics(
            collected_at=now,
            data_freshness_seconds=freshness,
            pipeline_execution_time_seconds=execution_time,
            total_symbols_processed=self._total_symbols_processed,
            symbol_coverage_ratio=coverage,
            schema_drift_detected=self._schema_drift_detected,
            validation_failure_count=self._validation_failure_count,
            consecutive_yfinance_failure_count=self._consecutive_yfinance_failure_count,
            gap_markers=tuple(markers),
        )


class NotificationChannel(Protocol):
    """營運通知的可插拔輸出介面。"""

    def send(self, event: PipelineEvent) -> bool:
        ...


class LogEventChannel:
    """將事件以 JSON 單行交由既有 logging 與脫敏 formatter 處理。"""

    def __init__(self, event_logger: logging.Logger | None = None) -> None:
        self._logger = event_logger or logger

    def send(self, event: PipelineEvent) -> bool:
        level = {
            EventSeverity.SUCCESS: logging.INFO,
            EventSeverity.WARNING: logging.WARNING,
            EventSeverity.CRITICAL: logging.ERROR,
        }[event.severity]
        self._logger.log(
            level,
            "%s",
            json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        return True


class WebhookChannel:
    """以標準庫 POST 事件；未設定 URL 時安全降級至 LogEventChannel。"""

    def __init__(
        self,
        webhook_url: str | None,
        *,
        fallback: NotificationChannel | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必須大於零")
        self._webhook_url = webhook_url
        self._fallback = fallback or LogEventChannel()
        self._timeout_seconds = timeout_seconds

    def send(self, event: PipelineEvent) -> bool:
        if not self._webhook_url:
            return self._fallback.send(event)
        request = Request(
            self._webhook_url,
            data=json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status = response.getcode()
        except (HTTPError, URLError, OSError) as exc:
            logger.error("Webhook 事件通知失敗：%s", type(exc).__name__)
            return False
        if 200 <= status < 300:
            return True
        logger.error("Webhook 事件通知回傳非成功狀態：%s", status)
        return False


class AlertRouter:
    """依門檻建立事件並分流到所有已設定通知管道。"""

    _CRITICAL_EVENT_TYPES = frozenset(
        {"VALIDATION_FAILED", "ROLLBACK_TRIGGERED", "PIPELINE_FAILED"}
    )

    def __init__(
        self,
        channels: Sequence[NotificationChannel],
        *,
        minimum_coverage_ratio: float = 0.95,
        maximum_freshness_seconds: float = 3600.0,
        yfinance_failure_threshold: int = 3,
    ) -> None:
        if not 0.0 < minimum_coverage_ratio <= 1.0:
            raise ValueError("minimum_coverage_ratio 必須介於 0 與 1")
        if maximum_freshness_seconds <= 0 or yfinance_failure_threshold < 1:
            raise ValueError("告警門檻設定不合法")
        self._channels = tuple(channels)
        self._minimum_coverage_ratio = minimum_coverage_ratio
        self._maximum_freshness_seconds = maximum_freshness_seconds
        self._yfinance_failure_threshold = yfinance_failure_threshold

    def create_and_route(
        self,
        *,
        event_type: str,
        metrics: PipelineMetrics,
        details: Mapping[str, object] | None = None,
    ) -> PipelineEvent:
        event = PipelineEvent(
            event_id=uuid4().hex,
            event_type=event_type,
            severity=self.classify(event_type, metrics),
            timestamp=metrics.collected_at,
            details={
                "symbol_coverage_ratio": metrics.symbol_coverage_ratio,
                "validation_failure_count": metrics.validation_failure_count,
                **(dict(details) if details is not None else {}),
            },
        )
        self.route_event(event)
        return event

    def classify(self, event_type: str, metrics: PipelineMetrics) -> EventSeverity:
        if event_type in self._CRITICAL_EVENT_TYPES or metrics.validation_failure_count > 0:
            return EventSeverity.CRITICAL
        coverage_is_unknown = any(
            marker.metric_name == "symbol_coverage_ratio" for marker in metrics.gap_markers
        )
        if not coverage_is_unknown and metrics.symbol_coverage_ratio < self._minimum_coverage_ratio:
            return EventSeverity.CRITICAL
        if (
            metrics.symbol_coverage_ratio < 1.0
            or metrics.schema_drift_detected
            or metrics.data_freshness_seconds > self._maximum_freshness_seconds
            or metrics.consecutive_yfinance_failure_count >= self._yfinance_failure_threshold
        ):
            return EventSeverity.WARNING
        return EventSeverity.SUCCESS

    def route_event(self, event: PipelineEvent) -> None:
        for channel in self._channels:
            try:
                channel.send(event)
            except Exception as exc:
                logger.error("通知管道處理失敗：%s", type(exc).__name__)
