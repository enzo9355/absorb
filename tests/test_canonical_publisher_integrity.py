from tests.test_professional_report_schema import ProfessionalReportSchemaTests
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from reporting.config import ReportConfig
from reporting.exceptions import ReportPublishError
from reporting.professional_schema import (
    ProfessionalPostCloseReport,
    compute_content_sha256,
)
from reporting.publisher import publish_report_v2


class CanonicalPublisherIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _base_report_doc(self):
        return ProfessionalReportSchemaTests()._document()

    def _base_metadata_doc(self, report_doc):
        identity = report_doc["identity"]
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
        }

    def test_successful_canonical_report_publishing(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)
        professional_report = ProfessionalPostCloseReport.from_document(report_doc)

        latest_path = publish_report_v2(
            root=self.root,
            metadata=metadata_doc,
            professional_report=professional_report,
        )

        self.assertTrue(latest_path.exists())
        publish_dir = self.root / "publish" / "reports" / "v2"

        index_path = publish_dir / "index-TW.json"
        self.assertTrue(index_path.exists())
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(index_data["reports"]), 1)

        meta_rel = index_data["reports"][0]["metadata"]
        meta_path = publish_dir / meta_rel
        self.assertTrue(meta_path.exists())
        meta_content = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertIn("professional_report", meta_content)

        ptr = meta_content["professional_report"]
        canonical_obj_path = publish_dir / ptr["object"]
        self.assertTrue(canonical_obj_path.exists())

        canonical_bytes = canonical_obj_path.read_bytes()
        self.assertGreater(len(canonical_bytes), 0)
        self.assertEqual(hashlib.sha256(canonical_bytes).hexdigest(), ptr["sha256"])

        readback_canonical = json.loads(canonical_bytes.decode("utf-8"))
        self.assertEqual(readback_canonical["identity"]["content_sha256"], ptr["content_sha256"])

    def test_fails_closed_on_binding_mismatch(self):
        report_doc = self._base_report_doc()
        metadata_doc = self._base_metadata_doc(report_doc)
        metadata_doc["source_manifest"] = "quant/v1/manifests/TW-20260717T091000Z-999999999aaa.json"
        professional_report = ProfessionalPostCloseReport.from_document(report_doc)

        with self.assertRaises(ReportPublishError):
            publish_report_v2(
                root=self.root,
                metadata=metadata_doc,
                professional_report=professional_report,
            )

        publish_dir = self.root / "publish" / "reports" / "v2"
        canonical_dir = publish_dir / "objects" / "canonical"
        if canonical_dir.exists():
            self.assertEqual(len(list(canonical_dir.glob("*.json"))), 0)

    def test_fails_closed_on_corrupted_content_sha(self):
        report_doc = self._base_report_doc()
        report_doc["identity"]["content_sha256"] = "a" * 64
        metadata_doc = self._base_metadata_doc(report_doc)

        with self.assertRaises(ReportPublishError):
            publish_report_v2(
                root=self.root,
                metadata=metadata_doc,
                professional_report=report_doc,
            )

        publish_dir = self.root / "publish" / "reports" / "v2"
        canonical_dir = publish_dir / "objects" / "canonical"
        if canonical_dir.exists():
            self.assertEqual(len(list(canonical_dir.glob("*.json"))), 0)


if __name__ == "__main__":
    unittest.main()
