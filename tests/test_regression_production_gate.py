"""Production entry-point gate tests for Task C readiness=false behavior."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reporting.observation_v2 import build_post_close_observation_metadata
from stock_papi.batch.observation_products import promote_observation_candidate
from tests.test_observation_report_v2 import Calendar, dashboard


class TestRegressionProductionGate(unittest.TestCase):
    def candidate(self, *, regression_pointer=False):
        metadata = build_post_close_observation_metadata(dashboard(), Calendar())
        if regression_pointer:
            metadata["regression_research"] = {"unexpected": "production pointer"}
        return {
            "post-close-report-v2.json": metadata,
            "dashboard-snapshot.json": {},
        }

    def test_real_production_entrypoint_calls_no_regression_builders_or_publishers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_latest = root / "publish" / "dashboard" / "v1" / "latest-TW.json"
            with mock.patch(
                "stock_papi.batch.observation_products._read_observation_candidate",
                return_value=self.candidate(),
            ), mock.patch(
                "stock_papi.batch.observation_products._prepare_observation_dashboard",
                return_value=(dashboard_latest, b"dashboard"),
            ), mock.patch(
                "reporting.git_commit_sha", return_value="d" * 40
            ), mock.patch(
                "reporting.publisher.publish_report_v2",
                return_value=root / "publish" / "reports" / "v2" / "latest-TW-post_close.json",
            ) as report_publisher, mock.patch(
                "reporting.regression_input_builder.build_regression_input_dataset"
            ) as input_builder, mock.patch(
                "reporting.regression_input_publisher.publish_regression_input_dataset"
            ) as input_publisher, mock.patch(
                "reporting.regression_builder.build_regression_research_artifact"
            ) as artifact_builder, mock.patch(
                "stock_papi.batch.observation_products._write_atomic"
            ):
                promote_observation_candidate(root, root / "candidate")

        input_builder.assert_not_called()
        input_publisher.assert_not_called()
        artifact_builder.assert_not_called()
        published_metadata = report_publisher.call_args.args[1]
        published_report = report_publisher.call_args.kwargs["professional_report"]
        self.assertNotIn("regression_research", published_metadata)
        self.assertIsNone(report_publisher.call_args.kwargs.get("regression_artifact"))
        self.assertEqual(published_report.quantitative_research.status, "unavailable")
        self.assertEqual(published_report.quantitative_research.data, {})

    def test_production_candidate_cannot_inject_regression_pointer_while_gate_is_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch(
                "stock_papi.batch.observation_products._read_observation_candidate",
                return_value=self.candidate(regression_pointer=True),
            ), mock.patch(
                "stock_papi.batch.observation_products._prepare_observation_dashboard",
                return_value=(root / "dashboard.json", b"dashboard"),
            ), mock.patch("reporting.git_commit_sha", return_value="d" * 40):
                with self.assertRaisesRegex(ValueError, "regression.*not ready"):
                    promote_observation_candidate(root, root / "candidate")


if __name__ == "__main__":
    unittest.main()
