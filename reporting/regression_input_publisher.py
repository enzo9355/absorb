# -*- coding: utf-8 -*-
"""Immutable publisher for validated RegressionInputDataset objects."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from reporting.regression_input_schema import (
    MAX_REGRESSION_INPUT_DATASET_BYTES,
    RegressionInputDataset,
    TradingCalendar,
    serialize_regression_input_dataset,
)


PUBLISH_ROOT = "publish"


def _write_temporary(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return temporary


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = _write_temporary(path, content)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_immutable(path: Path, content: bytes) -> bool:
    """Publish complete bytes without replacing another writer's object."""
    temporary = _write_temporary(path, content)
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError(f"immutable input dataset conflict at {path}")
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _validate_readback(
    payload: bytes,
    *,
    expected_size: int,
    expected_sha256: str,
    trading_calendar: TradingCalendar,
) -> RegressionInputDataset:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_REGRESSION_INPUT_DATASET_BYTES:
        raise ValueError("read-back size is outside allowed range")
    if len(payload) != expected_size:
        raise ValueError("read-back size mismatch")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("read-back SHA256 mismatch")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("read-back is not valid UTF-8") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("read-back is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("read-back schema must be a JSON object")
    try:
        return RegressionInputDataset.from_document(
            document,
            trading_calendar=trading_calendar,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"read-back schema validation failed: {exc}") from exc


def _cleanup_new(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"input dataset cleanup failed: {exc}") from exc


def _pointer(path: str, sha256: str, dataset: RegressionInputDataset) -> dict[str, Any]:
    return {
        "object": path,
        "sha256": sha256,
        "content_sha256": dataset.identity.content_sha256,
        "rows_sha256": dataset.identity.canonical_rows_sha256,
        "schema_version": dataset.schema_version,
        "row_count": dataset.identity.row_count,
    }


def publish_regression_input_dataset(
    dataset_doc: dict[str, Any] | RegressionInputDataset,
    publish_root: str | Path | None = None,
    *,
    trading_calendar: TradingCalendar,
) -> dict[str, Any]:
    """Validate, write once, verify exact bytes, and return a content pointer."""
    document = (
        dataset_doc.to_document()
        if isinstance(dataset_doc, RegressionInputDataset)
        else dataset_doc
    )
    dataset = RegressionInputDataset.from_document(
        document,
        trading_calendar=trading_calendar,
    )

    payload = serialize_regression_input_dataset(document)
    if not 0 < len(payload) <= MAX_REGRESSION_INPUT_DATASET_BYTES:
        raise ValueError("input dataset size is outside allowed range")
    object_sha256 = hashlib.sha256(payload).hexdigest()
    relative_path = f"objects/regression-input/{object_sha256}.json"
    root = Path(publish_root if publish_root is not None else PUBLISH_ROOT)
    object_path = root / relative_path

    created_by_this_transaction = False
    if object_path.exists():
        try:
            existing = object_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"input dataset read-back failed: {exc}") from exc
        if existing != payload:
            raise ValueError(f"immutable input dataset conflict at {relative_path}")
        verified = _validate_readback(
            existing,
            expected_size=len(payload),
            expected_sha256=object_sha256,
            trading_calendar=trading_calendar,
        )
        return _pointer(relative_path, object_sha256, verified)

    try:
        created_by_this_transaction = _write_immutable(object_path, payload)
    except ValueError:
        raise
    except Exception as exc:
        if created_by_this_transaction:
            _cleanup_new(object_path)
        raise RuntimeError(f"input dataset write failed: {exc}") from exc

    try:
        readback = object_path.read_bytes()
    except OSError as exc:
        if created_by_this_transaction:
            _cleanup_new(object_path)
        raise RuntimeError(f"input dataset read-back failed: {exc}") from exc

    try:
        verified = _validate_readback(
            readback,
            expected_size=len(payload),
            expected_sha256=object_sha256,
            trading_calendar=trading_calendar,
        )
    except Exception:
        if created_by_this_transaction:
            _cleanup_new(object_path)
        raise
    return _pointer(relative_path, object_sha256, verified)
