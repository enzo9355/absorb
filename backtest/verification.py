"""快照發布前的 schema、完整性與版本一致性驗證。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping, Protocol

from .contracts import PointInTimeSnapshot, SnapshotManifest, VerificationResult


class SnapshotStore(Protocol):
    """驗證器需要的唯讀物件儲存介面。"""

    def exists(self, path: str) -> bool:
        ...

    def read_bytes(self, path: str) -> bytes:
        ...


class SnapshotVerifier:
    """以不修改物件的方式驗證 staging 或歷史快照。"""

    _REQUIRED_SNAPSHOT_FIELDS = frozenset(
        {
            "schema_version",
            "generated_at",
            "cutoff_time",
            "model_version",
            "feature_version",
            "symbol_universe",
            "features_data",
            "data_available_time",
        }
    )

    def __init__(
        self,
        store: SnapshotStore,
        *,
        minimum_coverage: float = 0.95,
        minimum_initial_symbols: int = 1,
        minimum_snapshot_bytes: int = 2,
    ) -> None:
        if not 0.0 < minimum_coverage <= 1.0:
            raise ValueError("minimum_coverage 必須介於 0 與 1")
        if minimum_initial_symbols < 1 or minimum_snapshot_bytes < 1:
            raise ValueError("快照最小門檻必須大於零")
        self._store = store
        self._minimum_coverage = minimum_coverage
        self._minimum_initial_symbols = minimum_initial_symbols
        self._minimum_snapshot_bytes = minimum_snapshot_bytes

    def verify(
        self,
        staging_manifest_path: str,
        production_manifest_path: str | None,
    ) -> VerificationResult:
        """驗證 staging 快照；若已有正式版，額外檢查覆蓋率與版本遞增。"""
        return self._verify(
            staging_manifest_path,
            production_manifest_path=production_manifest_path,
            require_progression=production_manifest_path is not None
            and self._store.exists(production_manifest_path),
            require_staging_layout=True,
        )

    def verify_manifest(self, manifest_path: str) -> VerificationResult:
        """驗證單一歷史 manifest，不要求相對於正式版遞增。"""
        return self._verify(
            manifest_path,
            production_manifest_path=None,
            require_progression=False,
            require_staging_layout=False,
        )

    def _verify(
        self,
        candidate_manifest_path: str,
        *,
        production_manifest_path: str | None,
        require_progression: bool,
        require_staging_layout: bool,
    ) -> VerificationResult:
        errors: list[str] = []
        manifest = self._read_manifest(candidate_manifest_path, errors, "候選")
        snapshot = self._read_snapshot(manifest, errors)

        if manifest is not None and snapshot is not None:
            if require_staging_layout:
                expected_root = f"staging/{manifest.manifest_id}"
                if candidate_manifest_path != f"{expected_root}/manifest.json.tmp":
                    errors.append("暫存 manifest 路徑不符合 stage 識別碼")
                if manifest.manifest_path != candidate_manifest_path:
                    errors.append("manifest 內記錄的路徑與實體路徑不一致")
                if manifest.snapshot_path != f"{expected_root}/snapshot.json":
                    errors.append("暫存快照路徑不符合 stage 識別碼")
            if manifest.symbol_count != len(snapshot.symbol_universe):
                errors.append("manifest 標的數與快照 Universe 不一致")
            if manifest.symbol_count < self._minimum_initial_symbols:
                errors.append("初始快照標的數不足")

        if require_progression and manifest is not None and snapshot is not None:
            assert production_manifest_path is not None
            previous_manifest = self._read_manifest(
                production_manifest_path,
                errors,
                "正式",
            )
            previous_snapshot = self._read_snapshot(previous_manifest, errors)
            if previous_manifest is not None and previous_snapshot is not None:
                self._validate_progression(
                    manifest,
                    snapshot,
                    previous_manifest,
                    previous_snapshot,
                    errors,
                )

        return VerificationResult(
            is_valid=not errors,
            errors=errors,
            checked_at=datetime.now(timezone.utc),
        )

    def _read_manifest(
        self,
        path: str,
        errors: list[str],
        label: str,
    ) -> SnapshotManifest | None:
        document = self._read_json_object(path, errors, f"{label} manifest")
        if document is None:
            return None
        try:
            return SnapshotManifest.from_dict(document)
        except ValueError as exc:
            errors.append(f"{label} manifest schema 不合法：{exc}")
            return None

    def _read_snapshot(
        self,
        manifest: SnapshotManifest | None,
        errors: list[str],
    ) -> PointInTimeSnapshot | None:
        if manifest is None:
            return None
        try:
            content = self._store.read_bytes(manifest.snapshot_path)
        except (FileNotFoundError, OSError) as exc:
            errors.append(f"快照檔案無法讀取：{exc}")
            return None
        if len(content) < self._minimum_snapshot_bytes:
            errors.append("快照檔案大小不足")
            return None
        if len(content) != manifest.snapshot_size:
            errors.append("快照檔案大小與 manifest 不一致")
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != manifest.snapshot_sha256:
            errors.append("快照 SHA-256 與 manifest 不一致")

        try:
            document = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"快照 JSON 毀損：{exc}")
            return None
        if not isinstance(document, dict):
            errors.append("快照 JSON 必須為物件")
            return None
        missing_fields = self._REQUIRED_SNAPSHOT_FIELDS - document.keys()
        if missing_fields:
            errors.append(f"快照缺少必要欄位：{','.join(sorted(missing_fields))}")
            return None
        try:
            return PointInTimeSnapshot.from_dict(document)
        except ValueError as exc:
            errors.append(f"快照 schema 不合法：{exc}")
            return None

    def _read_json_object(
        self,
        path: str,
        errors: list[str],
        label: str,
    ) -> Mapping[str, object] | None:
        try:
            content = self._store.read_bytes(path)
            document = json.loads(content.decode("utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{label} 無法讀取：{exc}")
            return None
        if not isinstance(document, dict):
            errors.append(f"{label} 必須為物件")
            return None
        return document

    def _validate_progression(
        self,
        manifest: SnapshotManifest,
        snapshot: PointInTimeSnapshot,
        previous_manifest: SnapshotManifest,
        previous_snapshot: PointInTimeSnapshot,
        errors: list[str],
    ) -> None:
        required_symbols = math.ceil(previous_manifest.symbol_count * self._minimum_coverage)
        if manifest.symbol_count < required_symbols:
            errors.append("快照覆蓋率低於正式版本的 95% 門檻")
        if snapshot.generated_at <= previous_snapshot.generated_at:
            errors.append("快照 generated_at 必須嚴格晚於正式版本")
        if snapshot.cutoff_time <= previous_snapshot.cutoff_time:
            errors.append("快照 cutoff_time 必須嚴格晚於正式版本")
        if snapshot.snapshot_version != previous_snapshot.snapshot_version + 1:
            errors.append("snapshot_version 未正確遞增")
        if manifest.manifest_version != previous_manifest.manifest_version + 1:
            errors.append("manifest_version 未正確遞增")
