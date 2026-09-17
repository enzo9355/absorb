import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_papi.batch import x_watch_cli
from stock_papi.services.x_api import XApiError


class XWatchTests(unittest.TestCase):
    def result(self, handle, ids, author="42"):
        return {"user": {"username": handle, "id": author, "name": handle},
                "posts": [{"id": str(i), "text": "post " + str(i),
                           "created_at": "2026-09-17T01:00:00Z", "author_id": author} for i in ids],
                "acquisition_method": "fx_twitter_user_timeline", "pages_fetched": 1,
                "has_more": True, "fetched_at": "2026-09-17T02:00:00Z"}

    def test_new_posts_are_archived_deduplicated_and_keep_first_seen(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch.object(x_watch_cli, "SOURCES", {"alpha": "a"}):
            root = Path(folder)
            with patch.object(x_watch_cli, "FxTwitterClient") as factory:
                factory.return_value.fetch_user_posts.side_effect = [
                    self.result("alpha", [1, 2]), self.result("alpha", [2, 3]), self.result("alpha", [2, 3])]
                first = x_watch_cli.run_once(root, now=now)
                second = x_watch_cli.run_once(root, now=now + timedelta(minutes=5))
                third = x_watch_cli.run_once(root, now=now + timedelta(minutes=10))
            self.assertEqual([2, 1, 0], [s["accounts"]["alpha"]["new_posts"] for s in (first, second, third)])
            self.assertTrue((root / "x-history/alpha/1.json").exists())
            snapshot = json.loads((root / "x-candidates/alpha.json").read_text(encoding="utf-8"))
            row = next(r for r in snapshot["opinions"] if r["opinion_id"] == "x:2")
            self.assertEqual(row["first_seen_at"], now.isoformat().replace("+00:00", "Z"))
            self.assertEqual(row["review_status"], "pending_review")
            self.assertFalse((root / "public-opinions.json").exists())

    def test_one_failure_keeps_snapshot_and_other_account_runs_with_backoff(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch.object(x_watch_cli, "SOURCES", {"alpha": "a", "bravo": "b"}):
            root = Path(folder)
            with patch.object(x_watch_cli, "FxTwitterClient") as factory:
                client = factory.return_value
                client.fetch_user_posts.side_effect = lambda handle, **kw: self.result(handle, [1])
                x_watch_cli.run_once(root, now=now)
                before = (root / "x-candidates/alpha.json").read_bytes()
                def fail_alpha(handle, **kw):
                    if handle == "alpha":
                        raise XApiError("rate limited", status_code=429)
                    return self.result(handle, [2])
                client.fetch_user_posts.side_effect = fail_alpha
                status = x_watch_cli.run_once(root, now=now + timedelta(minutes=5))
                self.assertEqual("error", status["accounts"]["alpha"]["status"])
                self.assertEqual("ok", status["accounts"]["bravo"]["status"])
                self.assertEqual(before, (root / "x-candidates/alpha.json").read_bytes())
                client.reset_mock()
                x_watch_cli.run_once(root, now=now + timedelta(minutes=6))
                self.assertEqual(["bravo"], [call.args[0] for call in client.fetch_user_posts.call_args_list])

    def test_author_change_between_runs_is_rejected(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch.object(x_watch_cli, "SOURCES", {"alpha": "a"}):
            root = Path(folder)
            with patch.object(x_watch_cli, "FxTwitterClient") as factory:
                factory.return_value.fetch_user_posts.side_effect = [self.result("alpha", [1]), self.result("alpha", [2], author="99")]
                x_watch_cli.run_once(root, now=now)
                before = (root / "x-candidates/alpha.json").read_bytes()
                status = x_watch_cli.run_once(root, now=now + timedelta(minutes=5))
            self.assertEqual("error", status["accounts"]["alpha"]["status"])
            self.assertEqual(before, (root / "x-candidates/alpha.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
