import math
import unittest

from reporting.professional_schema import ProfessionalPostCloseReport, compute_content_sha256


class ProfessionalReportSchemaTests(unittest.TestCase):
    def _document(self):
        document = {
            "schema_version": 1,
            "kind": "absorb-professional-post-close-report",
            "identity": {
                "schema_version": 1,
                "report_type": "post_close",
                "product_tier": "institutional",
                "product_mode": "observation_with_research",
                "market": "TW",
                "source_market_date": "2026-07-17",
                "applicable_trading_date": "2026-07-20",
                "published_at": "2026-07-17T10:30:00Z",
                "generated_at": "2026-07-17T10:20:00Z",
                "source_manifest": "quant/v1/manifests/TW-20260717T091000Z-123456789abc.json",
                "source_manifest_sha256": "a" * 64,
                "content_sha256": "",
                "report_id": "TW-20260717-post-close-institutional",
                "generator_version": "professional-report/1",
                "code_commit_sha": "b" * 40,
                "model_version": None,
                "feature_schema_version": "features/v1",
                "recommendation_policy_version": "observation-policy/v1",
            },
            "executive_summary": {
                "market_state": "提高防守",
                "one_line_conclusion": "市場廣度偏弱，但尚未出現全面失速。",
                "supporting_evidence": ["站上 MA20 比例偏低"],
                "opposing_evidence": ["成交量未明顯放大"],
                "largest_risk": "廣度持續惡化",
                "strongest_industries": ["半導體製造"],
                "weakest_industries": ["航運"],
                "next_session_watch_conditions": ["觀察 MA20 廣度是否回升"],
                "ai_reference_summary": None,
            },
            "key_events": [],
            "market": {"status": "available", "data_as_of": "2026-07-17", "data": {"return_1d_pct": -0.5}},
            "capital_flows": {"status": "unavailable", "reason": "法人資料尚未完成", "data": {}},
            "industries": {"status": "available", "data_as_of": "2026-07-17", "data": {"ranking": []}},
            "securities": {"status": "available", "data_as_of": "2026-07-17", "data": {"positive_observations": []}},
            "quantitative_research": {"status": "unavailable", "reason": "模型 Promotion 維持 BLOCKED", "data": {}},
            "validation": {"status": "available", "data_as_of": "2026-07-17", "data": {"promotion": "BLOCKED"}},
            "next_session": {"status": "available", "data_as_of": "2026-07-17", "data": {"positive": [], "neutral": [], "negative": []}},
            "governance": {"status": "available", "data_as_of": "2026-07-17", "data": {"coverage": 0.982, "failed_symbols": []}},
            "ai_reference": {"status": "unavailable", "reason": "Gemini 尚未執行", "data": {}},
        }
        document["identity"]["content_sha256"] = compute_content_sha256(document)
        return document

    def test_round_trip_preserves_none_and_zero(self):
        document = self._document()
        document["market"]["data"]["flat_count"] = 0
        document["market"]["data"]["median_return"] = None
        document["identity"]["content_sha256"] = compute_content_sha256(document)
        report = ProfessionalPostCloseReport.from_document(document)
        round_trip = report.to_document()
        self.assertEqual(round_trip["market"]["data"]["flat_count"], 0)
        self.assertIsNone(round_trip["market"]["data"]["median_return"])
        self.assertEqual(round_trip["identity"]["content_sha256"], compute_content_sha256(round_trip))

    def test_rejects_non_finite_number(self):
        document = self._document()
        document["market"]["data"]["return_1d_pct"] = math.nan
        document["identity"]["content_sha256"] = compute_content_sha256(document, validate_finite=False)
        with self.assertRaisesRegex(ValueError, "finite JSON"):
            ProfessionalPostCloseReport.from_document(document)

    def test_rejects_unsupported_schema_version(self):
        document = self._document()
        document["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema_version"):
            ProfessionalPostCloseReport.from_document(document)

    def test_rejects_content_hash_mismatch(self):
        document = self._document()
        document["identity"]["content_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            ProfessionalPostCloseReport.from_document(document)

    def test_rejects_invalid_date_semantics(self):
        document = self._document()
        document["identity"]["applicable_trading_date"] = "2026-07-16"
        document["identity"]["content_sha256"] = compute_content_sha256(document)
        with self.assertRaisesRegex(ValueError, "date semantics"):
            ProfessionalPostCloseReport.from_document(document)

    def test_critical_sections_must_be_available(self):
        document = self._document()
        document["governance"] = {"status": "unavailable", "reason": "missing", "data": {}}
        document["identity"]["content_sha256"] = compute_content_sha256(document)
        with self.assertRaisesRegex(ValueError, "governance"):
            ProfessionalPostCloseReport.from_document(document)

    def test_unavailable_optional_section_requires_reason(self):
        document = self._document()
        document["capital_flows"] = {"status": "unavailable", "reason": "", "data": {}}
        document["identity"]["content_sha256"] = compute_content_sha256(document)
        with self.assertRaisesRegex(ValueError, "reason"):
            ProfessionalPostCloseReport.from_document(document)


if __name__ == "__main__":
    unittest.main()
