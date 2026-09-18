import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import jsonify, make_response, request

from absorb.conversation.renderers import render_web


COOKIE_NAME = "absorb_conversation"
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,12}$")
# Bound the cost of the LLM-backed endpoint per client. This is a per-instance
# in-process limiter (the app runs with a single Gunicorn worker); with multiple
# Cloud Run instances it caps amplification per instance rather than globally.
# Set ABSORB_CONVERSATION_RATE_LIMIT=off to disable (used by the test suite).
_RATE_WINDOW_SECONDS = 60.0
_RATE_MAX_REQUESTS = 30
_RATE_DISABLED_VALUES = {"off", "0", "false", "no", "disabled"}


def _rate_limit_enabled():
    return (
        os.environ.get("ABSORB_CONVERSATION_RATE_LIMIT", "on").strip().lower()
        not in _RATE_DISABLED_VALUES
    )


def register_conversation_routes(app, *, converse, resolve_authenticated_identity):
    request_log = defaultdict(deque)
    request_log_lock = threading.Lock()

    def rate_limit_allowed():
        if not _rate_limit_enabled():
            return True
        key = request.remote_addr or "unknown"
        cutoff = time.monotonic() - _RATE_WINDOW_SECONDS
        with request_log_lock:
            attempts = request_log[key]
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= _RATE_MAX_REQUESTS:
                return False
            attempts.append(time.monotonic())
            if len(request_log) > 4096:
                # Bound memory: drop the coldest idle buckets.
                for stale_key in [k for k, v in request_log.items() if not v][:1024]:
                    request_log.pop(stale_key, None)
            return True

    def conversation_api():
        if not rate_limit_allowed():
            response = _private(jsonify({"error": "rate limited"}), 429)
            response.headers["Retry-After"] = "60"
            return response
        if not request.is_json:
            return _private(jsonify({"error": "JSON body required"}), 415)
        payload = request.get_json(silent=True)
        allowed_fields = {"question", "market", "page", "symbol"}
        if (
            not isinstance(payload, dict)
            or "question" not in payload
            or not set(payload) <= allowed_fields
        ):
            return _private(jsonify({"error": "invalid request"}), 400)
        market = payload.get("market", "TW")
        page = payload.get("page", "home")
        raw_symbol = payload.get("symbol")
        if not all(
            isinstance(value, str)
            for value in (payload["question"], market, page)
        ):
            return _private(jsonify({"error": "invalid request"}), 400)
        if market not in {"TW", "US"} or page not in {
            "home", "market", "industries", "stocks", "reports", "stock", "ask", "learn"
        }:
            return _private(jsonify({"error": "invalid context"}), 400)
        symbol = None
        if raw_symbol is not None:
            if not isinstance(raw_symbol, str) or not _SYMBOL_PATTERN.fullmatch(raw_symbol.strip()):
                return _private(jsonify({"error": "invalid request"}), 400)
            if page == "stock":
                symbol = raw_symbol.strip()
        identity = resolve_authenticated_identity(request)
        cookie_value = request.cookies.get(COOKIE_NAME, "")
        set_cookie = False
        if identity is not None:
            principal, access = identity
        else:
            if not (16 <= len(cookie_value) <= 128 and all(char.isalnum() or char in "_-" for char in cookie_value)):
                cookie_value = secrets.token_urlsafe(24)
                set_cookie = True
            principal, access = f"web:{cookie_value}", "public"
        answer = converse(
            principal=principal, question=payload["question"], access=access,
            market_context=market, page_context=page, symbol_context=symbol,
        )
        response = _private(jsonify(render_web(answer)))
        if set_cookie:
            response.set_cookie(
                COOKIE_NAME,
                cookie_value,
                max_age=1800,
                secure=request.is_secure,
                httponly=True,
                samesite="Lax",
                path="/",
            )
        return response

    app.add_url_rule("/api/conversation", "conversation_api", conversation_api, methods=["POST"])


def _private(response, status=None):
    response = make_response(response, status) if status is not None else make_response(response)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"
    return response
