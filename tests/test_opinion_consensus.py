import copy
import unittest
from datetime import datetime, timezone

from stock_papi.services import public_opinions
from stock_papi.services.opinion_consensus import build_consensus


class OpinionConsensusTests(unittest.TestCase):
    def _creator(self, creator_id, handle):
        return {
            "id": creator_id,
            "name": creator_id.title(),
            "platform": "X",
            "canonical_profile_url": f"https://x.com/{handle}",
            "handle": handle,
            "identity_status": "verified",
            "source_status": "partial",
        }

    def _opinion(self, creator_id, post_id, *, opinion_id=None, **overrides):
        opinion_id = opinion_id or f"{creator_id}-{post_id}"
        row = {
            "id": opinion_id,
            "opinion_id": opinion_id,
            "creator_id": creator_id,
            "origin_group_id": opinion_id,
            "source_url": f"https://x.com/{creator_id}/status/{post_id}",
            "source_kind": "x_post",
            "source_platform": "x",
            "acquisition_method": "manual_permalink_check",
            "market": "US",
            "symbol": "NVDA",
            "published_at": "2026-09-16T10:00:00+00:00",
            "first_seen_at": "2026-09-16T10:05:00+00:00",
            "reviewed_at": "2026-09-16T10:10:00+00:00",
            "review_status": "confirmed",
            "source_status": "available",
            "content_type": "original_opinion",
            "stance": "bullish",
            "recommendation_kind": "explicit",
            "direction": "buy",
            "horizon": "short",
            "conditions": [],
            "text": "bullish NVDA",
        }
        row.update(overrides)
        return row

    def _catalog(self, opinions, coverage=None):
        creators = [
            self._creator("alpha", "alpha"),
            self._creator("bravo", "bravo"),
            self._creator("charlie", "charlie"),
            self._creator("delta", "delta"),
        ]
        document = {
            "schema_version": 2,
            "catalog_version": "consensus-test",
            "creators": creators,
            "coverage": coverage if coverage is not None else [],
            "opinions": opinions,
            "outcomes": [],
        }
        return public_opinions.build_catalog(document)

    def _cutoff(self):
        return datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)

    def test_78_manual_example_counts_activity_without_inventing_consensus(self):
        catalog = self._catalog(
            [
                self._opinion("alpha", 100, opinion_id="a-bull"),
                self._opinion(
                    "bravo",
                    101,
                    opinion_id="b-conditional",
                    recommendation_kind="conditional",
                    conditions=["breakout above 150"],
                    text="If NVDA breaks above 150 I would buy",
                ),
                self._opinion(
                    "charlie",
                    102,
                    opinion_id="c-news",
                    content_type="news_relay",
                    stance="unclear",
                    recommendation_kind="mention",
                    direction="hold",
                    origin_group_id="news-1",
                    text="Reuters: another fund says buy NVDA",
                ),
            ],
            coverage=[
                {
                    "creator_id": "alpha",
                    "source": "x_profile",
                    "status": "partial",
                    "reviewed_through": "2026-09-17T08:00:00+00:00",
                    "gaps": [],
                },
                {
                    "creator_id": "delta",
                    "source": "x_profile",
                    "status": "failure",
                    "reviewed_through": "2026-09-17T08:00:00+00:00",
                    "gaps": ["api unavailable"],
                },
            ],
        )

        result = build_consensus(
            catalog,
            market="US",
            symbol="NVDA",
            window_days=7,
            cutoff_at=self._cutoff(),
        )

        short = result["counts_by_horizon"]["short"]
        self.assertEqual(short["bullish"], 1)
        self.assertEqual(short["conditional"], 1)
        self.assertEqual(short["news"], 1)
        self.assertEqual(short["explicit_direction_denominator"], 1)
        self.assertIsNone(short["bullish_ratio"])
        self.assertEqual(short["status"], "insufficient")
        self.assertEqual([item["opinion_id"] for item in result["period_activity"]], ["a-bull", "b-conditional", "c-news"])
        self.assertEqual(result["origin_groups"]["news-1"]["activity_count"], 1)
        self.assertEqual(result["coverage"]["delta"]["status"], "failure")
        self.assertEqual(result["coverage"]["delta"]["gaps"], ["api unavailable"])
        self.assertEqual(result["evidence_ids"], ["a-bull", "b-conditional", "c-news"])
        self.assertNotIn("win_rate", result)

    def test_window_boundaries_and_cutoff_replay_use_utc_seen_and_reviewed_times(self):
        catalog = self._catalog([
            self._opinion(
                "alpha",
                110,
                opinion_id="at-24h-boundary",
                published_at="2026-09-16T08:00:00+00:00",
                first_seen_at="2026-09-16T08:01:00+00:00",
                reviewed_at="2026-09-16T08:02:00+00:00",
            ),
            self._opinion(
                "bravo",
                111,
                opinion_id="inside-7d",
                published_at="2026-09-12T08:00:00+00:00",
                first_seen_at="2026-09-12T08:01:00+00:00",
                reviewed_at="2026-09-12T08:02:00+00:00",
            ),
            self._opinion(
                "charlie",
                112,
                opinion_id="inside-28d",
                published_at="2026-08-28T08:00:00+00:00",
                first_seen_at="2026-08-28T08:01:00+00:00",
                reviewed_at="2026-08-28T08:02:00+00:00",
            ),
            self._opinion(
                "delta",
                113,
                opinion_id="reviewed-after-cutoff",
                first_seen_at="2026-09-16T10:01:00+00:00",
                reviewed_at="2026-09-17T08:01:00+00:00",
            ),
        ])

        one_day = build_consensus(catalog, market="US", symbol="NVDA", window_days=1, cutoff_at=self._cutoff())
        seven_day = build_consensus(catalog, market="US", symbol="NVDA", window_days=7, cutoff_at=self._cutoff())
        twenty_eight_day = build_consensus(catalog, market="US", symbol="NVDA", window_days=28, cutoff_at=self._cutoff())

        self.assertEqual([item["opinion_id"] for item in one_day["period_activity"]], ["at-24h-boundary"])
        self.assertEqual([item["opinion_id"] for item in seven_day["period_activity"]], ["at-24h-boundary", "inside-7d"])
        self.assertEqual(
            [item["opinion_id"] for item in twenty_eight_day["period_activity"]],
            ["at-24h-boundary", "inside-7d", "inside-28d"],
        )
        self.assertNotIn("reviewed-after-cutoff", twenty_eight_day["evidence_ids"])

    def test_latest_stances_keep_outside_window_and_exclude_superseded_or_withdrawn(self):
        catalog = self._catalog([
            self._opinion(
                "alpha",
                120,
                opinion_id="old-short-bull",
                published_at="2026-09-01T08:00:00+00:00",
                first_seen_at="2026-09-01T08:01:00+00:00",
                reviewed_at="2026-09-01T08:02:00+00:00",
            ),
            self._opinion(
                "alpha",
                121,
                opinion_id="new-short-bear",
                published_at="2026-09-16T09:00:00+00:00",
                first_seen_at="2026-09-16T09:01:00+00:00",
                reviewed_at="2026-09-16T09:02:00+00:00",
                stance="bearish",
                direction="sell",
                supersedes_id="old-short-bull",
            ),
            self._opinion(
                "bravo",
                122,
                opinion_id="outside-long-bull",
                published_at="2026-09-01T09:00:00+00:00",
                first_seen_at="2026-09-01T09:01:00+00:00",
                reviewed_at="2026-09-01T09:02:00+00:00",
                horizon="long",
            ),
            self._opinion(
                "charlie",
                123,
                opinion_id="withdrawn-long",
                published_at="2026-09-14T09:00:00+00:00",
                first_seen_at="2026-09-14T09:01:00+00:00",
                reviewed_at="2026-09-14T09:02:00+00:00",
                horizon="long",
                withdrawn_at="2026-09-15T00:00:00+00:00",
            ),
        ])

        result = build_consensus(catalog, market="US", symbol="NVDA", window_days=7, cutoff_at=self._cutoff())
        latest = {(item["creator_id"], item["horizon"]): item for item in result["latest_stances"]}

        self.assertEqual(latest[("alpha", "short")]["opinion_id"], "new-short-bear")
        self.assertFalse(latest[("alpha", "short")]["outside_window"])
        self.assertEqual(latest[("bravo", "long")]["opinion_id"], "outside-long-bull")
        self.assertTrue(latest[("bravo", "long")]["outside_window"])
        self.assertNotIn(("charlie", "long"), latest)
        self.assertNotIn("old-short-bull", result["evidence_ids"])

    def test_origin_group_keeps_creator_activity_but_one_independent_group(self):
        catalog = self._catalog([
            self._opinion(
                "alpha",
                130,
                opinion_id="news-a",
                content_type="news_relay",
                stance="unclear",
                recommendation_kind="mention",
                direction="hold",
                origin_group_id="same-news",
            ),
            self._opinion(
                "bravo",
                131,
                opinion_id="news-b",
                content_type="news_relay",
                stance="unclear",
                recommendation_kind="mention",
                direction="hold",
                origin_group_id="same-news",
            ),
        ])

        result = build_consensus(catalog, market="US", symbol="NVDA", window_days=7, cutoff_at=self._cutoff())

        self.assertEqual(len(result["period_activity"]), 2)
        self.assertEqual(result["counts_by_horizon"]["short"]["news"], 2)
        self.assertEqual(result["origin_groups"]["same-news"]["activity_count"], 2)
        self.assertEqual(result["origin_groups"]["same-news"]["independent_group_count"], 1)
        self.assertEqual(result["origin_groups"]["same-news"]["creator_ids"], ["alpha", "bravo"])

    def test_tw_us_are_separate_and_invalid_inputs_fail_closed(self):
        catalog = self._catalog([
            self._opinion("alpha", 140, opinion_id="us-tsm", market="US", symbol="TSM"),
            self._opinion("bravo", 141, opinion_id="tw-2330", market="TW", symbol="2330"),
        ])
        original = copy.deepcopy(catalog)

        tw_result = build_consensus(catalog, market="TW", symbol="2330", window_days=7, cutoff_at=self._cutoff())

        self.assertEqual([item["opinion_id"] for item in tw_result["period_activity"]], ["tw-2330"])
        self.assertEqual(catalog, original)
        for kwargs in (
            {"market": "KR", "symbol": "005930", "window_days": 7, "cutoff_at": self._cutoff()},
            {"market": "US", "symbol": "NVDA", "window_days": 2, "cutoff_at": self._cutoff()},
            {"market": "US", "symbol": "BAD TICKER", "window_days": 7, "cutoff_at": self._cutoff()},
            {"market": "US", "symbol": "NVDA", "window_days": 7, "cutoff_at": datetime(2026, 9, 17, 8, 0)},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    build_consensus(catalog, **kwargs)

    def test_ratios_use_only_explicit_directions_but_keep_mention_activity(self):
        for stance, direction, expected in (("bullish", "buy", 1.0), ("bearish", "sell", 0.0)):
            with self.subTest(stance=stance):
                catalog = self._catalog([
                    self._opinion("alpha", 160, stance=stance, direction=direction),
                    self._opinion("bravo", 161, stance=stance, direction=direction),
                    self._opinion("charlie", 162, recommendation_kind="mention"),
                    self._opinion("delta", 163, recommendation_kind="mention",
                                  stance="bearish", direction="sell"),
                ])
                result = build_consensus(catalog, market="US", symbol="NVDA",
                                         window_days=7, cutoff_at=self._cutoff())
                count = result["counts_by_horizon"]["short"]
                self.assertEqual(count["explicit_direction_denominator"], 2)
                self.assertEqual(count["bullish_ratio"], expected)
                self.assertEqual(count["bearish_ratio"], 1 - expected)
                self.assertEqual(count["bullish"] + count["bearish"], 4)
                self.assertEqual(len(result["period_activity"]), 4)

    def test_repeated_posts_do_not_turn_one_creator_into_multiple_votes(self):
        repeated = [self._opinion("alpha", 170), self._opinion("alpha", 171)]
        for extra, denominator in (([], 1), ([self._opinion("bravo", 172, stance="bearish", direction="sell")], 2)):
            with self.subTest(denominator=denominator):
                result = build_consensus(self._catalog(repeated + extra), market="US",
                                         symbol="NVDA", window_days=7, cutoff_at=self._cutoff())
                count = result["counts_by_horizon"]["short"]
                self.assertEqual(count["explicit_direction_denominator"], denominator)
                self.assertEqual(count["bullish"], 1)
                self.assertEqual(count["bullish_ratio"], None if denominator == 1 else 0.5)
                self.assertEqual(len(result["period_activity"]), 2 + len(extra))

    def test_withdrawn_latest_stance_does_not_resurrect_older_opinion(self):
        catalog = self._catalog([
            self._opinion("alpha", 180),
            self._opinion("alpha", 181, published_at="2026-09-16T11:00:00Z",
                          first_seen_at="2026-09-16T11:01:00Z", reviewed_at="2026-09-16T11:02:00Z",
                          withdrawn_at="2026-09-17T07:00:00Z"),
            self._opinion("bravo", 182, stance="bearish", direction="sell"),
        ])
        result = build_consensus(catalog, market="US", symbol="NVDA", window_days=7,
                                 cutoff_at=self._cutoff())
        self.assertEqual([r["creator_id"] for r in result["latest_stances"]], ["bravo"])
        self.assertEqual(result["counts_by_horizon"]["short"]["explicit_direction_denominator"], 1)
        self.assertEqual(len(result["period_activity"]), 3)
        before = build_consensus(catalog, market="US", symbol="NVDA", window_days=7,
                                 cutoff_at=datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
        self.assertEqual([r["opinion_id"] for r in before["latest_stances"]], ["alpha-181", "bravo-182"])

    def test_empty_denominator_has_none_ratio_and_insufficient_status(self):
        catalog = self._catalog([
            self._opinion(
                "alpha",
                150,
                opinion_id="flow",
                content_type="flow_observation",
                stance="unclear",
                recommendation_kind="mention",
                direction="hold",
            )
        ])

        result = build_consensus(catalog, market="US", symbol="NVDA", window_days=7, cutoff_at=self._cutoff())

        short = result["counts_by_horizon"]["short"]
        self.assertEqual(short["flow"], 1)
        self.assertEqual(short["explicit_direction_denominator"], 0)
        self.assertIsNone(short["bullish_ratio"])
        self.assertEqual(short["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
