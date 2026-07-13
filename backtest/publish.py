"""Point-in-time 快照的 staging、驗證、原子發布與回滾管道。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import threading
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from .contracts import EventSeverity, PipelineEvent, PointInTimeSnapshot, SnapshotManifest


logger = logging.getLogger(__name__)


class ValidationError(RuntimeError):
    """暫存快照不符合發布條件時拋出，正式 manifest 不可被改動。"""


class VerificationFailedError(ValidationError):
    """生產發布閘門拒絕暫存快照時拋出。"""


class ObjectStore(Protocol):
    """發布器所需的最小物件儲存介面。"""

    def exists(self, path: str) -> bool:
        ...

    def read_bytes(self, path: str) -> bytes:
        ...

    def write_bytes(self, path: str, content: bytes, *, if_absent: bool = False) -> None:
        ...

    def atomic_replace(self, path: str, content: bytes) -> None:
        ...

    def delete(self, path: str) -> None:
        ...


class GCSBlob(Protocol):
    """避免直接依賴 google-cloud-storage 的最小 Blob 介面。"""

    def exists(self) -> bool:
        ...

    def download_as_bytes(self) -> bytes:
        ...

    def upload_from_string(self, data: bytes, **kwargs: object) -> None:
        ...

    def delete(self) -> None:
        ...


class GCSBucket(Protocol):
    """可由實際 GCS Bucket 物件實作的最小介面。"""

    def blob(self, blob_name: str) -> GCSBlob:
        ...


class GCSObjectStore:
    """以單一物件覆寫提供讀取端原子可見性的 GCS adapter。"""

    def __init__(self, bucket: GCSBucket) -> None:
        self._bucket = bucket

    def exists(self, path: str) -> bool:
        return self._bucket.blob(path).exists()

    def read_bytes(self, path: str) -> bytes:
        return self._bucket.blob(path).download_as_bytes()

    def write_bytes(self, path: str, content: bytes, *, if_absent: bool = False) -> None:
        options: dict[str, object] = {"content_type": "application/json"}
        if if_absent:
            options["if_generation_match"] = 0
        self._bucket.blob(path).upload_from_string(content, **options)

    def atomic_replace(self, path: str, content: bytes) -> None:
        """GCS 單一物件覆寫對讀取端具原子可見性，不使用 copy/delete rename。"""
        # ponytail: 假設既有 runner lock 僅允許一個發布者；平行發布時加入 generation precondition。
        self._bucket.blob(path).upload_from_string(
            content,
            content_type="application/json",
        )

    def delete(self, path: str) -> None:
        self._bucket.blob(path).delete()


class InMemoryObjectStore:
    """供單元測試驗證發布語意的執行緒安全物件儲存。"""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def exists(self, path: str) -> bool:
        with self._lock:
            return path in self._objects

    def read_bytes(self, path: str) -> bytes:
        with self._lock:
            try:
                return self._objects[path]
            except KeyError as exc:
                raise FileNotFoundError(path) from exc

    def write_bytes(self, path: str, content: bytes, *, if_absent: bool = False) -> None:
        with self._lock:
            if if_absent and path in self._objects:
                raise FileExistsError(path)
            self._objects[path] = bytes(content)

    def atomic_replace(self, path: str, content: bytes) -> None:
        with self._lock:
            self._objects[path] = bytes(content)

    def delete(self, path: str) -> None:
        with self._lock:
            self._objects.pop(path, None)


@dataclass(frozen=True, slots=True)
class StagedSnapshot:
    """暫存快照與 manifest.tmp 的可驗證位置。"""

    stage_id: str
    snapshot_path: str
    manifest_path: str


def _json_bytes(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SnapshotPublisher:
    """只在 staging 驗證完成後才切換正式 manifest 的發布器。"""

    ACTIVE_MANIFEST_PATH = "manifest.json"
    LKG_MANIFEST_PATH = "lkg_manifest.json"

    def __init__(
        self,
        store: ObjectStore,
        *,
        minimum_coverage: float = 0.9,
        minimum_snapshot_bytes: int = 2,
        event_sink: Callable[[PipelineEvent], None] | None = None,
    ) -> None:
        if not 0.0 < minimum_coverage <= 1.0 or minimum_snapshot_bytes < 1:
            raise ValueError("發布驗證設定不合法")
        self._store = store
        self._minimum_coverage = minimum_coverage
        self._minimum_snapshot_bytes = minimum_snapshot_bytes
        self._event_sink = event_sink

    def stage(self, snapshot: PointInTimeSnapshot) -> StagedSnapshot:
        """先寫入不可見於讀取端的快照與 manifest.json.tmp。"""
        snapshot, manifest_version = self._with_next_versions(snapshot)
        snapshot_bytes = _json_bytes(snapshot.to_dict())
        snapshot_hash = _sha256(snapshot_bytes)
        stage_id = self._stage_id(snapshot.generated_at, snapshot_hash)
        snapshot_path = f"staging/{stage_id}/snapshot.json"
        manifest_path = f"staging/{stage_id}/manifest.json.tmp"
        manifest = SnapshotManifest(
            manifest_id=stage_id,
            generated_at=snapshot.generated_at,
            snapshot_path=snapshot_path,
            snapshot_sha256=snapshot_hash,
            snapshot_size=len(snapshot_bytes),
            symbol_count=len(snapshot.symbol_universe),
            manifest_path=manifest_path,
            previous_manifest_path=None,
            manifest_version=manifest_version,
        )
        self._store.write_bytes(snapshot_path, snapshot_bytes)
        self._store.write_bytes(manifest_path, _json_bytes(manifest.to_dict()))
        return StagedSnapshot(stage_id, snapshot_path, manifest_path)

    def validate(
        self,
        staged: StagedSnapshot,
        production_manifest_path: str = ACTIVE_MANIFEST_PATH,
    ) -> tuple[PointInTimeSnapshot, SnapshotManifest]:
        """驗證暫存物件，不允許此步驟修改正式 manifest。"""
        manifest = self._read_manifest(staged.manifest_path)
        if manifest.manifest_id != staged.stage_id or manifest.snapshot_path != staged.snapshot_path:
            raise ValidationError("暫存 manifest 與 stage 路徑不一致")
        content = self._store.read_bytes(staged.snapshot_path)
        if len(content) < self._minimum_snapshot_bytes:
            raise ValidationError("暫存快照大小不足")
        if len(content) != manifest.snapshot_size or _sha256(content) != manifest.snapshot_sha256:
            raise ValidationError("暫存快照雜湊或大小不一致")
        snapshot = self._read_snapshot(content)
        if len(snapshot.symbol_universe) != manifest.symbol_count:
            raise ValidationError("manifest 標的數與快照 Universe 不一致")
        previous = self._get_manifest(production_manifest_path)
        if previous is not None:
            required = math.ceil(previous.symbol_count * self._minimum_coverage)
            if manifest.symbol_count < required:
                raise ValidationError("快照覆蓋率低於前次發布門檻")
        return snapshot, manifest

    def publish(self, staged: StagedSnapshot) -> SnapshotManifest:
        """先完成版本化物件，再原子替換正式 manifest 指標。"""
        snapshot, staged_manifest = self.validate(staged)
        return self._publish_staged(
            staged,
            staged_manifest,
            self.ACTIVE_MANIFEST_PATH,
            retain_as_lkg=False,
        )

    def safe_publish(
        self,
        staging_manifest_path: str,
        production_manifest_path: str = ACTIVE_MANIFEST_PATH,
    ) -> SnapshotManifest:
        """通過 Phase 3B 發布閘門後，才原子替換正式 manifest。"""
        from .verification import SnapshotVerifier

        verifier = SnapshotVerifier(
            self._store,
            minimum_coverage=0.95,
            minimum_snapshot_bytes=self._minimum_snapshot_bytes,
        )
        result = verifier.verify(staging_manifest_path, production_manifest_path)
        if not result.is_valid:
            reason = "; ".join(result.errors)
            self._cleanup_staging(staging_manifest_path)
            logger.error("快照發布驗證失敗：%s", reason)
            self._emit_event(
                "VALIDATION_FAILED",
                EventSeverity.CRITICAL,
                {
                    "staging_manifest_path": staging_manifest_path,
                    "validation_error_count": len(result.errors),
                },
            )
            raise VerificationFailedError(reason)

        try:
            staged_manifest = self._read_manifest(staging_manifest_path)
            staged = StagedSnapshot(
                stage_id=staged_manifest.manifest_id,
                snapshot_path=staged_manifest.snapshot_path,
                manifest_path=staging_manifest_path,
            )
            _, staged_manifest = self.validate(staged, production_manifest_path)
        except (FileNotFoundError, OSError, ValidationError) as exc:
            self._cleanup_staging(staging_manifest_path)
            logger.error("快照發布驗證失敗：%s", exc)
            self._emit_event(
                "VALIDATION_FAILED",
                EventSeverity.CRITICAL,
                {
                    "staging_manifest_path": staging_manifest_path,
                    "error_type": type(exc).__name__,
                },
            )
            raise VerificationFailedError(str(exc)) from exc

        try:
            manifest = self._publish_staged(
                staged,
                staged_manifest,
                production_manifest_path,
                retain_as_lkg=True,
            )
        except Exception as exc:
            self._emit_event(
                "PIPELINE_FAILED",
                EventSeverity.CRITICAL,
                {"operation": "safe_publish", "error_type": type(exc).__name__},
            )
            raise
        self._emit_event(
            "PUBLISHED",
            EventSeverity.SUCCESS,
            {
                "manifest_id": manifest.manifest_id,
                "manifest_version": manifest.manifest_version,
                "symbol_count": manifest.symbol_count,
            },
        )
        return manifest

    def _publish_staged(
        self,
        staged: StagedSnapshot,
        staged_manifest: SnapshotManifest,
        production_manifest_path: str,
        *,
        retain_as_lkg: bool,
    ) -> SnapshotManifest:
        snapshot_bytes = self._store.read_bytes(staged.snapshot_path)
        release_snapshot_path = f"snapshots/{staged.stage_id}.json"
        self._write_immutable(release_snapshot_path, snapshot_bytes)
        if _sha256(self._store.read_bytes(release_snapshot_path)) != staged_manifest.snapshot_sha256:
            raise ValidationError("版本化快照雜湊不一致")

        previous = self._get_manifest(production_manifest_path)
        manifest_path = f"manifests/{staged.stage_id}.json"
        manifest = replace(
            staged_manifest,
            snapshot_path=release_snapshot_path,
            manifest_path=manifest_path,
            previous_manifest_path=(previous.manifest_path if previous else None),
        )
        manifest_bytes = _json_bytes(manifest.to_dict())
        self._write_immutable(manifest_path, manifest_bytes)
        self._store.atomic_replace(production_manifest_path, manifest_bytes)
        if retain_as_lkg and production_manifest_path == self.ACTIVE_MANIFEST_PATH:
            self._store.atomic_replace(self.LKG_MANIFEST_PATH, manifest_bytes)
        return manifest

    def get_active_manifest(self) -> SnapshotManifest | None:
        """正式讀取端只經由固定 manifest.json 尋找已驗證快照。"""
        return self._get_manifest(self.ACTIVE_MANIFEST_PATH)

    def read_active_snapshot(self) -> PointInTimeSnapshot:
        """讀取端再次驗證 hash，避免儲存層毀損被靜默接受。"""
        manifest = self.get_active_manifest()
        if manifest is None:
            raise FileNotFoundError(self.ACTIVE_MANIFEST_PATH)
        content = self._store.read_bytes(manifest.snapshot_path)
        if len(content) != manifest.snapshot_size or _sha256(content) != manifest.snapshot_sha256:
            raise ValidationError("正式快照雜湊或大小不一致")
        return self._read_snapshot(content)

    def rollback(self) -> SnapshotManifest:
        """將正式指標回指到前一個歷史 manifest，保留單向版本鏈。"""
        current = self.get_active_manifest()
        if current is None or current.previous_manifest_path is None:
            raise ValidationError("沒有可回滾的前一版 manifest")
        previous_bytes = self._store.read_bytes(current.previous_manifest_path)
        previous = self._read_manifest_bytes(previous_bytes)
        snapshot_content = self._store.read_bytes(previous.snapshot_path)
        if _sha256(snapshot_content) != previous.snapshot_sha256:
            raise ValidationError("回滾目標快照雜湊不一致")
        self._store.atomic_replace(self.ACTIVE_MANIFEST_PATH, previous_bytes)
        self._store.atomic_replace(self.LKG_MANIFEST_PATH, previous_bytes)
        return previous

    def _with_next_versions(
        self,
        snapshot: PointInTimeSnapshot,
    ) -> tuple[PointInTimeSnapshot, int]:
        previous = self.get_active_manifest()
        if previous is None:
            return replace(snapshot, snapshot_version=1), 1
        previous_snapshot = self._read_snapshot(self._store.read_bytes(previous.snapshot_path))
        return (
            replace(snapshot, snapshot_version=previous_snapshot.snapshot_version + 1),
            previous.manifest_version + 1,
        )

    def _cleanup_staging(self, staging_manifest_path: str) -> None:
        """只移除本次 staging 的已知暫存物件，正式區不可被觸及。"""
        if not staging_manifest_path.startswith("staging/") or not staging_manifest_path.endswith(
            "/manifest.json.tmp"
        ):
            logger.warning("拒絕清理非 staging 路徑：%s", staging_manifest_path)
            return
        stage_root = staging_manifest_path.rsplit("/", 1)[0]
        for path in (staging_manifest_path, f"{stage_root}/snapshot.json"):
            self._store.delete(path)

    def _emit_event(
        self,
        event_type: str,
        severity: EventSeverity,
        details: Mapping[str, object],
    ) -> None:
        if self._event_sink is None:
            return
        event = PipelineEvent(
            event_id=uuid4().hex,
            event_type=event_type,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
            details=details,
        )
        try:
            self._event_sink(event)
        except Exception as exc:
            logger.error("監控事件處理失敗：%s", type(exc).__name__)

    def _write_immutable(self, path: str, content: bytes) -> None:
        if self._store.exists(path):
            if self._store.read_bytes(path) != content:
                raise ValidationError("版本化物件路徑已被不同內容占用")
            return
        self._store.write_bytes(path, content, if_absent=True)

    @staticmethod
    def _stage_id(generated_at: datetime, snapshot_hash: str) -> str:
        return f"{generated_at.strftime('%Y%m%dT%H%M%S%f%z')}-{snapshot_hash[:12]}"

    def _read_manifest(self, path: str) -> SnapshotManifest:
        return self._read_manifest_bytes(self._store.read_bytes(path))

    def _get_manifest(self, path: str) -> SnapshotManifest | None:
        if not self._store.exists(path):
            return None
        return self._read_manifest(path)

    @staticmethod
    def _read_manifest_bytes(content: bytes) -> SnapshotManifest:
        try:
            document = json.loads(content.decode("utf-8"))
            if not isinstance(document, dict):
                raise ValueError("manifest 必須為物件")
            return SnapshotManifest.from_dict(document)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValidationError("manifest JSON 毀損或 schema 不合法") from exc

    @staticmethod
    def _read_snapshot(content: bytes) -> PointInTimeSnapshot:
        try:
            document = json.loads(content.decode("utf-8"))
            if not isinstance(document, dict):
                raise ValueError("snapshot 必須為物件")
            return PointInTimeSnapshot.from_dict(document)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValidationError("snapshot JSON 毀損或 schema 不合法") from exc
