# -*- coding: utf-8 -*-
"""Offline raw bytes loader for RegressionInputDataset objects."""

import hmac
import hashlib
import json
import os
import re
from typing import Any

from reporting.regression_input_schema import (
    MAX_REGRESSION_INPUT_DATASET_BYTES,
    RegressionInputDataset,
    compute_canonical_rows_sha256,
)

INPUT_DATASET_PATH_RE = re.compile(r"^objects/regression-input/[0-9a-f]{64}\.json$")


def get_raw_object_bytes(object_path: str, max_bytes: int = MAX_REGRESSION_INPUT_DATASET_BYTES) -> bytes | None:
    """Default local filesystem / publish directory loader for object bytes."""
    full_path = os.path.join("publish", object_path)
    if not os.path.exists(full_path):
        return None
    try:
        size = os.path.getsize(full_path)
        if size == 0 or size > max_bytes:
            return None
        with open(full_path, "rb") as f:
            data = f.read(max_bytes + 1)
        if len(data) > max_bytes or len(data) == 0:
            return None
        return data
    except Exception:
        return None


def load_regression_input_dataset(
    object_path: str,
    expected_sha256: str,
    max_bytes: int = MAX_REGRESSION_INPUT_DATASET_BYTES,
) -> RegressionInputDataset | None:
    """Load, verify bytes/SHA, parse, and validate RegressionInputDataset object."""
    if not isinstance(object_path, str) or not INPUT_DATASET_PATH_RE.fullmatch(object_path):
        return None
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        return None
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not (1 <= max_bytes <= MAX_REGRESSION_INPUT_DATASET_BYTES):
        return None

    raw_bytes = get_raw_object_bytes(object_path, max_bytes=max_bytes)
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) == 0 or len(raw_bytes) > max_bytes:
        return None

    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
        return None

    path_sha = object_path.split("/")[-1].replace(".json", "")
    if not hmac.compare_digest(actual_sha256, path_sha.lower()):
        return None

    try:
        text = raw_bytes.decode("utf-8")
        document = json.loads(text)
        if not isinstance(document, dict):
            return None
        dataset = RegressionInputDataset.from_document(document)
        expected_rows_sha = dataset.identity.canonical_rows_sha256
        actual_rows_sha = compute_canonical_rows_sha256(document.get("rows", []))
        if not hmac.compare_digest(actual_rows_sha, expected_rows_sha.lower()):
            return None
        return dataset
    except Exception:
        return None
