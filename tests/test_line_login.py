import datetime
import unittest
from urllib.parse import parse_qs, urlparse

from flask import Flask

from stock_papi.services.auth import (
    LineLoginConfig,
    create_pkce_pair,
    safe_return_path,
    sign_opaque_token,
    verify_line_claims,
)
from stock_papi.web.routes.auth import register_auth_routes
from stock_papi.shared.logging import redact_secrets


NOW = datetime.datetime(2026, 7, 13, 4, 0, tzinfo=datetime.timezone.utc)
USER_ID = "U" + "a" * 32


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.nonce = None
        self.token_status = 200
        self.verify_status = 200
        self.claim_overrides = {}

    def post(self, url, *, data, timeout):
        self.calls.append((url, dict(data), timeout))
        if url.endswith("/token"):
            return FakeResponse(self.token_status, {"id_token": "verified.id.token"})
        claims = {
            "iss": "https://access.line.me",
            "aud": "1234567890",
            "exp": int(NOW.timestamp()) + 300,
            "nonce": self.nonce,
            "sub": USER_ID,
            "name": "測試使用者",
            "picture": "https://profile.line-scdn.net/avatar.png",
        }
        claims.update(self.claim_overrides)
        return FakeResponse(self.verify_status, claims)


class FakeAuthStore:
    def __init__(self):
        self.attempts = {}
        self.sessions = {}
        self.users = {}
        self.deleted_sessions = []

    def create_oauth_attempt(self, attempt_id, value):
        if attempt_id in self.attempts:
            raise RuntimeError("collision")
        self.attempts[attempt_id] = dict(value)

    def consume_oauth_attempt(self, attempt_id, now):
        value = self.attempts.pop(attempt_id, None)
        if value is None or value["expires_at"] <= now:
            return None
        return value

    def create_session(self, session_id, value):
        self.sessions[session_id] = dict(value)

    def load_session(self, session_id, now):
        value = self.sessions.get(session_id)
        return dict(value) if value and value["expires_at"] > now else None

    def delete_session(self, session_id):
        self.deleted_sessions.append(session_id)
        self.sessions.pop(session_id, None)

    def upsert_user(self, user_id, profile):
        existing = self.users.get(user_id, {"login_count": 0, "created_at": NOW})
        existing.update(profile)
        existing["login_count"] += 1
        self.users[user_id] = existing
        return dict(existing)

    def get_user(self, user_id):
        value = self.users.get(user_id)
        return dict(value) if value else None


class FakeLineStore:
    def __init__(self):
        self.users = {}
        self.updated_user_ids = []

    def load(self, user_id):
        state = self.users.setdefault(user_id, {
            "watchlist": [], "alerts": [], "pending": {},
            "signals": {"as_of": None, "items": []},
        })
        return state, None

    def update(self, user_id, mutate):
        state, _ = self.load(user_id)
        mutate(state)
        self.updated_user_ids.append(user_id)
        return state


class LineLoginTests(unittest.TestCase):
    def setUp(self):
        self.auth_store = FakeAuthStore()
        self.line_store = FakeLineStore()
        self.http = FakeHttp()
        self.config = LineLoginConfig(
            channel_id="1234567890",
            channel_secret="channel-secret",
            redirect_uri="http://localhost/auth/line/callback",
            session_secret="s" * 32,
            cookie_secure=False,
        )
        app = Flask(__name__, template_folder="../templates", static_folder="../static")
        app.config.update(TESTING=True)
        register_auth_routes(
            app,
            config=self.config,
            auth_store=lambda: self.auth_store,
            line_store=lambda: self.line_store,
            search_stock=lambda code: (code, "台積電") if code == "2330" else (None, None),
            http_post=self.http.post,
            now=lambda: NOW,
        )
        self.client = app.test_client()

    def _start_login(self, return_to="/stock/2330"):
        response = self.client.get("/auth/line/login", query_string={"return_to": return_to})
        query = parse_qs(urlparse(response.headers["Location"]).query)
        self.http.nonce = query["nonce"][0]
        return response, query

    def _login(self):
        _response, query = self._start_login()
        return self.client.get("/auth/line/callback", query_string={
            "code": "authorization-code", "state": query["state"][0],
        })

    def test_pkce_and_safe_return_path(self):
        verifier, challenge = create_pkce_pair()

        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertNotEqual(verifier, challenge)
        self.assertEqual(safe_return_path("/stock/2330?tab=risk"), "/stock/2330?tab=risk")
        for unsafe in ("https://evil.test", "//evil.test", "/\\evil", "/%0d%0aX", "stock/2330"):
            self.assertEqual(safe_return_path(unsafe), "/")
        self.assertFalse(LineLoginConfig(
            "1234567890", "secret", "https://app.example/callback", "s" * 32,
            cookie_secure=False,
        ).configured)
        self.assertFalse(LineLoginConfig(
            "1234567890", "secret", "http://localhost/callback", "s" * 32,
            cookie_secure=True,
        ).configured)

    def test_login_generates_state_nonce_pkce_and_server_attempt(self):
        response, query = self._start_login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response.headers["Location"]).netloc, "access.line.me")
        self.assertEqual(query["scope"], ["openid profile"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(len(self.auth_store.attempts), 1)
        attempt = next(iter(self.auth_store.attempts.values()))
        self.assertEqual(attempt["nonce"], query["nonce"][0])
        self.assertNotEqual(attempt["code_verifier"], query["code_challenge"][0])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_callback_success_verifies_id_token_rotates_session_and_returns(self):
        response = self._login()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/stock/2330"))
        self.assertEqual(len(self.auth_store.sessions), 1)
        session = next(iter(self.auth_store.sessions.values()))
        self.assertEqual(session["line_user_id"], USER_ID)
        self.assertNotIn("id_token", str(session))
        self.assertNotIn("access_token", str(session))
        self.assertEqual(self.auth_store.users[USER_ID]["plan"], "free")
        self.assertEqual(len(self.http.calls), 2)
        self.assertIn("code_verifier", self.http.calls[0][1])
        self.assertEqual(self.http.calls[1][1]["nonce"], self.http.nonce)

        old_session_id = next(iter(self.auth_store.sessions))
        second = self._login()
        self.assertEqual(second.status_code, 302)
        self.assertIn(old_session_id, self.auth_store.deleted_sessions)
        self.assertNotIn(old_session_id, self.auth_store.sessions)

    def test_state_mismatch_cancel_token_failure_and_replay_fail_closed(self):
        _response, query = self._start_login()
        mismatch = self.client.get("/auth/line/callback", query_string={"code": "x", "state": "wrong"})
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(self.http.calls, [])

        cancelled = self.client.get("/auth/line/callback", query_string={"error": "access_denied"})
        self.assertEqual(cancelled.status_code, 400)

        _response, query = self._start_login()
        self.http.token_status = 500
        failure = self.client.get("/auth/line/callback", query_string={"code": "x", "state": query["state"][0]})
        self.assertEqual(failure.status_code, 503)
        replay = self.client.get("/auth/line/callback", query_string={"code": "x", "state": query["state"][0]})
        self.assertEqual(replay.status_code, 400)

    def test_claim_validation_rejects_issuer_audience_expiry_nonce_and_subject(self):
        base = {
            "iss": "https://access.line.me", "aud": self.config.channel_id,
            "exp": int(NOW.timestamp()) + 60, "nonce": "nonce", "sub": USER_ID,
            "name": "使用者", "picture": "https://example.com/avatar.png",
        }
        cases = (
            {"iss": "https://evil.test"}, {"aud": "other"},
            {"exp": int(NOW.timestamp()) - 1}, {"nonce": "wrong"},
            {"sub": "attacker"}, {"picture": "javascript:alert(1)"},
        )
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    verify_line_claims({**base, **change}, self.config, "nonce", NOW)

    def test_private_state_and_watchlist_are_session_isolated_and_csrf_protected(self):
        self._login()
        state = self.client.get("/api/account/state")
        payload = state.get_json()
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.headers["Cache-Control"], "private, no-store")
        self.assertEqual(payload["user"]["display_name"], "測試使用者")

        missing_csrf = self.client.post("/api/account/watchlist", json={"action": "add", "code": "2330"})
        self.assertEqual(missing_csrf.status_code, 403)
        added = self.client.post(
            "/api/account/watchlist",
            json={"action": "add", "code": "2330", "line_user_id": "U" + "b" * 32},
            headers={"X-CSRF-Token": payload["csrf_token"]},
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(self.line_store.updated_user_ids, [USER_ID])
        self.assertEqual(self.line_store.users[USER_ID]["watchlist"][0]["code"], "2330")
        self.assertNotIn("U" + "b" * 32, self.line_store.users)

    def test_unauthenticated_private_routes_do_not_read_or_mutate_user_state(self):
        fresh_app = self.client.application.test_client()
        response = fresh_app.get("/api/account/state")
        mutation = fresh_app.post("/api/account/watchlist", json={"action": "add", "code": "2330"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(mutation.status_code, 401)
        self.assertEqual(self.line_store.updated_user_ids, [])

    def test_logout_requires_csrf_and_invalidates_server_session(self):
        self._login()
        payload = self.client.get("/api/account/state").get_json()
        session_id = next(iter(self.auth_store.sessions))

        self.assertEqual(self.client.post("/auth/logout").status_code, 403)
        response = self.client.post("/auth/logout", headers={"X-CSRF-Token": payload["csrf_token"]})
        self.assertEqual(response.status_code, 302)
        self.assertIn(session_id, self.auth_store.deleted_sessions)
        self.assertEqual(self.client.get("/api/account/state").status_code, 401)

    def test_missing_configuration_fails_closed_without_affecting_public_app(self):
        app = Flask("missing")
        register_auth_routes(
            app,
            config=LineLoginConfig("", "", "", "", cookie_secure=True),
            auth_store=lambda: None,
            line_store=lambda: None,
            search_stock=lambda _code: (None, None),
            http_post=self.http.post,
            now=lambda: NOW,
        )
        response = app.test_client().get("/auth/line/login")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.http.calls, [])

    def test_login_has_bounded_process_rate_limit(self):
        responses = [self.client.get("/auth/line/login") for _ in range(11)]

        self.assertTrue(all(response.status_code == 302 for response in responses[:10]))
        self.assertEqual(responses[10].status_code, 429)
        self.assertEqual(responses[10].headers["Retry-After"], "60")

    def test_line_user_id_is_redacted_from_log_text(self):
        self.assertEqual(redact_secrets(f"loaded user {USER_ID}"), "loaded user U********")


    def _register_trading(self, beta_users=None, builder=None):
        from stock_papi.web.routes.auth import register_auth_routes as _reg
        # Re-register trading routes on a fresh app with beta allowlist + fake builder.
        from flask import Flask as _Flask
        from pathlib import Path as _Path
        app = _Flask(__name__, template_folder=str(_Path(__file__).parents[1] / "templates"))
        app.config.update(TESTING=True)
        if beta_users is None:
            beta_users = frozenset({USER_ID})
        _reg(app, config=self.config, auth_store=lambda: self.auth_store,
             line_store=lambda: self.line_store, search_stock=lambda code: (code, "X"),
             http_post=self.http.post, now=lambda: NOW,
             trading_beta_users=beta_users, trade_plan_builder=builder)
        return app.test_client()

    def _login_client(self, client, sub=None):
        if sub is not None:
            self.http.claim_overrides["sub"] = sub
        else:
            self.http.claim_overrides.pop("sub", None)
        resp = client.get("/auth/line/login", query_string={"return_to": "/"})
        from urllib.parse import parse_qs as _pq, urlparse as _up
        query = _pq(_up(resp.headers["Location"]).query)
        self.http.nonce = query["nonce"][0]
        out = client.get("/auth/line/callback", query_string={
            "code": "authorization-code", "state": query["state"][0]})
        self.assertEqual(out.status_code, 302)
        # Extract session cookie + csrf for API calls.
        session = next(iter(self.auth_store.sessions.values()))
        return session

    def test_two_sessions_are_isolated(self):
        beta = frozenset({USER_ID, "U" + "b" * 32})
        client_a = self._register_trading(beta_users=beta)
        client_b = self._register_trading(beta_users=beta)
        # Two separate browsers log in as different users.
        self._login_client(client_a, sub=USER_ID)
        self._login_client(client_b, sub="U" + "b" * 32)
        # Each client reads its own assistant; B cannot see A's follows.
        import re as _re
        # Grab CSRF from store (last session is B's; find A's by user).
        sessions_by_user = {}
        for sid, sess in self.auth_store.sessions.items():
            sessions_by_user[sess["line_user_id"]] = sess
        csrf_a = sessions_by_user[USER_ID]["csrf_token"]
        # A follows someone via direct POST with its cookies (client_a jar holds A's session).
        resp = client_a.post("/api/account/trading", json={
            "action": "follow_subject", "subject_id": "alpha-subject",
            "request_id": "00000000-0000-4000-8000-000000000021"},
            headers={"X-CSRF-Token": csrf_a})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        # B reads its own state: must not contain A's follow.
        csrf_b = sessions_by_user["U" + "b" * 32]["csrf_token"]
        # client_b jar holds B's session (last login overwrote? separate jars, so ok).
        resp_b = client_b.get("/api/account/trading")
        self.assertEqual(resp_b.status_code, 200)
        assistant_b = resp_b.get_json()["assistant"]
        self.assertNotIn("alpha-subject", assistant_b.get("followed_subject_ids", []))

    def test_trading_requires_beta_and_csrf(self):
        client = self._register_trading(beta_users=frozenset())
        self._login_client(client, sub=USER_ID)
        session = next(iter(self.auth_store.sessions.values()))
        # Non-beta -> 403 even with valid CSRF.
        resp = client.post("/api/account/trading", json={
            "action": "set_preferences", "view_preference": "data",
            "request_id": "00000000-0000-4000-8000-000000000031"},
            headers={"X-CSRF-Token": session["csrf_token"]})
        self.assertEqual(resp.status_code, 403)
        # Beta but wrong CSRF -> 403.
        client2 = self._register_trading(beta_users=frozenset({USER_ID}))
        self._login_client(client2, sub=USER_ID)
        resp2 = client2.post("/api/account/trading", json={
            "action": "set_preferences", "view_preference": "data",
            "request_id": "00000000-0000-4000-8000-000000000032"},
            headers={"X-CSRF-Token": "wrong"})
        self.assertEqual(resp2.status_code, 403)

    def test_save_plan_rejects_forged_ids_and_stale_plan(self):
        import hashlib as _hl
        from datetime import datetime as _dt, timezone as _tz
        from stock_papi.services import trade_plans as _tp
        import tests.test_trade_plans as _tpt
        snap, cal = _tpt._snapshot()
        plan = _tp.build_trade_plan(snap, expected_session=snap["as_of"],
            generated_at=_dt(2026, 9, 3, 1, 0, tzinfo=_tz.utc), calendar=cal)
        def _builder(market, symbol, evidence):
            return plan
        client = self._register_trading(beta_users=frozenset({USER_ID}), builder=_builder)
        self._login_client(client, sub=USER_ID)
        session = next(iter(self.auth_store.sessions.values()))
        headers = {"X-CSRF-Token": session["csrf_token"]}
        # Forged user_id field is rejected as unknown field (400), not honored.
        resp = client.post("/api/account/trading", json={
            "action": "save_plan", "market": "US", "symbol": "INTC",
            "expected_plan_id": plan["plan_id"], "evidence_ids": [],
            "position_context": "unheld", "request_id": "00000000-0000-4000-8000-000000000041",
            "line_user_id": "U" + "e" * 32},
            headers=headers)
        self.assertEqual(resp.status_code, 400)
        # Stale plan id -> 409.
        resp = client.post("/api/account/trading", json={
            "action": "save_plan", "market": "US", "symbol": "INTC",
            "expected_plan_id": "tp_stale00000000000000000000000000", "evidence_ids": [],
            "position_context": "unheld", "request_id": "00000000-0000-4000-8000-000000000042"},
            headers=headers)
        self.assertEqual(resp.status_code, 409)
        # Oversize body -> 400.
        big = "x" * (17 * 1024)
        resp = client.post("/api/account/trading",
            data='{"action":"feedback","category":"general","helpful":"helpful","text":"' + big + '"}',
            content_type="application/json", headers=headers)
        self.assertIn(resp.status_code, (400, 413))


    def _register_with_hosts(self, hosts):
        from flask import Flask as _Flask
        from pathlib import Path as _Path
        app = _Flask(__name__, template_folder=str(_Path(__file__).parents[1] / "templates"))
        app.config.update(TESTING=True)
        register_auth_routes(
            app, config=self.config, auth_store=lambda: self.auth_store,
            line_store=lambda: self.line_store, search_stock=lambda code: (code, "X"),
            http_post=self.http.post, now=lambda: NOW,
            login_callback_hosts=hosts)
        return app.test_client()

    def test_allowlisted_host_uses_request_host_callback(self):
        client = self._register_with_hosts(frozenset({"localhost"}))
        response = client.get("/auth/line/login", query_string={"return_to": "/"})
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%2Fauth%2Fline%2Fcallback", location)
        from urllib.parse import parse_qs as _pq, urlparse as _up
        query = _pq(_up(location).query)
        self.http.nonce = query["nonce"][0]
        done = client.get("/auth/line/callback", query_string={
            "code": "authorization-code", "state": query["state"][0]})
        self.assertEqual(done.status_code, 302)

    def test_default_host_keeps_configured_callback(self):
        client = self._register_with_hosts(None)
        response = client.get("/auth/line/login", query_string={"return_to": "/"})
        self.assertEqual(response.status_code, 302)
        from urllib.parse import quote as _quote
        self.assertIn("redirect_uri=" + _quote(self.config.redirect_uri, safe=""), response.headers["Location"])

    def test_mid_flow_host_switch_fails_closed(self):
        from stock_papi.services.auth import LineLoginConfig as _Config
        other = _Config(channel_id="1234567890", channel_secret="channel-secret",
                        redirect_uri="http://127.0.0.1/auth/line/callback",
                        session_secret="s" * 32, cookie_secure=False)
        holder = {"hosts": None}
        from flask import Flask as _Flask
        from pathlib import Path as _Path
        app = _Flask(__name__, template_folder=str(_Path(__file__).parents[1] / "templates"))
        app.config.update(TESTING=True)
        register_auth_routes(
            app, config=other, auth_store=lambda: self.auth_store,
            line_store=lambda: self.line_store, search_stock=lambda code: (code, "X"),
            http_post=self.http.post, now=lambda: NOW,
            login_callback_hosts=lambda: holder["hosts"])
        client = app.test_client()
        started = client.get("/auth/line/login", query_string={"return_to": "/"})
        from urllib.parse import parse_qs as _pq, urlparse as _up
        query = _pq(_up(started.headers["Location"]).query)
        self.http.nonce = query["nonce"][0]
        holder["hosts"] = frozenset({"localhost"})
        failed = client.get("/auth/line/callback", query_string={
            "code": "authorization-code", "state": query["state"][0]})
        self.assertEqual(failed.status_code, 400)


if __name__ == "__main__":
    unittest.main()
