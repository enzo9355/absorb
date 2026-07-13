"""Phase 3A 資料治理與快照原子發布測試。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from backtest.contracts import PointInTimeSnapshot, TradingStatus, UniverseMembership
from backtest.data import InMemoryMarketDataSource
from backtest.publish import InMemoryObjectStore, SnapshotPublisher, ValidationError


UTC = timezone.utc


def snapshot(version: str, symbols: tuple[str, ...]) -> PointInTimeSnapshot:
    """建立可發布的最小 point-in-time 快照。"""
    generated_at = datetime(2026, 3, 1, 14, 0, tzinfo=UTC)
    cutoff_time = generated_at - timedelta(minutes=1)
    return PointInTimeSnapshot(
        generated_at=generated_at,
        cutoff_time=cutoff_time,
        model_version=f"model-{version}",
        feature_version="feature-v1",
        symbol_universe=symbols,
        features_data={
            symbol: {
                "features": {"RET_1": 0.01},
                "signal": {"AI_P": 65.0},
            }
            for symbol in symbols
        },
        data_available_time=cutoff_time,
    )


class SnapshotPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryObjectStore()
        self.publisher = SnapshotPublisher(self.store)

    def publish_initial(self) -> PointInTimeSnapshot:
        initial = snapshot("v1", ("2330", "2317"))
        self.publisher.publish(self.publisher.stage(initial))
        return initial

    def test_corrupted_staging_snapshot_is_rejected_without_polluting_active_manifest(self) -> None:
        initial = self.publish_initial()
        active_before = self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH)
        staged = self.publisher.stage(snapshot("v2", ("2330", "2317")))
        self.store.write_bytes(staged.snapshot_path, b'{"corrupted":true}')

        with self.assertRaises(ValidationError):
            self.publisher.validate(staged)

        self.assertEqual(
            self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH),
            active_before,
        )
        self.assertEqual(self.publisher.read_active_snapshot(), initial)

    def test_hash_mismatch_is_rejected_without_changing_active_manifest(self) -> None:
        self.publish_initial()
        active_before = self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH)
        staged = self.publisher.stage(snapshot("v2", ("2330", "2317")))
        manifest = json.loads(self.store.read_bytes(staged.manifest_path))
        manifest["snapshot_sha256"] = "0" * 64
        self.store.write_bytes(
            staged.manifest_path,
            json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        )

        with self.assertRaises(ValidationError):
            self.publisher.validate(staged)

        self.assertEqual(
            self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH),
            active_before,
        )

    def test_staging_does_not_change_reader_until_atomic_publish(self) -> None:
        initial = self.publish_initial()
        staged = self.publisher.stage(snapshot("v2", ("2330", "2317")))

        self.assertEqual(self.publisher.read_active_snapshot(), initial)
        self.assertTrue(self.store.exists(staged.manifest_path))

        self.publisher.publish(staged)
        self.assertEqual(self.publisher.read_active_snapshot().model_version, "model-v2")

    def test_coverage_guard_and_rollback_follow_manifest_chain(self) -> None:
        initial = snapshot("v1", tuple(f"{value:04d}" for value in range(10)))
        first_manifest = self.publisher.publish(self.publisher.stage(initial))
        incomplete = snapshot("v2", tuple(f"{value:04d}" for value in range(8)))
        with self.assertRaises(ValidationError):
            self.publisher.validate(self.publisher.stage(incomplete))

        second = snapshot("v2", tuple(f"{value:04d}" for value in range(10)))
        second_manifest = self.publisher.publish(self.publisher.stage(second))
        self.assertEqual(second_manifest.previous_manifest_path, first_manifest.manifest_path)

        rolled_back = self.publisher.rollback()
        self.assertEqual(rolled_back.manifest_id, first_manifest.manifest_id)
        self.assertEqual(self.publisher.read_active_snapshot().model_version, "model-v1")

    def test_universe_version_and_missing_status_are_explicitly_marked(self) -> None:
        membership = UniverseMembership(
            symbol="2330",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            effective_to=None,
            data_available_time=datetime(2026, 1, 1, tzinfo=UTC),
            data_version="tw-universe-2026-01",
        )
        source = InMemoryMarketDataSource(())
        with self.assertLogs("backtest.data", level="WARNING"):
            status = source.get_trading_status(
                membership.symbol,
                datetime(2020, 1, 1, tzinfo=UTC),
            )

        self.assertEqual(membership.data_version, "tw-universe-2026-01")
        self.assertEqual(status, TradingStatus.NORMAL)
        self.assertEqual(source.gap_markers[0].kind, "TRADING_STATUS")


if __name__ == "__main__":
    unittest.main()
