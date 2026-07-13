"""Phase 3B 發布閘門、驗證器與 LKG 回滾演練測試。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from backtest.contracts import Manifest, PipelineEvent, PointInTimeSnapshot, VerificationResult
from backtest.publish import (
    InMemoryObjectStore,
    SnapshotPublisher,
    VerificationFailedError,
)
from backtest.rollback import RollbackWorkflow
from backtest.verification import SnapshotVerifier


UTC = timezone.utc
BASE_TIME = datetime(2026, 3, 1, 14, 0, tzinfo=UTC)


def make_snapshot(
    version: str,
    *,
    minutes_after_base: int,
    symbols: tuple[str, ...],
) -> PointInTimeSnapshot:
    """建立具有嚴格遞增時間的最小快照。"""
    generated_at = BASE_TIME + timedelta(minutes=minutes_after_base)
    cutoff_time = generated_at - timedelta(minutes=1)
    return PointInTimeSnapshot(
        generated_at=generated_at,
        cutoff_time=cutoff_time,
        model_version=f"model-{version}",
        feature_version="feature-v1",
        symbol_universe=symbols,
        features_data={
            symbol: {"features": {"RET_1": 0.01}, "signal": {"AI_P": 65.0}}
            for symbol in symbols
        },
        data_available_time=cutoff_time,
    )


class SnapshotVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryObjectStore()
        self.publisher = SnapshotPublisher(self.store)
        self.verifier = SnapshotVerifier(self.store)

    def publish_safe(self, version: str, minute: int, symbols: tuple[str, ...]) -> None:
        staged = self.publisher.stage(
            make_snapshot(version, minutes_after_base=minute, symbols=symbols)
        )
        self.publisher.safe_publish(staged.manifest_path)

    def test_verifier_rejects_missing_snapshot_field_and_hash_mismatch(self) -> None:
        staged = self.publisher.stage(
            make_snapshot("v0", minutes_after_base=0, symbols=("2330",))
        )
        document = json.loads(self.store.read_bytes(staged.snapshot_path))
        del document["model_version"]
        self.store.write_bytes(
            staged.snapshot_path,
            json.dumps(document, separators=(",", ":")).encode("utf-8"),
        )

        result = self.verifier.verify(staged.manifest_path, SnapshotPublisher.ACTIVE_MANIFEST_PATH)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("SHA-256" in error for error in result.errors))
        self.assertTrue(any("必要欄位" in error for error in result.errors))

    def test_manifest_and_verification_result_contracts_are_serializable(self) -> None:
        manifest = Manifest(
            manifest_version=1,
            generated_at=BASE_TIME,
            snapshots={"2330": {"path": "snapshots/2330.json", "sha256": "a" * 64}},
            previous_manifest_path=None,
        )
        restored = Manifest.from_dict(manifest.to_dict())
        result = VerificationResult(is_valid=True, errors=[], checked_at=BASE_TIME)

        self.assertEqual(restored.snapshots["2330"]["sha256"], "a" * 64)
        self.assertTrue(result.is_valid)
        with self.assertRaises(TypeError):
            restored.snapshots["2330"]["path"] = "changed.json"

    def test_verifier_rejects_insufficient_coverage_and_stale_time(self) -> None:
        symbols = tuple(f"{value:04d}" for value in range(20))
        self.publish_safe("v0", 0, symbols)
        staged = self.publisher.stage(
            make_snapshot("v1", minutes_after_base=0, symbols=symbols[:18])
        )

        result = self.verifier.verify(staged.manifest_path, SnapshotPublisher.ACTIVE_MANIFEST_PATH)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("覆蓋率" in error for error in result.errors))
        self.assertTrue(any("generated_at" in error for error in result.errors))
        self.assertTrue(any("cutoff_time" in error for error in result.errors))

    def test_publish_gate_never_cleans_a_path_supplied_by_tampered_manifest(self) -> None:
        self.publish_safe("v0", 0, ("2330", "2317"))
        active_before = self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH)
        staged = self.publisher.stage(
            make_snapshot("v1", minutes_after_base=10, symbols=("2330", "2317"))
        )
        manifest = json.loads(self.store.read_bytes(staged.manifest_path))
        manifest["snapshot_path"] = SnapshotPublisher.ACTIVE_MANIFEST_PATH
        self.store.write_bytes(
            staged.manifest_path,
            json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        )

        with self.assertLogs("backtest.publish", level="ERROR"):
            with self.assertRaises(VerificationFailedError):
                self.publisher.safe_publish(staged.manifest_path)

        self.assertEqual(
            self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH),
            active_before,
        )
        self.assertFalse(self.store.exists(staged.manifest_path))
        self.assertFalse(self.store.exists(staged.snapshot_path))


class RollbackDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryObjectStore()
        self.publisher = SnapshotPublisher(self.store)
        self.symbols = ("2330", "2317")

    def safe_stage_and_publish(self, version: str, minute: int) -> None:
        staged = self.publisher.stage(
            make_snapshot(version, minutes_after_base=minute, symbols=self.symbols)
        )
        self.publisher.safe_publish(staged.manifest_path)

    def test_corrupted_staging_is_blocked_then_active_corruption_rolls_back_to_v0(self) -> None:
        self.safe_stage_and_publish("v0", 0)
        self.safe_stage_and_publish("v1", 10)
        active_before = self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH)

        corrupted = self.publisher.stage(
            make_snapshot("v2", minutes_after_base=20, symbols=self.symbols)
        )
        self.store.write_bytes(corrupted.snapshot_path, b'{"broken":true}')
        with self.assertLogs("backtest.publish", level="ERROR"):
            with self.assertRaises(VerificationFailedError):
                self.publisher.safe_publish(corrupted.manifest_path)

        self.assertEqual(
            self.store.read_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH),
            active_before,
        )
        self.assertEqual(self.publisher.read_active_snapshot().model_version, "model-v1")
        self.assertFalse(self.store.exists(corrupted.manifest_path))
        self.assertFalse(self.store.exists(corrupted.snapshot_path))

        active_manifest = self.publisher.get_active_manifest()
        assert active_manifest is not None
        self.store.write_bytes(active_manifest.snapshot_path, b"{}")
        events: list[PipelineEvent] = []
        workflow = RollbackWorkflow(self.store, event_sink=events.append)
        with self.assertLogs("backtest.rollback", level="WARNING"):
            restored_manifest = workflow.trigger_rollback(SnapshotPublisher.ACTIVE_MANIFEST_PATH)

        self.assertEqual(restored_manifest.manifest_version, 1)
        self.assertEqual(self.publisher.read_active_snapshot().model_version, "model-v0")
        self.assertEqual(events[0].event_type, "ROLLBACK_TRIGGERED")

    def test_rollback_uses_lkg_copy_when_active_manifest_is_unreadable(self) -> None:
        self.safe_stage_and_publish("v0", 0)
        self.safe_stage_and_publish("v1", 10)
        active_manifest = self.publisher.get_active_manifest()
        assert active_manifest is not None
        self.store.write_bytes(active_manifest.snapshot_path, b"{}")
        self.store.write_bytes(SnapshotPublisher.ACTIVE_MANIFEST_PATH, b"not-json")

        workflow = RollbackWorkflow(self.store)
        with self.assertLogs("backtest.rollback", level="WARNING"):
            workflow.trigger_rollback(SnapshotPublisher.ACTIVE_MANIFEST_PATH)

        self.assertEqual(self.publisher.read_active_snapshot().model_version, "model-v0")


if __name__ == "__main__":
    unittest.main()
