"""Cross-object lineage tests for optional regression research binding."""

import copy
import hashlib
import unittest

from reporting.professional_binding import validate_regression_research_binding
from reporting.professional_schema import ProfessionalPostCloseReport, compute_content_sha256
from reporting.regression_schema import serialize_regression_artifact
from reporting.schemas import ReportMetadataV2
from tests.regression_fixtures import make_artifact_document, rehash_artifact_document
from tests import test_canonical_publisher_integrity as canonical_helpers


class TestRegressionBinding(unittest.TestCase):
    def setUp(self):
        helper = canonical_helpers.CanonicalPublisherIntegrityTests()
        self.report = helper._base_report_doc()
        self.artifact = make_artifact_document()
        self.artifact["identity"]["source_manifest"] = self.report["identity"]["source_manifest"]
        self.artifact["identity"]["source_manifest_sha256"] = self.report["identity"]["source_manifest_sha256"]
        rehash_artifact_document(self.artifact)
        self.object_sha = hashlib.sha256(serialize_regression_artifact(self.artifact)).hexdigest()
        self.pointer = {
            "object": f"objects/regression/{self.object_sha}.json",
            "sha256": self.object_sha,
            "content_sha256": self.artifact["identity"]["content_sha256"],
            "schema_version": 1,
            "generator_version": self.artifact["identity"]["generator_version"],
            "code_commit_sha": self.artifact["identity"]["code_commit_sha"],
        }

        self.report["quantitative_research"] = {
            "status": "available",
            "data_as_of": self.report["identity"]["source_market_date"],
            "data": {
                "regression_reference": {
                    "object_sha256": self.object_sha,
                    "content_sha256": self.artifact["identity"]["content_sha256"],
                    "summary_status": "available",
                }
            },
        }
        self.report["identity"]["content_sha256"] = compute_content_sha256(self.report)
        self.metadata = helper._base_metadata_doc(self.report)
        self.metadata["regression_research"] = copy.deepcopy(self.pointer)

    def validate(self, *, metadata=None, report=None, pointer=None, artifact=None):
        validate_regression_research_binding(
            metadata=ReportMetadataV2.from_document(metadata or self.metadata),
            professional_report=ProfessionalPostCloseReport.from_document(report or self.report),
            pointer=pointer or self.pointer,
            regression_artifact=artifact or self.artifact,
        )

    def test_valid_binding_cross_checks_all_four_documents(self):
        self.validate()

    def test_date_manifest_pointer_and_report_reference_mismatches_fail(self):
        cases = (
            ("metadata", "source_market_date", "2026-07-16"),
            ("metadata", "applicable_trading_date", "2026-07-21"),
            ("metadata", "source_manifest", "quant/v1/manifests/TW-20260717T103000Z-ffffffffffff.json"),
            ("metadata", "source_manifest_sha256", "f" * 64),
            ("pointer", "object", f"objects/regression/{'f' * 64}.json"),
            ("pointer", "sha256", "f" * 64),
            ("pointer", "content_sha256", "f" * 64),
            ("pointer", "generator_version", "2.0.0"),
            ("pointer", "code_commit_sha", "f" * 40),
            ("reference", "object_sha256", "f" * 64),
            ("reference", "content_sha256", "f" * 64),
        )
        for target, field, value in cases:
            with self.subTest(target=target, field=field):
                metadata = copy.deepcopy(self.metadata)
                report = copy.deepcopy(self.report)
                pointer = copy.deepcopy(self.pointer)
                if target == "metadata":
                    metadata[field] = value
                elif target == "pointer":
                    pointer[field] = value
                    metadata["regression_research"] = copy.deepcopy(pointer)
                else:
                    report["quantitative_research"]["data"]["regression_reference"][field] = value
                    report["identity"]["content_sha256"] = compute_content_sha256(report)
                with self.assertRaises((ValueError, TypeError)):
                    self.validate(metadata=metadata, report=report, pointer=pointer)

    def test_artifact_input_dataset_identity_tampering_fails(self):
        for field, value in (
            ("input_dataset_object", f"objects/regression-input/{'f' * 64}.json"),
            ("input_dataset_sha256", "f" * 64),
            ("input_dataset_content_sha256", "F" * 64),
            ("input_dataset_rows_sha256", "not-a-sha"),
        ):
            with self.subTest(field=field):
                artifact = copy.deepcopy(self.artifact)
                artifact["identity"][field] = value
                rehash_artifact_document(artifact)
                with self.assertRaises((ValueError, TypeError)):
                    self.validate(artifact=artifact)

    def test_artifact_date_and_manifest_mismatches_fail(self):
        for field, value in (
            ("source_market_date", "2026-07-18"),
            ("applicable_trading_date", "2026-07-21"),
            (
                "source_manifest",
                "quant/v1/manifests/TW-20260717T103000Z-ffffffffffff.json",
            ),
            ("source_manifest_sha256", "f" * 64),
        ):
            with self.subTest(field=field):
                artifact = copy.deepcopy(self.artifact)
                artifact["identity"][field] = value
                rehash_artifact_document(artifact)
                with self.assertRaises((ValueError, TypeError)):
                    self.validate(artifact=artifact)


if __name__ == "__main__":
    unittest.main()
