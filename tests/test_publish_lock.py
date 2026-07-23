"""Cross-process report-v2 publication lock tests."""

import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reporting.exceptions import ReportPublishError
from reporting.publish_lock import report_v2_publish_lock


LOCK_NAME = ".publish-transaction-lock"


def _hold_publish_lock(root, ready, release):
    with report_v2_publish_lock(Path(root)):
        ready.set()
        if not release.wait(10):
            raise RuntimeError("timed out waiting to release publish lock")


class ReportV2PublishLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lock_path = self.root / "publish" / "reports" / "v2" / LOCK_NAME

    def tearDown(self):
        self.temp.cleanup()

    def test_lock_is_cross_process_visible_and_fails_closed_without_waiting(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_publish_lock,
            args=(str(self.root), ready, release),
        )
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            with self.assertRaisesRegex(ReportPublishError, "already held"):
                with report_v2_publish_lock(self.root):
                    self.fail("contending publisher entered the lock")
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(10)

        self.assertEqual(process.exitcode, 0)
        with report_v2_publish_lock(self.root):
            self.assertTrue(self.lock_path.is_dir())
        self.assertFalse(self.lock_path.exists())

    def test_success_uses_unique_owner_tokens_and_releases_lock(self):
        owner_tokens = []
        for _ in range(2):
            with report_v2_publish_lock(self.root):
                owner_files = list(self.lock_path.iterdir())
                self.assertEqual(len(owner_files), 1)
                owner_token = owner_files[0].read_text(encoding="ascii")
                self.assertRegex(owner_token, r"\A[0-9a-f]{64}\Z")
                owner_tokens.append(owner_token)
            self.assertFalse(self.lock_path.exists())

        self.assertNotEqual(owner_tokens[0], owner_tokens[1])

    def test_lock_is_released_when_body_fails(self):
        with self.assertRaisesRegex(ValueError, "body failed"):
            with report_v2_publish_lock(self.root):
                raise ValueError("body failed")

        self.assertFalse(self.lock_path.exists())

    def test_foreign_owner_lock_cannot_be_removed(self):
        manager = report_v2_publish_lock(self.root)
        manager.__enter__()
        owner_file = next(self.lock_path.iterdir())
        owner_file.write_text("foreign-owner", encoding="ascii")

        with self.assertRaisesRegex(ReportPublishError, "ownership"):
            manager.__exit__(None, None, None)

        self.assertTrue(self.lock_path.is_dir())
        self.assertEqual(owner_file.read_text(encoding="ascii"), "foreign-owner")

    def test_corrupt_owner_lock_cannot_be_removed(self):
        manager = report_v2_publish_lock(self.root)
        manager.__enter__()
        owner_file = next(self.lock_path.iterdir())
        owner_file.write_bytes(b"\xff")

        with self.assertRaisesRegex(ReportPublishError, "ownership"):
            manager.__exit__(None, None, None)

        self.assertTrue(self.lock_path.is_dir())
        self.assertEqual(owner_file.read_bytes(), b"\xff")

    def test_stale_lock_fails_closed_and_is_not_removed(self):
        self.lock_path.mkdir(parents=True)
        owner_file = self.lock_path / "owner-token"
        owner_file.write_text("stale-owner", encoding="ascii")

        with self.assertRaisesRegex(ReportPublishError, "already held"):
            with report_v2_publish_lock(self.root):
                self.fail("stale lock was removed automatically")

        self.assertTrue(self.lock_path.is_dir())
        self.assertEqual(owner_file.read_text(encoding="ascii"), "stale-owner")

    def test_lock_cleanup_failure_is_reported_and_lock_remains_fail_closed(self):
        real_rmdir = Path.rmdir

        def fail_lock_rmdir(path):
            if path == self.lock_path:
                raise OSError("injected lock cleanup failure")
            return real_rmdir(path)

        with mock.patch.object(Path, "rmdir", fail_lock_rmdir):
            with self.assertRaisesRegex(ReportPublishError, "release"):
                with report_v2_publish_lock(self.root):
                    pass

        self.assertTrue(self.lock_path.is_dir())
        with self.assertRaisesRegex(ReportPublishError, "already held"):
            with report_v2_publish_lock(self.root):
                self.fail("cleanup failure lock was bypassed")


if __name__ == "__main__":
    unittest.main()
