"""Phase 4A 監控指標、告警與通知管道測試。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from backtest.contracts import EventSeverity, PipelineEvent, PointInTimeSnapshot
from backtest.monitoring import (
    AlertRouter,
    LogEventChannel,
    PipelineMetrics,
    PipelineMetricsCollector,
    WebhookChannel,
)
from backtest.publish import InMemoryObjectStore, SnapshotPublisher, VerificationFailedError


UTC = timezone.utc
NOW = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)


def metrics(*, validation_failure_count: int = 0) -> PipelineMetrics:
    """建立健康的最小指標，僅在需要時模擬 Gate 失敗。"""
    return PipelineMetrics(
        collected_at=NOW,
        data_freshness_seconds=30.0,
        pipeline_execution_time_seconds=10.0,
        total_symbols_processed=2,
        symbol_coverage_ratio=1.0,
        schema_drift_detected=False,
        validation_failure_count=validation_failure_count,
        consecutive_yfinance_failure_count=0,
    )


class MonitoringTests(unittest.TestCase):
    def test_validation_failure_routes_critical_event_to_log_channel(self) -> None:
        router = AlertRouter((LogEventChannel(),))
        with self.assertLogs("backtest.monitoring", level="ERROR") as captured:
            event = router.create_and_route(
                event_type="VALIDATION_FAILED",
                metrics=metrics(validation_failure_count=1),
                details={"validation_error_count": 1},
            )

        self.assertEqual(event.severity, EventSeverity.CRITICAL)
        self.assertIn('"event_type":"VALIDATION_FAILED"', captured.output[0])

    def test_webhook_without_url_falls_back_to_log_without_interrupting(self) -> None:
        event = PipelineEvent(
            event_id="event-1",
            event_type="PUBLISHED",
            severity=EventSeverity.SUCCESS,
            timestamp=NOW,
            details={"manifest_version": 1},
        )
        with self.assertLogs("backtest.monitoring", level="INFO") as captured:
            delivered = WebhookChannel(None).send(event)

        self.assertTrue(delivered)
        self.assertIn('"event_type":"PUBLISHED"', captured.output[0])

    def test_metrics_fallback_marks_missing_inputs_without_fabricating_values(self) -> None:
        collector = PipelineMetricsCollector()
        result = collector.snapshot(universe_size=None, collected_at=NOW)

        self.assertEqual(result.data_freshness_seconds, 0.0)
        self.assertEqual(result.pipeline_execution_time_seconds, 0.0)
        self.assertEqual(result.symbol_coverage_ratio, 0.0)
        self.assertEqual(
            {marker.metric_name for marker in result.gap_markers},
            {
                "data_freshness_seconds",
                "pipeline_execution_time_seconds",
                "symbol_coverage_ratio",
            },
        )

    def test_safe_publish_emits_optional_validation_event(self) -> None:
        events: list[PipelineEvent] = []
        store = InMemoryObjectStore()
        publisher = SnapshotPublisher(store, event_sink=events.append)
        cutoff_time = NOW - timedelta(minutes=1)
        staged = publisher.stage(
            PointInTimeSnapshot(
                generated_at=NOW,
                cutoff_time=cutoff_time,
                model_version="model-v1",
                feature_version="feature-v1",
                symbol_universe=("2330",),
                features_data={"2330": {"signal": {"AI_P": 65.0}}},
                data_available_time=cutoff_time,
            )
        )
        store.write_bytes(staged.snapshot_path, b"{}")

        with self.assertLogs("backtest.publish", level="ERROR"):
            with self.assertRaises(VerificationFailedError):
                publisher.safe_publish(staged.manifest_path)

        self.assertEqual(events[0].event_type, "VALIDATION_FAILED")
        self.assertEqual(events[0].severity, EventSeverity.CRITICAL)


if __name__ == "__main__":
    unittest.main()
