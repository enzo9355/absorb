import unittest
from reporting.schemas import ReportMetadataV2


class ProfessionalPointerSchemaTests(unittest.TestCase):
    def _base_metadata(self):
        return {
            "schema_version": 2,
            "report_type": "post_close",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-17T10:30:00Z",
            "forecast_start_date": "2026-07-20",
            "forecast_end_date": "2026-07-24",
            "backtest_as_of": None,
            "data_as_of": "2026-07-17",
            "source_manifest": "quant/v1/manifests/TW-20260717T091000Z-123456789abc.json",
            "source_manifest_sha256": "a" * 64,
            "model_versions": {},
            "title": "ABSORB ????????",
            "summary": ["??"],
            "warnings": [],
            "content": {"observation": "test"},
            "product_mode": "observation",
            "observation_start_date": "2026-07-17",
            "observation_end_date": "2026-07-20",
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
        }

    def _valid_pointer(self):
        sha256_val = "c" * 64
        return {
            "object": "objects/canonical/" + sha256_val + ".json",
            "sha256": sha256_val,
            "content_sha256": "d" * 64,
            "schema_version": 1,
            "generator_version": "professional-report/1",
            "code_commit_sha": "b" * 40,
        }

    def test_valid_professional_report_pointer(self):
        doc = self._base_metadata()
        doc["professional_report"] = self._valid_pointer()
        schema = ReportMetadataV2.from_document(doc)
        self.assertIsNotNone(schema.professional_report)
        self.assertEqual(schema.professional_report["schema_version"], 1)

    def test_rejects_unknown_keys_in_pointer(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["extra_key"] = "forbidden"
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_missing_required_keys_in_pointer(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        del pointer["code_commit_sha"]
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_invalid_schema_version(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["schema_version"] = 2
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_invalid_sha256(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["sha256"] = "short"
        pointer["object"] = "objects/canonical/short.json"
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_object_path_mismatch(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["object"] = "objects/canonical/" + ("e" * 64) + ".json"
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_invalid_generator_version(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["generator_version"] = ""
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_rejects_invalid_code_commit_sha(self):
        doc = self._base_metadata()
        pointer = self._valid_pointer()
        pointer["code_commit_sha"] = "b" * 39
        doc["professional_report"] = pointer
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_forbidden_in_pre_market(self):
        doc = self._base_metadata()
        doc["report_type"] = "pre_market"
        doc["professional_report"] = self._valid_pointer()
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_forbidden_in_weekly_model(self):
        doc = self._base_metadata()
        doc["report_type"] = "weekly_model"
        doc["professional_report"] = self._valid_pointer()
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)

    def test_forbidden_in_non_observation_mode(self):
        doc = self._base_metadata()
        doc["product_mode"] = None
        doc["professional_report"] = self._valid_pointer()
        with self.assertRaises(ValueError):
            ReportMetadataV2.from_document(doc)


if __name__ == "__main__":
    unittest.main()
