import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from stock_papi.batch import x_opinions_cli
from stock_papi.services.fx_twitter import FxTwitterClient
from stock_papi.services.x_api import XApiError, build_pending_candidate


def _post(post_id="1", **changes):
    row = {
        "type": "status", "id": post_id, "text": "Watch NVDA",
        "created_at": "Thu Sep 17 12:00:00 +0000 2026",
        "author": {"screen_name": "creator", "name": "Creator", "id": "42"},
    }
    row.update(changes)
    return row


def _response(rows, cursor=None, code=200):
    return 200, json.dumps({
        "code": code, "results": rows, "cursor": {"bottom": cursor},
    }).encode("utf-8")


class FxTwitterClientTests(unittest.TestCase):
    def test_same_handle_cannot_change_author_id(self):
        rows = [_post(), _post("2", author={"screen_name": "creator", "id": "43"})]
        with self.assertRaisesRegex(XApiError, "conflicting author ids"):
            FxTwitterClient(transport=lambda *args: _response(rows)).fetch_user_posts("creator")

    def test_candidate_preserves_free_source_and_pending_review(self):
        result = FxTwitterClient(transport=lambda *args: _response([_post()])).fetch_user_posts("creator")
        candidate = build_pending_candidate(result, creator_id="creator", market="US", symbol="NVDA")
        self.assertEqual("fx_twitter_user_timeline", candidate["opinions"][0]["acquisition_method"])
        self.assertEqual("pending_review", candidate["opinions"][0]["review_status"])
        self.assertEqual("fx_twitter_user_timeline", candidate["coverage"][0]["acquisition_method"])
        self.assertNotIn("official X API", candidate["coverage"][0]["rights_note"])

    def test_two_pages_deduplicate_and_exhaust_without_auth(self):
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, headers, timeout))
            if len(calls) == 1:
                return _response([_post()], "next +/=")
            return _response([_post(), _post("2")])

        result = FxTwitterClient(transport=transport).fetch_user_posts("@Creator")
        self.assertEqual(["1", "2"], [row["id"] for row in result["posts"]])
        self.assertEqual({"username": "creator", "name": "Creator", "id": "42"}, result["user"])
        self.assertEqual("fx_twitter_user_timeline", result["acquisition_method"])
        self.assertEqual(2, result["pages_fetched"])
        self.assertFalse(result["has_more"])
        self.assertEqual("exhausted", result["stop_reason"])
        self.assertIsNotNone(datetime.fromisoformat(result["fetched_at"].replace("Z", "+00:00")).tzinfo)
        row = result["posts"][0]
        self.assertEqual("Watch NVDA", row["text"])
        self.assertEqual("42", row["author_id"])
        self.assertEqual("2026-09-17T12:00:00+00:00", datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).isoformat())
        for url, headers, timeout in calls:
            parsed = urlparse(url)
            self.assertEqual("https", parsed.scheme)
            self.assertEqual("api.fxtwitter.com", parsed.netloc)
            self.assertEqual("/2/profile/creator/statuses", parsed.path)
            self.assertEqual(["100"], parse_qs(parsed.query)["count"])
            self.assertFalse({key.lower() for key in headers} & {"authorization", "cookie", "x-api-key"})
            self.assertGreater(timeout, 0)
        self.assertEqual(["next +/="], parse_qs(urlparse(calls[1][0]).query)["cursor"])

    def test_reposts_and_tombstones_are_counted_and_skipped(self):
        rows = [
            _post(),
            _post("2", author={"screen_name": "other", "name": "Other", "id": "9"}),
            _post("3", is_retweet=True),
            {"type": "tombstone"},
        ]
        result = FxTwitterClient(transport=lambda *args: _response(rows)).fetch_user_posts("creator")
        self.assertEqual(["1"], [row["id"] for row in result["posts"]])
        self.assertEqual(2, result["skipped"]["reposts"])
        self.assertEqual(1, result["skipped"]["unavailable"])

    def test_invalid_json_codes_and_rows_fail_closed(self):
        responses = [
            (200, b"not-json"), (200, b"null"), (200, b"[]"),
            (503, b"unavailable"), _response([], code=401),
            _response({"not": "a list"}), _response([None]),
            _response([{"type": "unknown"}]),
        ]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(XApiError):
                    FxTwitterClient(transport=lambda *args: response).fetch_user_posts("creator")

    def test_missing_or_invalid_required_fields_fail_closed(self):
        rows = []
        for key in ("id", "text", "created_at", "author"):
            row = _post()
            del row[key]
            rows.append(row)
            rows.append(_post(**{key: None}))
        rows.extend([
            _post(id=""), _post(text=123), _post(created_at="not a date"),
            _post(author={}), _post(author={"screen_name": "creator"}),
            _post(author={"screen_name": None, "id": "42", "name": "Creator"}),
        ])
        for row in rows:
            with self.subTest(row=row):
                with self.assertRaises(XApiError):
                    FxTwitterClient(transport=lambda *args: _response([row])).fetch_user_posts("creator")

    def test_invalid_input_never_calls_transport(self):
        def transport(*args):
            self.fail("invalid arguments reached transport")

        client = FxTwitterClient(transport=transport)
        for username, kwargs in [
            ("", {}), ("../creator", {}), ("creator?x=1", {}),
            ("creator", {"max_pages": 0}), ("creator", {"max_pages": True}),
            ("creator", {"start_time": "2026-09-17"}),
            ("creator", {"end_time": "bad"}),
            ("creator", {"start_time": "2026-09-18T00:00:00Z", "end_time": "2026-09-17T00:00:00Z"}),
        ]:
            with self.subTest(username=username, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    client.fetch_user_posts(username, **kwargs)

    def test_repeated_cursor_stops_with_more_data_flag(self):
        calls = []

        def transport(*args):
            calls.append(args)
            return _response([_post()], "same")

        result = FxTwitterClient(transport=transport).fetch_user_posts("creator", max_pages=3)
        self.assertEqual(2, len(calls))
        self.assertEqual(["1"], [row["id"] for row in result["posts"]])
        self.assertTrue(result["has_more"])
        self.assertEqual("repeated_cursor", result["stop_reason"])

    def test_time_window_does_not_stop_at_old_pinned_post(self):
        calls = []

        def transport(*args):
            calls.append(args)
            if len(calls) == 1:
                return _response([
                    _post("11", created_at="Tue Sep 01 12:00:00 +0000 2026"),
                    _post("12", created_at="Fri Sep 18 12:00:00 +0000 2026"),
                ], "next")
            return _response([_post("13")])

        result = FxTwitterClient(transport=transport).fetch_user_posts(
            "creator", start_time="2026-09-17T00:00:00Z", end_time="2026-09-18T00:00:00Z",
        )
        self.assertEqual(2, len(calls))
        self.assertEqual(["13"], [row["id"] for row in result["posts"]])
        self.assertEqual(2, result["skipped"]["outside_window"])
        self.assertFalse(result["has_more"])


class FxTwitterCliTests(unittest.TestCase):
    def _args(self, output):
        return ["--username", "creator", "--creator-id", "creator", "--output", str(output)]

    def test_defaults_to_free_provider_even_with_token(self):
        result = FxTwitterClient(transport=lambda *args: _response([_post()])).fetch_user_posts("creator")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.json"
            with patch.dict(os.environ, {"X_BEARER_TOKEN": "configured-secret"}), patch.object(
                x_opinions_cli, "FxTwitterClient",
            ) as free, patch.object(x_opinions_cli, "XApiClient") as paid, redirect_stdout(io.StringIO()):
                free.return_value.fetch_user_posts.return_value = result
                self.assertEqual(0, x_opinions_cli.main(self._args(output)))
                paid.assert_not_called()
                free.return_value.fetch_user_posts.assert_called_once_with(
                    "creator", start_time=None, end_time=None, max_pages=3,
                )
            candidate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("fx_twitter_user_timeline", candidate["opinions"][0]["acquisition_method"])

    def test_fetch_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.json"
            output.write_bytes(b"existing evidence\n")
            with patch.object(x_opinions_cli, "FxTwitterClient") as free, redirect_stderr(io.StringIO()):
                free.return_value.fetch_user_posts.side_effect = XApiError("upstream unavailable")
                self.assertEqual(2, x_opinions_cli.main(self._args(output)))
            self.assertEqual(b"existing evidence\n", output.read_bytes())

    def test_zero_page_limit_refuses_without_request_or_output(self):
        def transport(*args):
            self.fail("invalid page limit reached transport")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.json"
            with patch.object(x_opinions_cli, "FxTwitterClient", return_value=FxTwitterClient(transport=transport)), redirect_stderr(io.StringIO()):
                self.assertEqual(2, x_opinions_cli.main(self._args(output) + ["--max-pages", "0"]))
            self.assertFalse(output.exists())

    def test_public_catalog_output_is_blocked_before_fetch(self):
        output = Path(x_opinions_cli.__file__).resolve().parents[2] / "data" / "research" / "public-opinions.json"
        with patch.object(x_opinions_cli, "FxTwitterClient") as free, patch.object(x_opinions_cli, "_write_json") as write, redirect_stderr(io.StringIO()):
            self.assertEqual(2, x_opinions_cli.main(self._args(output)))
            free.assert_not_called()
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
