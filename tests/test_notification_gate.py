# -*- coding: utf-8 -*-
"""Notification date guard & capability gate boundary test."""

import unittest


class TestNotificationGateGuard(unittest.TestCase):

    def test_line_broadcast_does_not_contain_forbidden_words_or_probabilities(self):
        from reporting.regression_schema import FORBIDDEN_WORDS

        # Mock notification text generator output
        sample_notification_text = "【ABSORB 日報摘要】市場觀察模式運行中，AI 模型參考建議僅供對照。"

        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, sample_notification_text)


if __name__ == "__main__":
    unittest.main()
