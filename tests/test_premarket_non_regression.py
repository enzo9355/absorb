# -*- coding: utf-8 -*-
"""Pre-market non-regression & HTTP boundary guard test."""

import unittest


class TestPremarketNonRegressionGuard(unittest.TestCase):

    def test_premarket_report_type_rejects_regression_artifact(self):
        from reporting.schemas import ReportMetadataV2

        metadata_doc = {
            "schema_version": 2,
            "kind": "absorb-report",
            "report_type": "pre_market",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-17T10:30:00Z",
            "forecast_start_date": "2026-07-20",
            "forecast_end_date": "2026-07-24",
            "backtest_as_of": None,
            "data_as_of": "2026-07-17",
            "source_manifest": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
            "source_manifest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "model_versions": {"tw_v2_core": 1},
            "title": "盤前日報",
            "summary": ["摘要"],
            "warnings": [],
            "content": {"observation": "test"},
            "regression_research": {
                "object": "objects/regression/a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890.json",
                "sha256": "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890",
                "content_sha256": "b1c2d3e4f5a67890b1c2d3e4f5a67890b1c2d3e4f5a67890b1c2d3e4f5a67890",
                "schema_version": 1,
                "generator_version": "1.0.0",
                "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86"
            }
        }
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(metadata_doc)


if __name__ == "__main__":
    unittest.main()
