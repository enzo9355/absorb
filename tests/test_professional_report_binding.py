from tests.test_professional_report_schema import ProfessionalReportSchemaTests
import datetime as dt
import unittest
from reporting.professional_binding import validate_professional_report_binding
from reporting.professional_schema import (
    ProfessionalPostCloseReport,
    ProfessionalReportIdentity,
    compute_content_sha256,
)
from reporting.schemas import ReportMetadataV2


class ProfessionalReportBindingTests(unittest.TestCase):
    def _base_report_doc(self):
        return ProfessionalReportSchemaTests()._document()

    def _base_metadata_doc(self, report_doc):
        identity = report_doc["identity"]
        sha256_val = "c" * 64
        return {
            "schema_version": 2,
            "report_type": "post_close",
            "market": "TW",
            "source_market_date": identity["source_market_date"],
            "applicable_trading_date": identity["applicable_trading_date"],
            "published_at": "2026-07-17T10:30:00Z",
            "forecast_start_date": identity["applicable_trading_date"],
            "forecast_end_date": "2026-07-24",
            "backtest_as_of": None,
            "data_as_of": identity["source_market_date"],
            "source_manifest": identity["source_manifest"],
            "source_manifest_sha256": identity["source_manifest_sha256"],
            "model_versions": {},
            "title": "ABSORB ????????",
            "summary": ["??"],
            "warnings": [],
            "content": {"observation": "test"},
            "product_mode": "observation",
            "observation_start_date": identity["source_market_date"],
            "observation_end_date": identity["applicable_trading_date"],
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "professional_report": {
                "object": "objects/canonical/" + sha256_val + ".json",
                "sha256": sha256_val,
                "content_sha256": identity["content_sha256"],
                "schema_version": 1,
                "generator_version": identity["generator_version"],
                "code_commit_sha": identity["code_commit_sha"],
            },
        }

    def test_valid_binding(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)

        validate_professional_report_binding(
            route_source_date=dt.date(2026, 7, 17),
            metadata=metadata_doc,
            report=report_doc,
        )

    def test_mismatched_source_market_date(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)
        metadata_doc["source_market_date"] = "2026-07-18"

        with self.assertRaises(ValueError):
            validate_professional_report_binding(
                metadata=metadata_doc,
                report=report_doc,
            )

    def test_mismatched_route_source_date(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)

        with self.assertRaises(ValueError):
            validate_professional_report_binding(
                route_source_date="2026-07-18",
                metadata=metadata_doc,
                report=report_doc,
            )

    def test_mismatched_content_sha256(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)
        report_doc["identity"]["content_sha256"] = "f" * 64

        with self.assertRaises(ValueError):
            validate_professional_report_binding(
                metadata=metadata_doc,
                report=report_doc,
            )

    def test_mismatched_pointer_content_sha256(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)
        metadata_doc["professional_report"]["content_sha256"] = "e" * 64

        with self.assertRaises(ValueError):
            validate_professional_report_binding(
                metadata=metadata_doc,
                report=report_doc,
            )

    def test_mismatched_report_id(self):
        report_doc = self._base_report_doc()
        report_doc["identity"]["report_id"] = "TW-20260717-post-close-retail"
        report_doc["identity"]["content_sha256"] = compute_content_sha256(report_doc)
        metadata_doc = self._base_metadata_doc(report_doc)

        with self.assertRaises(ValueError):
            validate_professional_report_binding(
                metadata=metadata_doc,
                report=report_doc,
            )


if __name__ == "__main__":
    unittest.main()
