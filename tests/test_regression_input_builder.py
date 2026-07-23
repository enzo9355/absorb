"""Tests for the pure input builder and fail-closed readiness declarations."""

import datetime as dt
import unittest
from unittest import mock

from reporting.regression_input_builder import (
    PRODUCTION_REGRESSION_ARTIFACT_AVAILABLE,
    PRODUCTION_REGRESSION_INPUT_READY,
    PRODUCTION_REGRESSION_SOURCE_ADAPTER_READY,
    AGGREGATE_MANIFEST_INTERVAL_VALIDATION_READY,
    build_regression_input_dataset,
)
from reporting.regression_input_schema import RegressionInputDataset
from tests.regression_fixtures import COMMIT_SHA, SHA_A, input_rows, trading_calendar


class TestRegressionInputBuilder(unittest.TestCase):
    def setUp(self):
        self.calendar = trading_calendar()
        self.rows = input_rows(self.calendar)

    def build(self, **overrides):
        arguments = {
            "source_market_date": "2026-07-17",
            "rows": self.rows,
            "aggregate_manifest_object": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
            "aggregate_manifest_sha256": SHA_A,
            "code_commit_sha": COMMIT_SHA,
            "trading_calendar": self.calendar,
            "calendar_sha256": "c" * 64,
        }
        arguments.update(overrides)
        return build_regression_input_dataset(**arguments)

    def test_all_production_readiness_declarations_remain_false(self):
        self.assertFalse(PRODUCTION_REGRESSION_SOURCE_ADAPTER_READY)
        self.assertFalse(PRODUCTION_REGRESSION_INPUT_READY)
        self.assertFalse(PRODUCTION_REGRESSION_ARTIFACT_AVAILABLE)
        self.assertFalse(AGGREGATE_MANIFEST_INTERVAL_VALIDATION_READY)

    def test_pure_builder_constructs_calendar_valid_hashed_dataset(self):
        document = self.build()
        dataset = RegressionInputDataset.from_document(
            document,
            trading_calendar=self.calendar,
        )
        self.assertEqual(dataset.identity.code_commit_sha, COMMIT_SHA)
        first_feature = dt.date.fromisoformat(dataset.identity.first_feature_session)
        self.assertEqual(
            dataset.identity.lookback_start_session,
            self.calendar.session_offset(first_feature, -20).isoformat(),
        )
        self.assertEqual(dataset.identity.row_count, len(self.rows))
        volatility = next(
            item
            for item in dataset.factor_definitions
            if item["name"] == "volatility_20d"
        )
        self.assertEqual(volatility["lookback_sessions"], 20)
        self.assertEqual(volatility["required_price_observations"], 21)

    def test_missing_commit_uses_repository_sha_and_fails_closed(self):
        with mock.patch("reporting.regression_input_builder.git_commit_sha", return_value="e" * 40):
            document = self.build(code_commit_sha=None)
        self.assertEqual(document["identity"]["code_commit_sha"], "e" * 40)

        with mock.patch("reporting.regression_input_builder.git_commit_sha", return_value="unknown"):
            with self.assertRaisesRegex(ValueError, "code_commit_sha"):
                self.build(code_commit_sha=None)


if __name__ == "__main__":
    unittest.main()
