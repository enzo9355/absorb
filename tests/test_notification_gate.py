# -*- coding: utf-8 -*-
"""Guard the real report notification generator without sending LINE."""

import datetime
import tempfile
import unittest

from reporting.regression_schema import FORBIDDEN_WORDS
from stock_papi.batch.notifications import NotificationManager


class TestNotificationGateGuard(unittest.TestCase):

    def test_actual_notification_generator_has_no_regression_prediction_language(self):
        captured = []
        with tempfile.TemporaryDirectory() as root:
            manager = NotificationManager(
                root,
                send=lambda message, audience: captured.append((message, audience)),
            )
            receipt = manager.deliver(
                report_type="post_close",
                content_sha256="a" * 64,
                audience="broadcast",
                public_url="https://example.com/reports/2026-07-17/post-close",
                summary=["市場觀察資料已更新", "量化研究仍維持不可用"],
                now=datetime.datetime(2026, 7, 17, 10, 30, tzinfo=datetime.timezone.utc),
            )

        self.assertEqual(receipt["status"], "sent")
        self.assertEqual(len(captured), 1)
        message, audience = captured[0]
        self.assertEqual(audience, "broadcast")
        self.assertIn("ABSORB 盤後分析", message)
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, message)


if __name__ == "__main__":
    unittest.main()
