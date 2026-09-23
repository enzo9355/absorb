"""Coverage for the per-instance rate limit on the LLM-backed conversation API."""

import unittest
from unittest.mock import patch

from flask import Flask

from absorb.conversation.schemas import ConversationAnswer
from absorb.conversation.web import (
    _RATE_MAX_REQUESTS,
    register_conversation_routes,
)


def _build_client():
    """A bare app with fresh limiter state and a cheap stub converse."""
    app = Flask("rate-limit-test")
    calls = {"count": 0}

    def converse(**_kwargs):
        calls["count"] += 1
        return ConversationAnswer("ok", data_quality="available")

    register_conversation_routes(
        app,
        converse=converse,
        resolve_authenticated_identity=lambda _request: None,
    )
    return app.test_client(), calls


class ConversationRateLimitTests(unittest.TestCase):
    def _post(self, client):
        return client.post("/api/conversation", json={"question": "台積電如何？"})

    def test_requests_are_blocked_after_threshold_when_enabled(self):
        client, calls = _build_client()
        with patch("absorb.conversation.web._rate_limit_enabled", return_value=True):
            allowed = [self._post(client).status_code for _ in range(_RATE_MAX_REQUESTS)]
            blocked = self._post(client)

        self.assertTrue(all(code == 200 for code in allowed), allowed)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers.get("Retry-After"), "60")
        # A rate-limited request must not reach the expensive converse call.
        self.assertEqual(calls["count"], _RATE_MAX_REQUESTS)

    def test_limiter_is_bypassed_when_disabled(self):
        client, _calls = _build_client()
        with patch("absorb.conversation.web._rate_limit_enabled", return_value=False):
            codes = [self._post(client).status_code for _ in range(_RATE_MAX_REQUESTS + 5)]
        self.assertTrue(all(code == 200 for code in codes), codes)


if __name__ == "__main__":
    unittest.main()
