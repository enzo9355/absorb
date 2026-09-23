# The suite shares one Flask app instance across many test modules, so the
# per-instance conversation rate limiter would accumulate requests across
# unrelated tests and return 429 where a test expects a validation status.
# Disable that limiter for tests; production leaves it enabled by default.
import os

os.environ.setdefault("ABSORB_CONVERSATION_RATE_LIMIT", "off")
