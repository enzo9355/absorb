# -*- coding: utf-8 -*-
"""Immutable publisher for RegressionInputDataset objects."""

import hmac
import hashlib
import json
import os
from typing import Any

from reporting.regression_input_schema import (
    MAX_REGRESSION_INPUT_DATASET_BYTES,
    RegressionInputDataset,
    compute_canonical_rows_sha256,
    serialize_regression_input_dataset,
)

PUBLISH_ROOT = "publish"


def publish_regression_input_dataset(
    dataset_doc: dict[str, Any] | RegressionInputDataset,
    publish_root: str | None = None,
) -> dict[str, Any]:
    """Execute 11-step atomic publication sequence for RegressionInputDataset."""
    root = publish_root if publish_root is not None else PUBLISH_ROOT

    # 1. Validate RegressionInputDataset instance/document
    if isinstance(dataset_doc, RegressionInputDataset):
        dataset_obj = dataset_doc
        doc = dataset_obj.to_document()
    else:
        doc = dataset_doc
        dataset_obj = RegressionInputDataset.from_document(doc)

    # 2. serialize_regression_input_dataset() ONCE
    dataset_bytes = serialize_regression_input_dataset(doc)

    # 3. Check MAX_REGRESSION_INPUT_DATASET_BYTES
    if len(dataset_bytes) > MAX_REGRESSION_INPUT_DATASET_BYTES:
        raise ValueError(f"Oversized input dataset: {len(dataset_bytes)} > {MAX_REGRESSION_INPUT_DATASET_BYTES}")

    # 4. object_sha256 = SHA256(exact bytes)
    object_sha256 = hashlib.sha256(dataset_bytes).hexdigest()

    # 5. object_path = objects/regression-input/<object_sha256>.json
    object_path = f"objects/regression-input/{object_sha256}.json"
    full_path = os.path.join(root, object_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # 6. Immutable conflict check: fail closed if byte mismatch
    if os.path.exists(full_path):
        with open(full_path, "rb") as f:
            existing_bytes = f.read()
        if not hmac.compare_digest(hashlib.sha256(existing_bytes).hexdigest(), object_sha256):
            raise ValueError(f"Immutable object conflict at {object_path}: existing bytes hash mismatch")

    # 7. Write atomic
    temp_path = f"{full_path}.tmp_{os.getpid()}"
    try:
        with open(temp_path, "wb") as f:
            f.write(dataset_bytes)
        os.replace(temp_path, full_path)
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise RuntimeError(f"Failed atomic write for {object_path}: {exc}") from exc

    # 8. Read-back raw bytes
    try:
        with open(full_path, "rb") as f:
            readback_bytes = f.read()
    except Exception as exc:
        raise RuntimeError(f"Read-back failed for {object_path}: {exc}") from exc

    # 9. Verify size / SHA / UTF-8 / JSON / Schema
    if len(readback_bytes) != len(dataset_bytes):
        raise ValueError(f"Read-back size mismatch for {object_path}: {len(readback_bytes)} != {len(dataset_bytes)}")

    readback_sha = hashlib.sha256(readback_bytes).hexdigest()
    if not hmac.compare_digest(readback_sha, object_sha256):
        raise ValueError(f"Read-back SHA256 mismatch for {object_path}")

    try:
        readback_doc = json.loads(readback_bytes.decode("utf-8"))
        readback_obj = RegressionInputDataset.from_document(readback_doc)
    except Exception as exc:
        raise ValueError(f"Read-back JSON/Schema validation failed for {object_path}: {exc}") from exc

    # 10. Verify content_sha256 / canonical_rows_sha256
    expected_content_sha = dataset_obj.identity.content_sha256
    if expected_content_sha and not hmac.compare_digest(readback_obj.identity.content_sha256, expected_content_sha):
        raise ValueError(f"Read-back content_sha256 mismatch for {object_path}")

    actual_rows_sha = compute_canonical_rows_sha256(readback_doc.get("rows", []))
    if not hmac.compare_digest(actual_rows_sha, dataset_obj.identity.canonical_rows_sha256):
        raise ValueError(f"Read-back canonical_rows_sha256 mismatch for {object_path}")

    # 11. Return pointer dict
    return {
        "object": object_path,
        "sha256": object_sha256,
        "content_sha256": readback_obj.identity.content_sha256,
        "rows_sha256": actual_rows_sha,
        "schema_version": readback_obj.schema_version,
        "row_count": readback_obj.identity.row_count,
    }
