# -*- coding: utf-8 -*-
"""Tests for regression input dataset builder and production readiness gates."""

import unittest


class TestRegressionInputBuilder(unittest.TestCase):

    def test_production_orchestrator_does_not_build_or_publish_when_readiness_false(self):
        from reporting.regression_input_builder import (
            is_production_regression_input_ready,
            orchestrate_production_regression_input,
            BUILDER_READINESS_SOURCE_ADAPTER,
            BUILDER_READINESS_INPUT_READY,
            BUILDER_READINESS_ARTIFACT_AVAILABLE,
            BUILDER_READINESS_AGGREGATE_INTERVAL_VALIDATION,
        )
        self.assertFalse(BUILDER_READINESS_SOURCE_ADAPTER)
        self.assertFalse(BUILDER_READINESS_INPUT_READY)
        self.assertFalse(BUILDER_READINESS_ARTIFACT_AVAILABLE)
        self.assertFalse(BUILDER_READINESS_AGGREGATE_INTERVAL_VALIDATION)
        self.assertFalse(is_production_regression_input_ready())

        res = orchestrate_production_regression_input(metadata={"source_market_date": "2026-07-17"})
        self.assertIsNone(res)

    def test_pure_builder_constructs_valid_dataset_from_fixture_rows(self):
        from reporting.regression_input_builder import build_regression_input_dataset
        rows = [
            {
                "feature_session": "2025-07-10",
                "label_end_session": "2025-07-17",
                "taiex_close_t": 22450.15,
                "taiex_close_t_plus_5": 22810.40,
                "five_session_forward_return": 0.016046663385589028,
                "factor_values": {"volume_surge_ratio": 1.25}
            }
        ]
        doc = build_regression_input_dataset(
            source_market_date="2026-07-17",
            rows=rows,
            aggregate_manifest_object="quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
            aggregate_manifest_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            code_commit_sha="da25d594d3b76865da22b891285ac0c85e710d86",
        )
        self.assertIsNotNone(doc)
        self.assertEqual(doc["identity"]["row_count"], 1)
        self.assertEqual(doc["identity"]["aggregate_manifest_object"], "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json")


if __name__ == "__main__":
    unittest.main()
