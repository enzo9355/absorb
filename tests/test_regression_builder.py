"""PIT, lineage, and exception-boundary tests for the pure regression builder."""

import unittest
from unittest import mock

from reporting.regression_builder import build_regression_research_artifact
from reporting.regression_input_schema import RegressionInputDataset
from reporting.regression_schema import RegressionResearchArtifact
from tests.regression_fixtures import COMMIT_SHA, make_input_document, trading_calendar


class TestRegressionBuilder(unittest.TestCase):
    def setUp(self):
        self.calendar = trading_calendar()
        self.input_document = make_input_document(calendar=self.calendar)
        self.dataset = RegressionInputDataset.from_document(
            self.input_document,
            trading_calendar=self.calendar,
        )
        self.object_sha = "b" * 64

    def build(self, **overrides):
        arguments = {
            "input_dataset": self.dataset,
            "input_dataset_object_path": f"objects/regression-input/{self.object_sha}.json",
            "input_dataset_object_sha256": self.object_sha,
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "generated_at": "2026-07-17T10:30:00Z",
            "code_commit_sha": COMMIT_SHA,
            "trading_calendar": self.calendar,
        }
        arguments.update(overrides)
        return build_regression_research_artifact(**arguments)

    def test_builds_schema_valid_artifact_with_injected_identity(self):
        document = self.build()
        artifact = RegressionResearchArtifact.from_document(document)
        self.assertEqual(artifact.identity.generated_at, "2026-07-17T10:30:00Z")
        self.assertEqual(artifact.identity.code_commit_sha, COMMIT_SHA)
        self.assertEqual(artifact.regression_spec.sample_count, 35)

    def test_object_path_and_sha_are_bound(self):
        with self.assertRaisesRegex(ValueError, "input dataset object"):
            self.build(input_dataset_object_sha256="a" * 64)

    def test_missing_commit_uses_repository_sha_and_fails_closed_if_invalid(self):
        with mock.patch("reporting.regression_builder.git_commit_sha", return_value="e" * 40):
            document = self.build(code_commit_sha=None)
        self.assertEqual(document["identity"]["code_commit_sha"], "e" * 40)

        with mock.patch("reporting.regression_builder.git_commit_sha", return_value="unknown"):
            with self.assertRaisesRegex(ValueError, "code_commit_sha"):
                self.build(code_commit_sha=None)

    def test_programming_and_dependency_errors_are_not_hidden(self):
        with mock.patch(
            "reporting.regression_builder.compute_ols_hac_regression",
            side_effect=RuntimeError("dependency bug"),
        ):
            with self.assertRaisesRegex(RuntimeError, "dependency bug"):
                self.build()


if __name__ == "__main__":
    unittest.main()
