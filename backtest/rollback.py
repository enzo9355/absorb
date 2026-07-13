"""沿 manifest 單向版本鏈尋找 LKG 並原子回滾。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from .contracts import EventSeverity, PipelineEvent, SnapshotManifest
from .verification import SnapshotStore, SnapshotVerifier


logger = logging.getLogger(__name__)


class RollbackError(RuntimeError):
    """找不到可驗證的歷史快照或無法完成回滾時拋出。"""


class RollbackStore(SnapshotStore, Protocol):
    """回滾需要額外支援原子覆寫的物件儲存介面。"""

    def atomic_replace(self, path: str, content: bytes) -> None:
        ...


class RollbackWorkflow:
    """不依賴全域狀態的 LKG 搜尋與回滾工作流。"""

    def __init__(
        self,
        store: RollbackStore,
        *,
        lkg_manifest_path: str = "lkg_manifest.json",
        event_sink: Callable[[PipelineEvent], None] | None = None,
    ) -> None:
        self._store = store
        self._lkg_manifest_path = lkg_manifest_path
        self._verifier = SnapshotVerifier(store)
        self._event_sink = event_sink

    def find_last_known_good(self, current_manifest_path: str) -> str:
        """由現行 manifest 向前回溯，找出最近通過獨立驗證的版本。"""
        pending_paths = [current_manifest_path]
        seen_paths: set[str] = set()
        lkg_queued = False

        while pending_paths:
            path = pending_paths.pop(0)
            if path in seen_paths:
                continue
            seen_paths.add(path)

            manifest = self._try_read_manifest(path)
            verification = self._verifier.verify_manifest(path)
            if verification.is_valid:
                return path

            if manifest is not None and manifest.previous_manifest_path is not None:
                pending_paths.append(manifest.previous_manifest_path)
                continue
            if not lkg_queued and self._lkg_manifest_path not in seen_paths:
                if self._store.exists(self._lkg_manifest_path):
                    pending_paths.append(self._lkg_manifest_path)
                    lkg_queued = True

        raise RollbackError("找不到通過快照驗證的 Last Known Good manifest")

    def trigger_rollback(self, production_manifest_path: str) -> SnapshotManifest:
        """選取 LKG 後只原子覆寫正式 manifest 指標。"""
        try:
            lkg_path = self.find_last_known_good(production_manifest_path)
            content = self._store.read_bytes(lkg_path)
            manifest = self._parse_manifest(content)
            self._store.atomic_replace(production_manifest_path, content)
            self._store.atomic_replace(self._lkg_manifest_path, content)
        except Exception as exc:
            self._emit_event(
                "ROLLBACK_FAILED",
                EventSeverity.CRITICAL,
                {"operation": "trigger_rollback", "error_type": type(exc).__name__},
            )
            raise
        logger.warning("快照已回滾至 LKG manifest：%s", manifest.manifest_id)
        self._emit_event(
            "ROLLBACK_TRIGGERED",
            EventSeverity.CRITICAL,
            {
                "lkg_manifest_id": manifest.manifest_id,
                "lkg_manifest_version": manifest.manifest_version,
                "lkg_manifest_path": lkg_path,
            },
        )
        return manifest

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

    def _try_read_manifest(self, path: str) -> SnapshotManifest | None:
        try:
            return self._parse_manifest(self._store.read_bytes(path))
        except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_manifest(content: bytes) -> SnapshotManifest:
        document = json.loads(content.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("manifest 必須為物件")
        return SnapshotManifest.from_dict(document)
