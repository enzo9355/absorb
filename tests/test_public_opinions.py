import hashlib
import unittest
from datetime import date, datetime, timedelta, timezone

from stock_papi.services import public_opinions
from stock_papi.services.public_opinions import query_activities, validate_activity


class PublicOpinionsTests(unittest.TestCase):
    def _v2_catalog(self, opinions):
        return {
            "schema_version": 2,
            "catalog_version": "test-v2",
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
            "opinions": opinions,
            "outcomes": [],
        }

    def _v2_opinion(self, opinion_id, post_id, **overrides):
        row = {
            "id": opinion_id,
            "opinion_id": opinion_id,
            "creator_id": "michael-sikand",
            "origin_group_id": opinion_id,
            "source_url": f"https://x.com/michaelsikand/status/{post_id}",
            "source_kind": "x_post",
            "source_platform": "x",
            "acquisition_method": "manual_permalink_check",
            "market": "US",
            "symbol": "NVDA",
            "published_at": "2026-01-01T14:30:00-05:00",
            "first_seen_at": "2026-01-01T15:00:00-05:00",
            "reviewed_at": "2026-01-01T16:00:00-05:00",
            "review_status": "confirmed",
            "source_status": "available",
            "content_type": "original_opinion",
            "stance": "bullish",
            "recommendation_kind": "explicit",
            "direction": "buy",
            "horizon": "short",
            "conditions": [],
            "text": "I am bullish NVDA.",
        }
        row.update(overrides)
        return row

    def test_parse_helpers_classify_negative_conditional_quotes_and_activity_types(self):
        cases = [
            (
                {"text": "不建議買 NVDA", "content_type": "original_opinion"},
                {
                    "content_type": "original_opinion",
                    "stance": "bearish",
                    "recommendation_kind": "mention",
                    "horizon": "unspecified",
                    "conditions": [],
                    "negative": True,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "若 NVDA 突破 150 才買", "content_type": "original_opinion"},
                {
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "conditional",
                    "horizon": "unspecified",
                    "conditions": ["若 NVDA 突破 150 才買"],
                    "negative": False,
                    "quoted": False,
                    "classification": "conditional",
                },
            ),
            (
                {"text": "Reuters: another fund says buy NVDA"},
                {
                    "content_type": "news_relay",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "horizon": "unspecified",
                    "conditions": [],
                    "negative": False,
                    "quoted": True,
                    "classification": "mention",
                },
            ),
            (
                {"text": "NVDA options flow: large call sweep"},
                {
                    "content_type": "flow_observation",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "horizon": "unspecified",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "Pelosi disclosed a NVDA trade"},
                {
                    "content_type": "trade_disclosure",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "horizon": "unspecified",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "Long-term NVDA thesis remains bullish"},
                {
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "mention",
                    "horizon": "long",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "Bullish NVDA short term"},
                {
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "mention",
                    "horizon": "short",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "Short-term NVDA thesis remains bullish"},
                {
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "mention",
                    "horizon": "short",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
            (
                {"text": "I have a short position in NVDA"},
                {
                    "content_type": "original_opinion",
                    "stance": "bearish",
                    "recommendation_kind": "mention",
                    "horizon": "unspecified",
                    "conditions": [],
                    "negative": False,
                    "quoted": False,
                    "classification": "mention",
                },
            ),
        ]

        for opinion, expected in cases:
            with self.subTest(opinion=opinion["text"]):
                parsed = public_opinions.parse_opinion_markers(opinion)
                self.assertEqual(parsed, expected)

    def test_v2_timeline_preserves_reversals_withdrawals_and_latest_by_horizon(self):
        catalog = self._v2_catalog([
            self._v2_opinion("bull-short", 200, text="I am bullish NVDA short term."),
            self._v2_opinion(
                "bear-short",
                201,
                published_at="2026-01-10T14:30:00-05:00",
                first_seen_at="2026-01-10T15:00:00-05:00",
                reviewed_at="2026-01-10T16:00:00-05:00",
                stance="bearish",
                direction="sell",
                supersedes_id="bull-short",
                text="I changed my view and am bearish NVDA short term.",
            ),
            self._v2_opinion(
                "bull-long",
                202,
                published_at="2026-01-11T14:30:00-05:00",
                first_seen_at="2026-01-11T15:00:00-05:00",
                reviewed_at="2026-01-11T16:00:00-05:00",
                horizon="long",
                text="Long-term NVDA thesis remains bullish.",
            ),
            self._v2_opinion(
                "withdraw-long",
                203,
                published_at="2026-01-12T14:30:00-05:00",
                first_seen_at="2026-01-12T15:00:00-05:00",
                reviewed_at="2026-01-12T16:00:00-05:00",
                stance="unclear",
                recommendation_kind="mention",
                direction="hold",
                horizon="long",
                withdraws_id="bull-long",
                text="Withdrawing my long-term NVDA view.",
            ),
        ])

        result = public_opinions.build_catalog(catalog)
        latest = public_opinions.latest_valid_stances(result)
        latest_by_key = {
            (item["creator_id"], item["market"], item["symbol"], item["horizon"]): item
            for item in latest
        }

        self.assertEqual(
            [item["opinion_id"] for item in result["opinions"]],
            ["bull-short", "bear-short", "bull-long", "withdraw-long"],
        )
        self.assertEqual(
            latest_by_key[("michael-sikand", "US", "NVDA", "short")]["opinion_id"],
            "bear-short",
        )
        self.assertEqual(
            latest_by_key[("michael-sikand", "US", "NVDA", "short")]["stance"],
            "bearish",
        )
        self.assertNotIn(("michael-sikand", "US", "NVDA", "long"), latest_by_key)
        self.assertFalse(result["opinions"][0]["is_current_effective"])
        self.assertTrue(result["opinions"][1]["is_current_effective"])
        self.assertFalse(result["opinions"][2]["is_current_effective"])
        self.assertFalse(result["opinions"][3]["is_current_effective"])

    def test_v2_outcomes_keep_history_but_dedupe_continuations_inside_60_days(self):
        start = date(2026, 1, 1)
        candles = [
            {"date": (start + timedelta(days=offset)).isoformat(), "close": 100 + offset}
            for offset in range(150)
        ]
        catalog = self._v2_catalog([
            self._v2_opinion("initial", 300),
            self._v2_opinion(
                "continuation",
                301,
                published_at="2026-01-11T14:30:00-05:00",
                first_seen_at="2026-01-11T15:00:00-05:00",
                reviewed_at="2026-01-11T16:00:00-05:00",
                continuation_of="initial",
                text="Adding more evidence to the same short-term NVDA thesis.",
            ),
            self._v2_opinion(
                "new-after-60d",
                302,
                published_at="2026-03-12T14:30:00-05:00",
                first_seen_at="2026-03-12T15:00:00-05:00",
                reviewed_at="2026-03-12T16:00:00-05:00",
                text="A new short-term NVDA thesis after the prior 60-day window.",
            ),
        ])

        result = public_opinions.build_catalog(catalog, {"NVDA": candles})

        self.assertEqual(
            [item["opinion_id"] for item in result["opinions"]],
            ["initial", "continuation", "new-after-60d"],
        )
        self.assertEqual(
            [item["opinion_id"] for item in result["outcomes"]],
            ["initial", "new-after-60d"],
        )
        self.assertEqual(result["opinions"][1]["outcome"], {})

    def test_v2_outcome_dedupe_keeps_different_horizons_but_same_chain_suppresses_direction_change(self):
        start = date(2026, 1, 1)
        candles = [
            {"date": (start + timedelta(days=offset)).isoformat(), "close": 100 + offset}
            for offset in range(150)
        ]
        catalog = self._v2_catalog([
            self._v2_opinion(
                "short-thesis",
                310,
                origin_group_id="same-security",
                horizon="short",
                text="Bullish NVDA short term.",
            ),
            self._v2_opinion(
                "long-thesis",
                311,
                origin_group_id="different-horizon",
                horizon="long",
                published_at="2026-01-11T14:30:00-05:00",
                first_seen_at="2026-01-11T15:00:00-05:00",
                reviewed_at="2026-01-11T16:00:00-05:00",
                text="Long-term NVDA thesis remains bullish.",
            ),
            self._v2_opinion(
                "chain-direction-change",
                312,
                origin_group_id="same-security",
                horizon="short",
                published_at="2026-01-12T14:30:00-05:00",
                first_seen_at="2026-01-12T15:00:00-05:00",
                reviewed_at="2026-01-12T16:00:00-05:00",
                continuation_of="short-thesis",
                stance="bearish",
                direction="sell",
                text="Continuation of the same thesis, now sell the short-term position.",
            ),
        ])

        result = public_opinions.build_catalog(catalog, {"NVDA": candles})

        self.assertEqual(
            [item["opinion_id"] for item in result["outcomes"]],
            ["short-thesis", "long-thesis"],
        )
        self.assertEqual(result["opinions"][2]["outcome"], {})

    def test_v2_catalog_confirms_only_reviewed_available_x_posts(self):
        catalog = {
            "schema_version": 2,
            "catalog_version": "test-v2",
            "creators": [
                {
                    "id": "unusual-whales",
                    "name": "Unusual Whales",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/unusual_whales",
                    "handle": "unusual_whales",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [
                {
                    "creator_id": "unusual-whales",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T10:00:00+08:00",
                    "reviewed_through": "2026-09-17T10:00:00+08:00",
                    "catalog_version": "test-v2",
                    "canonical_profile_url": "https://x.com/unusual_whales",
                    "post_permalink_status": "available",
                    "sample_start": "2026-08-18",
                    "sample_end": "2026-09-17",
                    "verified_post_count": 1,
                    "acquisition_method": "manual_permalink_check",
                    "rights_note": "Public permalink only; no full-text republication.",
                    "last_success_at": "2026-09-17T10:05:00+08:00",
                    "gaps": [],
                    "status": "partial",
                    "reviewer": "codex",
                }
            ],
            "opinions": [
                {
                    "id": "uw-1",
                    "opinion_id": "uw-1",
                    "creator_id": "unusual-whales",
                    "origin_group_id": "flow-12345",
                    "continuation_of": "uw-0",
                    "withdraws_id": "",
                    "source_url": "https://twitter.com/unusual_whales/status/12345?ref=feed",
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
                    "content_type": "flow_observation",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "direction": "hold",
                    "text": "options flow observation",
                }
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["catalog_version"], "test-v2")
        self.assertEqual(result["coverage"][0]["catalog_version"], "test-v2")
        self.assertEqual(result["coverage"][0]["reviewed_through"], "2026-09-17T10:00:00+08:00")
        self.assertEqual(result["coverage"][0]["creator_id"], "unusual-whales")
        self.assertEqual(result["opinions"][0]["opinion_id"], "uw-1")
        self.assertEqual(result["opinions"][0]["original_source_url"], "https://twitter.com/unusual_whales/status/12345?ref=feed")
        self.assertEqual(result["opinions"][0]["source_id"], "x:12345")
        self.assertEqual(
            result["opinions"][0]["source_url"],
            "https://x.com/unusual_whales/status/12345",
        )
        self.assertEqual(result["opinions"][0]["origin_group_id"], "flow-12345")
        self.assertEqual(result["opinions"][0]["continuation_of"], "uw-0")
        self.assertTrue(result["opinions"][0]["is_confirmed"])

    def test_v2_catalog_marks_invalid_or_unreviewed_records_pending(self):
        base = {
            "schema_version": 2,
            "creators": [
                {
                    "id": "serenity",
                    "name": "Serenity",
                    "platform": "X",
                    "canonical_profile_url": "https://x.com/aleabitoreddit",
                    "handle": "aleabitoreddit",
                    "identity_status": "pending_review",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "bad-market",
                    "creator_id": "serenity",
                    "source_url": "https://x.com/aleabitoreddit/status/111",
                    "source_kind": "x_post",
                    "market": "KR",
                    "symbol": "005930",
                    "security_status": "unknown",
                    "published_at": "2026-09-16T14:30:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "",
                    "review_status": "pending_review",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "buy",
                },
                {
                    "id": "duplicate-post",
                    "creator_id": "serenity",
                    "source_url": "https://x.com/aleabitoreddit/status/111",
                    "source_kind": "x_post",
                    "market": "US",
                    "symbol": "NVDA",
                    "security_status": "verified",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "bullish",
                    "recommendation_kind": "explicit",
                    "direction": "buy",
                    "text": "buy",
                },
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(base)

        self.assertFalse(result["opinions"][0]["is_confirmed"])
        self.assertNotIn("unknown_market", result["opinions"][0]["validation_errors"])
        self.assertIn("unknown_security", result["opinions"][0]["validation_errors"])
        self.assertIn("published_at_timezone", result["opinions"][0]["validation_errors"])
        self.assertFalse(result["opinions"][1]["is_confirmed"])
        self.assertIn("duplicate_source_id", result["opinions"][1]["validation_errors"])

    def test_v2_requires_explicit_opinion_id_and_source_metadata(self):
        catalog = {
            "schema_version": 2,
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "handle": "michaelsikand",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "stable-row-id",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/123",
                    "source_kind": "x_post",
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
                    "text": "missing id and metadata",
                }
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertEqual(result["opinions"][0]["id"], "stable-row-id")
        self.assertEqual(result["opinions"][0]["opinion_id"], "")
        self.assertFalse(result["opinions"][0]["is_confirmed"])
        self.assertIn("missing_opinion_id", result["opinions"][0]["validation_errors"])
        self.assertIn("missing_source_platform", result["opinions"][0]["validation_errors"])
        self.assertIn("missing_acquisition_method", result["opinions"][0]["validation_errors"])

    def test_v2_coverage_preserves_malformed_rows(self):
        catalog = {
            "schema_version": 2,
            "catalog_version": "opinions-v2-test",
            "creators": [{"id": "known", "name": "Known"}],
            "coverage": [
                "not-a-mapping",
                {
                    "creator_id": "missing",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T10:00:00+08:00",
                    "reviewed_through": "2026-09-17T10:00:00+08:00",
                    "catalog_version": "wrong-version",
                    "sample_start": "bad-date",
                    "sample_end": "2026-09-17",
                    "last_success_at": "no-timezone",
                    "gaps": "none",
                    "status": "bad-status",
                    "reviewer": "",
                },
            ],
            "opinions": [],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertEqual(len(result["coverage"]), 2)
        self.assertFalse(result["coverage"][0]["is_current"])
        self.assertIn("not_mapping", result["coverage"][0]["validation_errors"])
        errors = result["coverage"][1]["validation_errors"]
        self.assertIn("unknown_creator", errors)
        self.assertIn("catalog_version_mismatch", errors)
        self.assertIn("sample_start_date", errors)
        self.assertIn("last_success_at_timezone", errors)
        self.assertIn("gaps_list", errors)
        self.assertIn("invalid_status", errors)
        self.assertIn("missing_reviewer", errors)

    def test_company_only_opinions_are_pending_without_company_master(self):
        catalog = {
            "schema_version": 2,
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "handle": "michaelsikand",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "company-only",
                    "opinion_id": "company-only",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand/status/456",
                    "source_kind": "x_post",
                    "source_platform": "x",
                    "acquisition_method": "manual_permalink_check",
                    "company_id": "sikand-media",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "direction": "hold",
                    "text": "company-level mention",
                }
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertFalse(result["opinions"][0]["is_confirmed"])
        self.assertIn("unknown_company", result["opinions"][0]["validation_errors"])

    def test_malformed_outcomes_do_not_clear_v2_catalog(self):
        catalog = {
            "schema_version": 2,
            "creators": [{"id": "creator", "name": "Creator"}],
            "coverage": [],
            "opinions": [],
            "outcomes": [
                {"opinion_id": "ok", "return_5d": 0.1},
                {"opinion_id": "bad", "return_5d": "unknown"},
                {"return_5d": 0.2},
            ],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertEqual(result["outcomes"], [])
        self.assertEqual(len(result["outcome_errors"]), 3)
        self.assertTrue(any(
            "outcome_orphan" in item["validation_errors"]
            for item in result["outcome_errors"]
        ))

    def test_v2_supplied_outcomes_only_attach_to_selected_eligible_samples(self):
        start = date(2026, 1, 1)
        candles = [
            {"date": (start + timedelta(days=offset)).isoformat(), "close": 100 + offset}
            for offset in range(150)
        ]
        catalog = self._v2_catalog([
            self._v2_opinion(
                "continuation",
                320,
                origin_group_id="chain",
                continuation_of="early",
                published_at="2026-01-11T14:30:00-05:00",
                first_seen_at="2026-01-11T15:00:00-05:00",
                reviewed_at="2026-01-11T16:00:00-05:00",
            ),
            self._v2_opinion(
                "early",
                321,
                id="row-id-different-from-opinion-id",
                origin_group_id="chain",
                published_at="2026-01-01T14:30:00-05:00",
                first_seen_at="2026-01-01T15:00:00-05:00",
                reviewed_at="2026-01-01T16:00:00-05:00",
            ),
            self._v2_opinion(
                "pending",
                322,
                origin_group_id="pending",
                review_status="pending_review",
            ),
            self._v2_opinion(
                "generated",
                323,
                id="generated-row-id",
                origin_group_id="generated",
                published_at="2026-03-12T14:30:00-05:00",
                first_seen_at="2026-03-12T15:00:00-05:00",
                reviewed_at="2026-03-12T16:00:00-05:00",
            ),
        ])
        catalog["outcomes"] = [
            {"opinion_id": "continuation", "return_5d": 0.11},
            {"opinion_id": "early", "return_5d": 0.05},
            {"opinion_id": "early", "return_5d": 0.06},
            {"opinion_id": "pending", "return_5d": 0.07},
            {"opinion_id": "orphan", "return_5d": 0.08},
        ]

        result = public_opinions.build_catalog(catalog, {"NVDA": candles})

        self.assertEqual(
            result["outcomes"],
            [
                {"opinion_id": "early", "return_5d": 0.05},
                {
                    "opinion_id": "generated",
                    "return_5d": 0.029412,
                    "return_20d": 0.117647,
                    "return_60d": 0.352941,
                    "max_drawdown": 0.0,
                },
            ],
        )
        self.assertEqual(result["opinions"][0]["outcome"], {})
        self.assertEqual(result["opinions"][1]["outcome"], {"return_5d": 0.05})
        self.assertEqual(result["opinions"][3]["outcome"]["return_60d"], 0.352941)
        errors_by_id = {}
        for error in result["outcome_errors"]:
            errors_by_id.setdefault(error["opinion_id"], []).extend(error["validation_errors"])
        self.assertIn("outcome_not_eligible", errors_by_id["continuation"])
        self.assertIn("duplicate_outcome", errors_by_id["early"])
        self.assertIn("outcome_not_eligible", errors_by_id["pending"])
        self.assertIn("outcome_orphan", errors_by_id["orphan"])

    def test_v2_rejects_profile_only_capafy_and_mismatched_x_handles(self):
        catalog = {
            "schema_version": 2,
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "handle": "michaelsikand",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "profile-only",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/michaelsikand",
                    "source_kind": "x_post",
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
                    "text": "profile only",
                },
                {
                    "id": "capafy",
                    "creator_id": "michael-sikand",
                    "source_url": "https://capafy.ai/agent/alpha-consensus-x-s-best-traders/2987621471?languageCode=en",
                    "source_kind": "article",
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
                    "text": "capafy summary",
                },
                {
                    "id": "wrong-handle",
                    "creator_id": "michael-sikand",
                    "source_url": "https://x.com/notmichaelsikand/status/555",
                    "source_kind": "x_post",
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
                    "text": "wrong handle",
                },
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        errors = {item["id"]: item["validation_errors"] for item in result["opinions"]}
        self.assertIn("invalid_source_url", errors["profile-only"])
        self.assertIn("invalid_source_url", errors["capafy"])
        self.assertIn("source_handle_mismatch", errors["wrong-handle"])

    def test_non_x_sources_use_allowlisted_hosts_and_strip_tracking(self):
        catalog = {
            "schema_version": 2,
            "creators": [
                {
                    "id": "michael-sikand",
                    "name": "Michael Sikand",
                    "platform": "X",
                    "handle": "michaelsikand",
                    "canonical_profile_url": "https://x.com/michaelsikand",
                    "identity_status": "verified",
                    "source_status": "partial",
                }
            ],
            "coverage": [],
            "opinions": [
                {
                    "id": "official",
                    "creator_id": "michael-sikand",
                    "source_url": "https://sikandmedia.com/?utm_source=x#top",
                    "source_kind": "official_site",
                    "company_id": "sikand-media",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "direction": "hold",
                    "text": "official profile",
                },
                {
                    "id": "bad-official",
                    "creator_id": "michael-sikand",
                    "source_url": "https://example.com/post",
                    "source_kind": "official_site",
                    "company_id": "sikand-media",
                    "published_at": "2026-09-16T14:30:00-04:00",
                    "first_seen_at": "2026-09-17T02:30:00+08:00",
                    "reviewed_at": "2026-09-17T10:00:00+08:00",
                    "review_status": "confirmed",
                    "source_status": "available",
                    "content_type": "original_opinion",
                    "stance": "unclear",
                    "recommendation_kind": "mention",
                    "direction": "hold",
                    "text": "bad host",
                },
            ],
            "outcomes": [],
        }

        result = public_opinions.build_catalog(catalog)

        self.assertEqual(result["opinions"][0]["source_url"], "https://sikandmedia.com/")
        self.assertEqual(result["opinions"][0]["original_source_url"], "https://sikandmedia.com/?utm_source=x#top")
        self.assertFalse(result["opinions"][0]["is_confirmed"])
        self.assertIn("unknown_company", result["opinions"][0]["validation_errors"])
        self.assertIn("invalid_source_url", result["opinions"][1]["validation_errors"])

    def test_build_catalog_validates_classifies_dedupes_and_scores_outcomes(self):
        start = date(2026, 1, 2)
        prices = [100] + [100 + min(day * 2, 30) for day in range(1, 61)]
        catalog = {
            "creators": [
                {"id": "alice", "name": "Alice"},
                {"id": "bob", "name": "Bob"},
            ],
            "opinions": [
                {
                    "id": "o1",
                    "creator_id": "alice",
                    "symbol": "2330",
                    "direction": "buy",
                    "published_at": "2026-01-02",
                    "text": "明確建議買進 2330",
                },
                {
                    "id": "o1-dup",
                    "creator_id": "alice",
                    "symbol": "2330",
                    "direction": "buy",
                    "published_at": "2026-01-03",
                    "text": "重複看多 2330",
                },
                {
                    "id": "o2",
                    "creator_id": "bob",
                    "symbol": "2317",
                    "direction": "sell",
                    "published_at": "2026-01-02",
                    "text": "若跌破季線才考慮賣出",
                },
            ],
        }
        candles = {
            "2330": [
                {"date": (start + timedelta(days=offset)).isoformat(), "close": price}
                for offset, price in enumerate(prices)
            ],
            "2317": [
                {"date": "2026-01-02", "close": 50},
                {"date": "2026-01-03", "close": 49},
            ],
        }

        result = public_opinions.build_catalog(catalog, candles)

        self.assertEqual([item["id"] for item in result["opinions"]], ["o1", "o2"])
        self.assertEqual(
            result["outcomes"],
            [
                {
                    "opinion_id": "o1",
                    "return_5d": 0.1,
                    "return_20d": 0.3,
                    "return_60d": 0.3,
                    "max_drawdown": 0.0,
                }
            ],
        )
        self.assertEqual(
            result["opinions"][0]["classification"],
            "explicit_recommendation",
        )
        self.assertEqual(result["opinions"][1]["classification"], "conditional")
        self.assertEqual(
            result["opinions"][0]["outcome"],
            {
                "return_5d": 0.1,
                "return_20d": 0.3,
                "return_60d": 0.3,
                "max_drawdown": 0.0,
            },
        )
        self.assertEqual(result["opinions"][1]["outcome"], {})

    def test_build_catalog_rejects_unknown_creator_and_invalid_outcome(self):
        with self.assertRaises(ValueError):
            public_opinions.build_catalog(
                {
                    "creators": [{"id": "alice", "name": "Alice"}],
                    "outcomes": [{"opinion_id": "bad", "return_5d": "unknown"}],
                    "opinions": [
                        {
                            "id": "bad",
                            "creator_id": "missing",
                            "symbol": "2330",
                            "direction": "buy",
                            "published_at": "2026-01-02",
                            "text": "買進",
                        }
                    ],
                },
                {},
            )

    def test_only_explicit_recommendations_receive_outcomes(self):
        start = date(2026, 1, 2)
        candles = [
            {"date": (start + timedelta(days=offset)).isoformat(), "close": 100 + offset}
            for offset in range(61)
        ]
        result = public_opinions.build_catalog(
            {
                "creators": [{"id": "alice", "name": "Alice"}],
                "opinions": [
                    {
                        "id": "conditional",
                        "creator_id": "alice",
                        "symbol": "2330",
                        "direction": "buy",
                        "published_at": "2026-01-02",
                        "text": "若突破季線才考慮買進",
                    }
                ],
            },
            {"2330": candles},
        )
        self.assertEqual(result["opinions"][0]["classification"], "conditional")
        self.assertEqual(result["opinions"][0]["outcome"], {})
        self.assertEqual(result["outcomes"], [])

        with self.assertRaises(ValueError):
            public_opinions.build_catalog(
                {
                    "creators": [{"id": "alice", "name": "Alice"}],
                    "opinions": [
                        {
                            "id": "bad",
                            "creator_id": "alice",
                            "symbol": "2330",
                            "direction": "buy",
                            "published_at": "2026-01-02",
                            "text": "買進",
                            "outcome": {"return_5d": "unknown"},
                        }
                    ],
                },
                {},
            )


class PublicActivityContractTests(unittest.TestCase):
    def _subject(self, **overrides):
        row = {
            "subject_id": "test-household",
            "subject_kind": "household",
            "subject_name": "Test Household",
            "aliases": ["Test Family"],
            "identity_source_url": "https://ethics.house.gov/test-identity",
            "identity_status": "verified",
        }
        row.update(overrides)
        return row

    def _subjects_map(self, subjects=None):
        if subjects is None:
            subjects = [self._subject()]
        validated = {}
        for row in subjects:
            sid = str(row.get("subject_id") or "").strip()
            errors = []
            if not sid:
                errors.append("missing_subject_id")
            if row.get("subject_kind") not in {"person", "household", "institution"}:
                errors.append("invalid_subject_kind")
            if not str(row.get("subject_name") or "").strip():
                errors.append("missing_subject_name")
            if row.get("identity_status") != "verified":
                errors.append("subject_identity_unverified")
            validated[sid] = dict(row, validation_errors=errors, is_verified=not errors)
        return validated

    def activity(self, **overrides):
        import hashlib as _hl
        evidence_hash = _hl.sha256(b"test-evidence").hexdigest()
        row = {
            "activity_id": "test-act-001",
            "activity_type": "trade_disclosure",
            "publisher_creator_id": "",
            "subject_id": "test-household",
            "owner": "spouse",
            "owner_name": "Spouse A",
            "market": "US",
            "symbol": "INTC",
            "instrument_type": "common_stock",
            "security_name": "Intel",
            "security_identifier": "CUSIP-458140100",
            "action": "purchase",
            "transaction_date": "2026-08-28",
            "holdings_as_of": "",
            "public_at": "2026-09-01T20:00:00Z",
            "public_time_precision": "timestamp",
            "first_seen_at": "2026-09-02T01:00:00Z",
            "reviewed_at": "2026-09-02T03:00:00Z",
            "amount_min": 1001,
            "amount_max": 15000,
            "currency": "USD",
            "quantity": None,
            "quantity_unit": "",
            "reported_value": None,
            "option_type": "",
            "strike": None,
            "expiry": "",
            "source_kind": "house_ptr",
            "source_url": "https://ethics.house.gov/test-001",
            "source_document_id": "test-001",
            "source_locator": "page:1,row:1",
            "source_sha256": evidence_hash,
            "reviewer": "test-reviewer",
            "rights_status": "approved",
            "review_status": "confirmed",
            "source_status": "available",
            "supersedes_id": "",
            "withdraws_id": "",
            "summary": "Test disclosure summary",
            "limitations": "Test limitations",
        }
        row.update(overrides)
        return row

    def activity_catalog(self, rows, subjects=None):
        subjects_rows = subjects if subjects is not None else [self._subject()]
        return public_opinions.build_catalog({
            "schema_version": 2,
            "catalog_version": "test-v2-activities",
            "creators": [],
            "coverage": [],
            "opinions": [],
            "outcomes": [],
            "activity_schema_version": 1,
            "subjects": subjects_rows,
            "activities": rows,
        })

    def test_activity_is_not_known_before_review(self):
        row = self.activity(public_at="2026-09-01T20:00:00Z",
                            first_seen_at="2026-09-02T01:00:00Z",
                            reviewed_at="2026-09-02T03:00:00Z")
        catalog = self.activity_catalog([row])
        result = query_activities(catalog, subject_id=None, market="US",
                                  symbol="INTC", cutoff_at=datetime.fromisoformat(
                                      "2026-09-02T02:00:00+00:00"), window_days=28)
        self.assertEqual(result, [])

    def test_same_document_two_rows_are_both_kept(self):
        first = self.activity(activity_id="test-act-001", source_locator="page:1,row:1")
        second = self.activity(activity_id="test-act-002", source_locator="page:1,row:2")
        catalog = self.activity_catalog([first, second])
        self.assertTrue(catalog["activities"][0]["is_confirmed"])
        self.assertTrue(catalog["activities"][1]["is_confirmed"])
        result = query_activities(catalog, subject_id=None, market="US", symbol="INTC",
                                  cutoff_at=datetime.fromisoformat("2026-09-03T00:00:00+00:00"),
                                  window_days=28)
        self.assertEqual([item["activity_id"] for item in result], ["test-act-001", "test-act-002"])

    def test_duplicate_row_is_single_count(self):
        first = self.activity(activity_id="test-act-dup", source_locator="page:1,row:1")
        second = self.activity(activity_id="test-act-dup", source_locator="page:1,row:1")
        catalog = self.activity_catalog([first, second])
        self.assertTrue(catalog["activities"][0]["is_confirmed"])
        self.assertFalse(catalog["activities"][1]["is_confirmed"])
        self.assertIn("duplicate_activity_id", catalog["activities"][1]["validation_errors"])
        result = query_activities(catalog, subject_id=None, market="US", symbol="INTC",
                                  cutoff_at=datetime.fromisoformat("2026-09-03T00:00:00+00:00"),
                                  window_days=28)
        self.assertEqual(len(result), 1)

    def test_owner_spouse_is_preserved(self):
        validated = validate_activity(self.activity(), self._subjects_map())
        self.assertTrue(validated["is_confirmed"])
        self.assertEqual(validated["owner"], "spouse")
        self.assertEqual(validated["subject_id"], "test-household")

    def test_holding_snapshot_has_no_transaction_date(self):
        row = self.activity(activity_id="test-13f-001", activity_type="holding_snapshot",
                            action="holding", transaction_date="", holdings_as_of="2026-06-30",
                            instrument_type="common_stock", source_kind="sec_13f",
                            source_url="https://www.sec.gov/test-13f",
                            source_document_id="test-13f", source_locator="table:1,row:1")
        validated = validate_activity(row, self._subjects_map())
        self.assertTrue(validated["is_confirmed"], validated.get("validation_errors"))

    def test_option_is_not_equity_buy(self):
        row = self.activity(activity_id="test-opt-001", instrument_type="option",
                            option_type="call", strike=20.0, expiry="2027-01-15",
                            action="purchase")
        validated = validate_activity(row, self._subjects_map())
        self.assertTrue(validated["is_confirmed"], validated.get("validation_errors"))
        self.assertEqual(validated["instrument_type"], "option")
        self.assertNotEqual(validated["instrument_type"], "common_stock")

    def test_future_revision_applies_only_after_available(self):
        original = self.activity(activity_id="test-rev-001", source_locator="page:1,row:1",
                                 public_at="2026-09-01T20:00:00Z",
                                 first_seen_at="2026-09-02T01:00:00Z",
                                 reviewed_at="2026-09-02T03:00:00Z")
        revision = self.activity(activity_id="test-rev-002", source_locator="page:1,row:1-rev2",
                                 public_at="2026-09-05T20:00:00Z",
                                 first_seen_at="2026-09-06T01:00:00Z",
                                 reviewed_at="2026-09-06T03:00:00Z",
                                 supersedes_id="test-rev-001")
        catalog = self.activity_catalog([original, revision])
        before = query_activities(catalog, subject_id=None, market="US", symbol="INTC",
                                  cutoff_at=datetime.fromisoformat("2026-09-03T00:00:00+00:00"),
                                  window_days=90)
        self.assertEqual([item["activity_id"] for item in before], ["test-rev-001"])
        after = query_activities(catalog, subject_id=None, market="US", symbol="INTC",
                                 cutoff_at=datetime.fromisoformat("2026-09-07T00:00:00+00:00"),
                                 window_days=90)
        self.assertEqual([item["activity_id"] for item in after], ["test-rev-002"])

    def test_unknown_security_and_evil_url_are_rejected(self):
        import hashlib as _hl2
        evil_hash = _hl2.sha256(b"evil").hexdigest()
        row = self.activity(activity_id="test-evil-001", market="US", symbol="ZZZZZZZZ",
                            source_url="https://evil.example.com/steal",
                            source_kind="house_ptr", source_sha256=evil_hash)
        validated = validate_activity(row, self._subjects_map())
        self.assertFalse(validated["is_confirmed"])
        self.assertTrue(any(key in validated["validation_errors"]
                            for key in ("unknown_security", "invalid_source_url")))
        catalog = self.activity_catalog([row])
        result = query_activities(catalog, subject_id=None, market="US", symbol="ZZZZZZZZ",
                                  cutoff_at=datetime.fromisoformat("2026-09-03T00:00:00+00:00"),
                                  window_days=28)
        self.assertEqual(result, [])

    def test_old_catalog_without_activities_keeps_opinions(self):
        catalog = {
            "schema_version": 2,
            "catalog_version": "legacy-no-activities",
            "creators": [{"id": "michael-sikand", "name": "Michael Sikand",
                          "platform": "X", "handle": "michaelsikand",
                          "identity_status": "verified", "source_status": "partial"}],
            "coverage": [],
            "opinions": [{
                "id": "op-1", "opinion_id": "op-1", "creator_id": "michael-sikand",
                "origin_group_id": "op-1", "source_url": "https://x.com/michaelsikand/status/900",
                "source_kind": "x_post", "source_platform": "x",
                "acquisition_method": "manual_permalink_check",
                "market": "US", "symbol": "NVDA",
                "published_at": "2026-09-16T14:30:00-04:00",
                "first_seen_at": "2026-09-17T02:30:00+08:00",
                "reviewed_at": "2026-09-17T10:00:00+08:00",
                "review_status": "confirmed", "source_status": "available",
                "content_type": "original_opinion", "stance": "bullish",
                "recommendation_kind": "explicit", "direction": "buy", "text": "good",
            }],
            "outcomes": [],
        }
        result = public_opinions.build_catalog(catalog)
        self.assertTrue(result["opinions"][0]["is_confirmed"])
        self.assertEqual(result.get("activities"), [])
        self.assertEqual(result.get("activity_errors"), [])

    def test_operations_do_not_change_consensus_denominator(self):
        from stock_papi.services import opinion_consensus
        opinion = {
            "id": "op-1", "opinion_id": "op-1", "creator_id": "michael-sikand",
            "origin_group_id": "op-1", "source_url": "https://x.com/michaelsikand/status/901",
            "source_kind": "x_post", "source_platform": "x",
            "acquisition_method": "manual_permalink_check",
            "market": "US", "symbol": "INTC",
            "published_at": "2026-09-01T14:30:00-04:00",
            "first_seen_at": "2026-09-02T01:00:00Z",
            "reviewed_at": "2026-09-02T03:00:00Z",
            "review_status": "confirmed", "source_status": "available",
            "content_type": "original_opinion", "stance": "bullish",
            "recommendation_kind": "explicit", "direction": "buy",
            "horizon": "short", "text": "buy INTC",
        }
        base = {"schema_version": 2, "catalog_version": "test-consensus",
                "creators": [{"id": "michael-sikand", "name": "M",
                              "platform": "X", "handle": "michaelsikand",
                              "identity_status": "verified", "source_status": "partial"}],
                "coverage": [], "opinions": [opinion], "outcomes": []}
        without = public_opinions.build_catalog(dict(base))
        with_activities = public_opinions.build_catalog(dict(base, subjects=[self._subject()],
                                                             activities=[self.activity()],
                                                             activity_schema_version=1))
        cutoff = datetime.fromisoformat("2026-09-10T00:00:00+00:00")
        left = opinion_consensus.build_consensus(without, market="US", symbol="INTC",
                                                 window_days=28, cutoff_at=cutoff)
        right = opinion_consensus.build_consensus(with_activities, market="US", symbol="INTC",
                                                  window_days=28, cutoff_at=cutoff)
        self.assertEqual(left["counts_by_horizon"], right["counts_by_horizon"])



if __name__ == "__main__":
    unittest.main()
