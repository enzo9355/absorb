# -*- coding: utf-8 -*-
"""Tests for pure RegressionResearchArtifact builder."""

import unittest


class TestRegressionBuilder(unittest.TestCase):

    def test_builds_valid_regression_research_artifact(self):
        from reporting.regression_builder import build_regression_research_artifact
        from reporting.regression_input_schema import compute_canonical_rows_sha256

        # Construct 35 synthetic valid rows to satisfy n >= 30 condition
        import numpy as np
        np.random.seed(42)
        rows = []
        for i in range(35):
            date_str = f"2025-07-{(i % 20) + 1:02d}"
            v_ratio = 1.0 + float(np.random.normal(0, 0.1))
            f_ratio = 0.02 + float(np.random.normal(0, 0.01))
            vol_20 = 0.01 + float(np.random.normal(0, 0.002))
            ret = 0.01 + 0.02 * v_ratio + 0.05 * f_ratio + float(np.random.normal(0, 0.005))
            rows.append({
                "feature_session": f"2025-07-{i+1:02d}",
                "label_end_session": f"2025-07-{i+8:02d}",
                "taiex_close_t": 22000.0 + i * 10,
                "taiex_close_t_plus_5": (22000.0 + i * 10) * (1.0 + ret),
                "five_session_forward_return": ret,
                "factor_values": {
                    "volume_surge_ratio": v_ratio,
                    "foreign_net_flow_ratio": f_ratio,
                    "volatility_20d": vol_20,
                }
            })

        rows_sha = compute_canonical_rows_sha256(rows)
        input_dataset_doc = {
            "schema_version": 1,
            "kind": "absorb-regression-input-dataset",
            "identity": {
                "dataset_id": "TW-20260717-input-dataset-v1",
                "market": "TW",
                "analysis_scope": "market_level_daily",
                "source_market_date": "2026-07-17",
                "first_feature_session": "2025-07-01",
                "last_feature_session": "2025-08-05",
                "first_label_end_session": "2025-07-08",
                "last_label_end_session": "2025-08-12",
                "first_source_session": "2025-06-10",
                "last_source_session": "2026-07-17",
                "lookback_start_session": "2025-06-10",
                "source_object_count": 1,
                "aggregate_manifest_object": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
                "aggregate_manifest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "aggregate_manifest_schema_version": 1,
                "row_count": 35,
                "calendar_id": "TWSE_TRADING_CALENDAR",
                "calendar_version": "2026.1",
                "calendar_sha256": "c1a2b3e4f5d6a789901234567890abcdefc1a2b3e4f5d6a789901234567890ab",
                "canonical_rows_sha256": rows_sha,
                "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86",
                "content_sha256": "e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6"
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

        artifact_doc = build_regression_research_artifact(
            input_dataset=input_dataset_doc,
            input_dataset_object_path="objects/regression-input/f1e2d3c4b5a697887766554433221100f1e2d3c4b5a697887766554433221100.json",
            input_dataset_object_sha256="f1e2d3c4b5a697887766554433221100f1e2d3c4b5a697887766554433221100",
            source_market_date="2026-07-17",
            applicable_trading_date="2026-07-20",
        )
        self.assertIsNotNone(artifact_doc)
        self.assertEqual(artifact_doc["schema_version"], 1)
        self.assertEqual(artifact_doc["kind"], "absorb-regression-research-artifact")
        self.assertTrue(len(artifact_doc["identity"]["content_sha256"]) == 64)


if __name__ == "__main__":
    unittest.main()
