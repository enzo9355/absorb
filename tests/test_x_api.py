import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from stock_papi.services.x_api import (
    XApiClient,
    XApiConfig,
    XApiError,
    build_pending_candidate,
    canonical_post_url,
)
from stock_papi.services.public_opinions import build_catalog


def _response(data, *, meta=None):
    payload = {"data": data}
    if meta is not None:
        payload["meta"] = meta
    return 200, json.dumps(payload).encode("utf-8")


class XApiClientTests(unittest.TestCase):
    def test_missing_token_fails_closed_before_transport(self):
        with self.assertRaisesRegex(XApiError, "not configured"):
            XApiClient(XApiConfig(bearer_token=""))

    def test_rejects_non_https_base_url(self):
        with self.assertRaisesRegex(XApiError, "api.x.com"):
            XApiClient(XApiConfig(bearer_token="token", base_url="http://x.test/2"))

    def test_rejects_non_x_api_host(self):
        with self.assertRaisesRegex(XApiError, "api.x.com"):
            XApiClient(XApiConfig(bearer_token="token", base_url="https://proxy.test/2"))

    def test_lookup_and_timeline_paginate_with_bearer_and_exclusions(self):
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, dict(headers), timeout))
            if "/users/by/username/" in url:
                return _response({"id": "42", "username": "unusual_whales", "name": "Unusual Whales"})
            if "pagination_token=next-1" in url:
                return _response(
                    [{"id": "2", "text": "Buy NVDA", "created_at": "2026-09-16T12:00:00Z"}],
                    meta={},
                )
            return _response(
                [{"id": "1", "text": "Watch NVDA", "created_at": "2026-09-17T12:00:00Z"}],
                meta={"next_token": "next-1"},
            )

        result = XApiClient(
            XApiConfig(bearer_token="secret", max_pages=3), transport=transport,
        ).fetch_user_posts("@Unusual_Whales", max_pages=2)
        self.assertEqual(["1", "2"], [row["id"] for row in result["posts"]])
        self.assertEqual(2, result["pages_fetched"])
        self.assertTrue(result["has_more"])
        self.assertEqual("Bearer secret", calls[0][1]["Authorization"])
        self.assertIn("exclude=retweets%2Creplies", calls[1][0])
        self.assertIn("max_results=100", calls[1][0])

    def test_repeated_page_token_stops_without_duplicate_requests(self):
        count = {"timeline": 0}

        def transport(url, headers, timeout):
            if "/users/by/username/" in url:
                return _response({"id": "42", "username": "creator"})
            count["timeline"] += 1
            return _response([{"id": "1", "text": "x", "created_at": "2026-09-17T00:00:00Z"}], meta={"next_token": "same"})

        result = XApiClient(XApiConfig(bearer_token="secret", max_pages=50), transport=transport).fetch_user_posts("creator")
        self.assertEqual(2, count["timeline"])
        self.assertEqual(["1"], [row["id"] for row in result["posts"]])

    def test_invalid_time_and_page_bounds_are_rejected(self):
        client = XApiClient(XApiConfig(bearer_token="secret"), transport=lambda *args: _response({}))
        with self.assertRaisesRegex(ValueError, "timezone"):
            client.fetch_user_posts("creator", start_time="2026-09-17")
        with self.assertRaisesRegex(ValueError, "between"):
            client.fetch_user_posts("creator", max_pages=0)

    def test_http_and_json_errors_are_safe(self):
        def http_error(*args):
            raise XApiError("safe failure", status_code=429)

        with self.assertRaisesRegex(XApiError, "safe failure"):
            XApiClient(XApiConfig(bearer_token="secret"), transport=http_error).lookup_user("creator")

        def bad_json(*args):
            return 200, b"not-json"

        with self.assertRaisesRegex(XApiError, "invalid JSON"):
            XApiClient(XApiConfig(bearer_token="secret"), transport=bad_json).lookup_user("creator")


class XCandidateTests(unittest.TestCase):
    def test_post_url_is_canonical_and_query_free(self):
        self.assertEqual(
            "https://x.com/unusual_whales/status/123",
            canonical_post_url("unusual_whales", "123"),
        )
        with self.assertRaises(ValueError):
            canonical_post_url("bad/name", "123")

    def test_candidate_rows_are_pending_and_stable_by_post_id(self):
        now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
        result = {
            "user": {"id": "42", "username": "unusual_whales", "name": "Unusual Whales"},
            "posts": [
                {"id": "123", "text": "Bullish on NVDA", "created_at": "2026-09-17T10:00:00Z", "conversation_id": "123"},
                {"id": "123", "text": "duplicate", "created_at": "2026-09-17T10:01:00Z"},
            ],
            "pages_fetched": 1,
            "fetched_at": "2026-09-17T12:00:00Z",
        }
        candidate = build_pending_candidate(
            result, creator_id="unusual-whales", market="US", symbol="NVDA", now=now,
        )
        self.assertEqual(["x:123"], [row["opinion_id"] for row in candidate["opinions"]])
        row = candidate["opinions"][0]
        self.assertEqual("pending_review", row["review_status"])
        self.assertEqual("available", row["source_status"])
        self.assertEqual("https://x.com/unusual_whales/status/123", row["source_url"])
        self.assertEqual("pending_review", candidate["coverage"][0]["status"])
        self.assertEqual("x_api_v2_user_timeline", row["acquisition_method"])
        validated = build_catalog(candidate)
        self.assertFalse(validated["opinions"][0]["is_confirmed"])
        self.assertIn("creator_identity_unverified", validated["opinions"][0]["validation_errors"])

    def test_candidate_without_security_stays_unmapped(self):
        result = {
            "user": {"id": "42", "username": "creator"},
            "posts": [{"id": "123", "text": "A post", "created_at": "2026-09-17T10:00:00Z"}],
        }
        candidate = build_pending_candidate(result, creator_id="creator")
        self.assertEqual("", candidate["opinions"][0]["symbol"])
        self.assertEqual("unmapped", candidate["opinions"][0]["security_status"])
        self.assertEqual("pending_review", candidate["opinions"][0]["review_status"])


if __name__ == "__main__":
    unittest.main()
