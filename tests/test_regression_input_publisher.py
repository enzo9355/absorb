# -*- coding: utf-8 -*-
"""Tests for immutable RegressionInputDataset publisher."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch


class TestRegressionInputPublisher(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.publish_dir = os.path.join(self.test_dir, "publish")
        os.makedirs(os.path.join(self.publish_dir, "objects", "regression-input"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_publishes_input_dataset_atomically_with_readback(self):
        from reporting.regression_input_publisher import publish_regression_input_dataset
        from reporting.regression_input_schema import compute_canonical_rows_sha256, compute_regression_input_dataset_content_sha256

        rows = [
            {
                "feature_session": "2025-07-10",
                "label_end_session": "2025-07-17",
                "taiex_close_t": 22450.15,
                "taiex_close_t_plus_5": 22810.40,
                "five_session_forward_return": 0.016047,
                "factor_values": {"volume_surge_ratio": 1.25}
            }
        ]
        rows_sha = compute_canonical_rows_sha256(rows)

        doc = {
            "schema_version": 1,
            "kind": "absorb-regression-input-dataset",
            "identity": {
                "dataset_id": "TW-20260717-input-dataset-v1",
                "market": "TW",
                "analysis_scope": "market_level_daily",
                "source_market_date": "2026-07-17",
                "first_feature_session": "2025-07-10",
                "last_feature_session": "2026-07-10",
                "first_label_end_session": "2025-07-17",
                "last_label_end_session": "2026-07-17",
                "first_source_session": "2025-06-10",
                "last_source_session": "2026-07-17",
                "lookback_start_session": "2025-06-10",
                "source_object_count": 1,
                "aggregate_manifest_object": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
                "aggregate_manifest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "aggregate_manifest_schema_version": 1,
                "row_count": 1,
                "calendar_id": "TWSE_TRADING_CALENDAR",
                "calendar_version": "2026.1",
                "calendar_sha256": "c1a2b3e4f5d6a789901234567890abcdefc1a2b3e4f5d6a789901234567890ab",
                "canonical_rows_sha256": rows_sha,
                "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86",
                "content_sha256": ""
            },
            "source_objects": [],
            "factor_definitions": [],
            "preprocessing_policy": {
                "factor_value_stage": "raw",
                "missing_value_policy": "listwise_deletion",
                "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                "standardization_policy": "z_score_sample_std_ddof_1"
            },
            "rows": rows
        }
        content_sha = compute_regression_input_dataset_content_sha256(doc)
        doc["identity"]["content_sha256"] = content_sha

        with patch("reporting.regression_input_publisher.PUBLISH_ROOT", self.publish_dir):
            ptr = publish_regression_input_dataset(doc)
            self.assertIsNotNone(ptr)
            self.assertEqual(ptr["schema_version"], 1)
            self.assertEqual(ptr["row_count"], 1)
            self.assertTrue(ptr["object"].startswith("objects/regression-input/"))
            written_file = os.path.join(self.publish_dir, ptr["object"])
            self.assertTrue(os.path.exists(written_file))


if __name__ == "__main__":
    unittest.main()
