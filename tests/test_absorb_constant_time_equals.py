"""Crafted credentials must fail authentication cleanly, never raise.

`hmac.compare_digest` raises TypeError on non-ASCII str. Feeding it a
request-supplied header/cookie/query value therefore turned a crafted
credential into a 500 instead of a 403. These tests pin the corrected
behaviour at the helper and at the HTTP boundary.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app
from stock_papi.shared.validation import constant_time_equals


class ConstantTimeEqualsTests(unittest.TestCase):
    def test_matching_ascii_values_compare_equal(self):
        self.assertTrue(constant_time_equals("s3cret", "s3cret"))

    def test_differing_values_compare_unequal(self):
        self.assertFalse(constant_time_equals("s3cret", "other"))

    def test_non_ascii_is_a_mismatch_rather_than_an_error(self):
        # Previously raised TypeError, surfacing as a 500.
        for supplied in ("祕密", "Bearer ñ", "tokén"):
            with self.subTest(supplied=supplied):
                self.assertFalse(constant_time_equals(supplied, "s3cret"))

    def test_non_ascii_expected_value_is_also_safe(self):
        self.assertFalse(constant_time_equals("s3cret", "祕密"))

    def test_empty_and_non_string_values_are_mismatches(self):
        for supplied, expected in (
            ("", "s3cret"), ("s3cret", ""), (None, "s3cret"),
            ("s3cret", None), (b"s3cret", "s3cret"), (123, "s3cret"),
        ):
            with self.subTest(supplied=supplied, expected=expected):
                self.assertFalse(constant_time_equals(supplied, expected))


class CraftedCredentialHttpTests(unittest.TestCase):
    """A crafted credential is rejected with 403, not a 500."""

    def _client(self):
        return stock_app.app.test_client()

    def test_broadcast_rejects_non_ascii_header_without_error(self):
        with patch.object(stock_app, "BROADCAST_TOKEN", "testsecret"):
            response = self._client().get(
                "/broadcast_weekly", headers={"Authorization": "Bearer ñ"}
            )
        self.assertEqual(response.status_code, 403)

    def test_broadcast_rejects_non_ascii_query_token_without_error(self):
        with patch.object(stock_app, "BROADCAST_TOKEN", "testsecret"):
            response = self._client().get("/broadcast_weekly?token=%C3%B1")
        self.assertEqual(response.status_code, 403)

    def test_alert_task_rejects_non_ascii_header_without_error(self):
        with patch.object(stock_app, "ALERT_TASK_TOKEN", "testsecret"):
            response = self._client().post(
                "/tasks/check-alerts", headers={"Authorization": "Bearer ñ"}
            )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
