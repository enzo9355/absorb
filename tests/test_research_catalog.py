import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stock_papi.services import research_catalog


class ResearchCatalogTests(unittest.TestCase):
    def test_free_candidates_only_expose_ingestion_metadata(self):
        document = {"schema_version": 2, "catalog_version": "test",
                    "creators": [{"id": "a", "name": "A", "handle": "alpha"}],
                    "opinions": [], "coverage": [], "outcomes": []}
        candidate = {"catalog_id": "public-opinions-fxtwitter-candidate",
                     "fetch_meta": {"username": "alpha", "fetched_at": "2026-09-17T06:00:00Z", "has_more": True},
                     "opinions": [{"creator_id": "a", "review_status": "pending_review", "text": "must not be published"}]}
        def read(name):
            return document if name == "public-opinions.json" else candidate
        with patch.object(research_catalog, "_read_json", side_effect=read):
            result = research_catalog.load_opinions()
            self.assertEqual(1, result["ingestion"]["a"]["count"])
            self.assertEqual([], result["opinions"])
            self.assertNotIn("must not be published", str(result))
            candidate["opinions"][0]["review_status"] = "confirmed"
            self.assertEqual({}, research_catalog.load_opinions()["ingestion"])

    def test_events_are_loaded_only_from_allowed_https_hosts(self):
        events = research_catalog.load_events()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(item['source'].startswith('https://') for item in events))

    def test_opinion_creator_metadata_is_preserved_for_public_profile(self):
        creators = research_catalog.load_opinions()['creators']
        legacy = next(item for item in creators if item["id"] == "gmoney-finance-corner")
        self.assertEqual(legacy['platform'], 'YouTube')
        self.assertIn('coverage_since', legacy)

    def test_invalid_opinion_source_is_excluded(self):
        document = {'schema_version': 1, 'creators': [{'id':'a','name':'A'}], 'opinions': [{'id':'o','creator_id':'a','symbol':'2330','direction':'hold','published_at':'2026-01-01','text':'觀點','source':'https://example.com'}], 'outcomes': []}
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()
        self.assertEqual(result['opinions'][0]['id'], 'o')
        self.assertFalse(result['opinions'][0]['is_confirmed'])
        self.assertIn('invalid_source_url', result['opinions'][0]['validation_errors'])

    def test_schema_v2_opinions_preserve_coverage_and_x_source_identity(self):
        document = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "handle": "michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [
                {
                    "creator_id": "michael-sikand",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T10:00:00+08:00",
                    "reviewed_through": "2026-09-17T10:00:00+08:00",
                    "catalog_version": "opinions-v2-test",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "post_permalink_status": "available",
                    "sample_start": "2026-08-18",
                    "sample_end": "2026-09-17",
                    "verified_post_count": 1,
                    "acquisition_method": "manual_permalink_check",
                    "rights_note": "Public permalink only.",
                    "last_success_at": "2026-09-17T10:05:00+08:00",
                    "gaps": [],
                    "status": "partial",
                    "reviewer": "codex",
                }
            ],
            "opinions": [
                {
                    "id": "ms-1",
                    "opinion_id": "ms-1",
                    "origin_group_id": "ms-1",
                    "creator_id": "michael-sikand",
                    "source_url": "https://twitter.com/michaelsikand/status/98765?s=20",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "market": "US",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "AI infrastructure thesis",
                }
            ],
            "outcomes": [],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["catalog_version"], "opinions-v2-test")
        self.assertEqual(result["coverage"][0]["creator_id"], "michael-sikand")
        self.assertEqual(result["coverage"][0]["reviewed_through"], "2026-09-17T10:00:00+08:00")
        self.assertEqual(result["opinions"][0]["source_id"], "x:98765")
        self.assertEqual(result["opinions"][0]["original_source_url"], "https://twitter.com/michaelsikand/status/98765?s=20")
        self.assertTrue(result["opinions"][0]["is_confirmed"])

    def test_schema_v2_malformed_rows_are_preserved_with_errors(self):
        document = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "handle": "michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "good",
                    "opinion_id": "good",
                    "origin_group_id": "good",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/1",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "market": "US",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "good",
                },
                {
                    "id": "bad",
                    "creator_id": "michael-sikand",
                    "source_url": "https://capafy.ai/agent/alpha",
                    "source_kind": "article",
                    "market": "",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "bad",
                },
            ],
            "outcomes": [],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual([item["id"] for item in result["opinions"]], ["good", "bad"])
        self.assertTrue(result["opinions"][0]["is_confirmed"])
        self.assertFalse(result["opinions"][1]["is_confirmed"])
        self.assertIn("invalid_source_url", result["opinions"][1]["validation_errors"])
        self.assertIn("unknown_market", result["opinions"][1]["validation_errors"])

    def test_schema_v2_malformed_coverage_opinion_and_outcome_keep_catalog(self):
        document = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "handle": "michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [
                "bad-coverage-row",
                {
                    "creator_id": "michael-sikand",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T10:00:00+08:00",
                    "reviewed_through": "2026-09-17T10:00:00+08:00",
                    "catalog_version": "opinions-v2-test",
                    "sample_start": "2026-09-01",
                    "sample_end": "2026-09-17",
                    "gaps": [],
                    "status": "partial",
                    "reviewer": "codex",
                },
            ],
            "opinions": [
                {
                    "id": "good",
                    "opinion_id": "good",
                    "origin_group_id": "good",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/100",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "market": "US",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "good",
                },
                "bad-opinion-row",
            ],
            "outcomes": [
                {"opinion_id": "good", "return_5d": 0.1},
                {"opinion_id": "bad", "return_5d": "bad"},
            ],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual(result["coverage"][0]["validation_errors"], ["not_mapping"])
        self.assertTrue(result["coverage"][1]["is_current"])
        self.assertTrue(result["opinions"][0]["is_confirmed"])
        self.assertEqual(result["opinions"][1]["validation_errors"], ["not_mapping"])
        self.assertEqual(result["outcomes"], [{"opinion_id": "good", "return_5d": 0.1}])
        self.assertEqual(result["outcome_errors"][0]["opinion_id"], "bad")

    def test_schema_v2_non_list_coverage_is_preserved_without_losing_opinions(self):
        document = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "handle": "michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": {},
            "opinions": [
                {
                    "id": "good",
                    "opinion_id": "good",
                    "origin_group_id": "good",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/101",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "market": "US",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "good",
                }
            ],
            "outcomes": [],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual(result["coverage"][0]["raw_coverage"], {})
        self.assertEqual(result["coverage"][0]["validation_errors"], ["coverage_not_list"])
        self.assertFalse(result["coverage"][0]["is_current"])
        self.assertTrue(result["opinions"][0]["is_confirmed"])

    def test_schema_v2_malformed_and_duplicate_creators_keep_valid_catalog_rows(self):
        document = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "handle": "michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                },
                "bad-creator-row",
                {"id": "michael-sikand", "name": "Duplicate Michael"},
                {"id": "missing-name"},
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "good",
                    "opinion_id": "good",
                    "origin_group_id": "good",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/102",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "market": "US",
                    "symbol": "NVDA",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "good",
                }
            ],
            "outcomes": [],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual(result["creators"][1]["validation_errors"], ["not_mapping"])
        self.assertIn("duplicate_creator", result["creators"][2]["validation_errors"])
        self.assertIn("missing_name", result["creators"][3]["validation_errors"])
        self.assertTrue(result["opinions"][0]["is_confirmed"])

    def test_schema_v1_opinions_are_legacy_pending_not_confirmed(self):
        document = {
            "schema_version": 1,
            "creators": [{"id": "legacy", "name": "Legacy", "platform": "YouTube"}],
            "opinions": [
                {
                    "id": "legacy-1",
                    "creator_id": "legacy",
                    "symbol": "2330",
                    "direction": "hold",
                    "published_at": "2026-01-01T00:00:00+08:00",
                    "text": "legacy opinion",
                    "source": "https://www.youtube.com/watch?v=abc",
                },
                {
                    "id": "legacy-2",
                    "creator_id": "legacy",
                    "direction": "hold",
                    "published_at": "2026-01-01T00:00:00",
                    "text": "legacy opinion without timezone",
                    "source": "https://www.youtube.com/watch?v=def",
                },
                "bad-legacy-row",
            ],
            "outcomes": [],
        }
        with patch.object(research_catalog, '_read_json', return_value=document):
            result = research_catalog.load_opinions()

        self.assertEqual(result["opinions"][0]["id"], "legacy-1")
        self.assertEqual(result["opinions"][0]["review_status"], "legacy_unverified")
        self.assertEqual(result["opinions"][0]["source_status"], "pending_review")
        self.assertFalse(result["opinions"][0]["is_confirmed"])
        self.assertNotIn("market", result["opinions"][0])
        self.assertNotIn("security_status", result["opinions"][0])
        self.assertNotIn("first_seen_at", result["opinions"][0])
        self.assertNotIn("content_type", result["opinions"][0])
        self.assertNotIn("stance", result["opinions"][0])
        self.assertNotIn("recommendation_kind", result["opinions"][0])
        self.assertIn("legacy_missing_opinion_id", result["opinions"][0]["validation_errors"])
        self.assertIn("legacy_missing_source_id", result["opinions"][0]["validation_errors"])
        self.assertIn("legacy_missing_market", result["opinions"][0]["validation_errors"])
        self.assertIn("legacy_missing_first_seen_at", result["opinions"][0]["validation_errors"])
        self.assertNotIn("legacy_published_at_timezone", result["opinions"][0]["validation_errors"])
        self.assertIn("legacy_missing_symbol", result["opinions"][1]["validation_errors"])
        self.assertIn("legacy_published_at_timezone", result["opinions"][1]["validation_errors"])
        self.assertEqual(result["opinions"][2]["raw"], "bad-legacy-row")
        self.assertEqual(result["opinions"][2]["validation_errors"], ["not_mapping"])
        self.assertFalse(result["opinions"][2]["is_confirmed"])

    def test_malformed_catalog_fails_closed(self):
        with patch.object(research_catalog, '_read_json', return_value={'schema_version': 1, 'creators': 'bad', 'opinions': []}):
            self.assertEqual(research_catalog.load_opinions(), {'creators': [], 'opinions': [], 'outcomes': []})


if __name__ == '__main__':
    unittest.main()
