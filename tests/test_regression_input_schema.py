# -*- coding: utf-8 -*-
"""Tests for RegressionInputDataset schema and canonical serializers."""

import unittest


class TestRegressionInputSchema(unittest.TestCase):

    def test_input_dataset_validates_rows_and_hashes(self):
        from reporting.regression_input_schema import (
            RegressionInputDataset,
            serialize_regression_input_dataset,
            serialize_regression_rows,
            compute_canonical_rows_sha256,
        )
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
                "canonical_rows_sha256": "82bf6ef3ebfc26f2fb7072ea63ddff6d31bb9bfbdcf9a5a40b90cfc8cfbdce1a",
                "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86",
                "content_sha256": ""
            },
            "source_objects": [
                {
                    "object": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "kind": "absorb-quant-manifest",
                    "schema_version": 1,
                    "source_market_date": "2026-07-17"
                }
            ],
            "factor_definitions": [
                {
                    "name": "volume_surge_ratio",
                    "source_object_kind": "twse_market_daily_summary",
                    "source_field": "total_shares_traded",
                    "unit": "ratio",
                    "formula": "Session t total shares traded divided by 20-session arithmetic mean volume",
                    "lookback_sessions": 20,
                    "lag_sessions": 0,
                    "missing_policy": "listwise_deletion",
                    "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                    "standardization_policy": "z_score_sample_std_ddof_1"
                }
            ],
            "preprocessing_policy": {
                "factor_value_stage": "raw",
                "missing_value_policy": "listwise_deletion",
                "winsorization_policy": "1st_99th_percentile_linear_interpolation",
                "standardization_policy": "z_score_sample_std_ddof_1"
            },
            "rows": [
                {
                    "feature_session": "2025-07-10",
                    "label_end_session": "2025-07-17",
                    "taiex_close_t": 22450.15,
                    "taiex_close_t_plus_5": 22810.40,
                    "five_session_forward_return": 0.016046663385589028,
                    "factor_values": {
                        "volume_surge_ratio": 1.25
                    }
                }
            ]
        }
        dataset = RegressionInputDataset.from_document(doc)
        self.assertEqual(dataset.schema_version, 1)
        self.assertEqual(dataset.kind, "absorb-regression-input-dataset")
        rows_sha = compute_canonical_rows_sha256(doc["rows"])
        self.assertIsInstance(rows_sha, str)
        self.assertEqual(len(rows_sha), 64)
        serialized = serialize_regression_input_dataset(doc)
        self.assertIsInstance(serialized, bytes)

    def test_non_ascending_sessions_rejected(self):
        from reporting.regression_input_schema import RegressionInputDataset
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
                "row_count": 2,
                "calendar_id": "TWSE_TRADING_CALENDAR",
                "calendar_version": "2026.1",
                "calendar_sha256": "c1a2b3e4f5d6a789901234567890abcdefc1a2b3e4f5d6a789901234567890ab",
                "canonical_rows_sha256": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
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
            "rows": [
                {
                    "feature_session": "2025-07-11",
                    "label_end_session": "2025-07-18",
                    "taiex_close_t": 100.0,
                    "taiex_close_t_plus_5": 105.0,
                    "five_session_forward_return": 0.05,
                    "factor_values": {}
                },
                {
                    "feature_session": "2025-07-10",
                    "label_end_session": "2025-07-17",
                    "taiex_close_t": 100.0,
                    "taiex_close_t_plus_5": 105.0,
                    "five_session_forward_return": 0.05,
                    "factor_values": {}
                }
            ]
        }
        with self.assertRaises(ValueError):
            RegressionInputDataset.from_document(doc)


if __name__ == "__main__":
    unittest.main()
