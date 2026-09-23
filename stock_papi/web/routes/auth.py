"""LINE Login、server-side session 與共用 LINE 使用者狀態路由。"""

import datetime
import re
import secrets
import threading
from collections import defaultdict, deque
from urllib.parse import urlencode, urlsplit

from flask import (
    jsonify, make_response, redirect, render_template, request, url_for,
)

from line_state import StateError, add_watch, remove_watch
from stock_papi.shared.validation import constant_time_equals
from stock_papi.services.auth import (
    create_pkce_pair,
    safe_return_path,
    sign_opaque_token,
    verify_line_claims,
    verify_opaque_token,
)


AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


def _private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _safe_json(response):
    try:
        value = response.json()
    except Exception as exc:
        raise ValueError("LINE response was not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("LINE response was invalid")
    return value


def _public_user(value):
    name = value.get("display_name") if isinstance(value, dict) else None
    if not isinstance(name, str) or not name.strip() or any(ord(char) < 32 for char in name):
        name = "LINE 使用者"
    picture = value.get("picture_url") if isinstance(value, dict) else None
    if picture:
        parsed = urlsplit(picture) if isinstance(picture, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            picture = None
    return {"display_name": name[:100], "picture_url": picture, "plan": "free"}


def register_auth_routes(
    app, *, config, auth_store, line_store, search_stock, http_post, now,
):
    login_attempts = defaultdict(deque)
    login_attempts_lock = threading.Lock()

    def login_rate_allowed():
        key = request.remote_addr or "unknown"
        cutoff = now().timestamp() - 60
        with login_attempts_lock:
            attempts = login_attempts[key]
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= 10:
                return False
            attempts.append(now().timestamp())
            return True

    def dependencies():
        store = auth_store()
        states = line_store()
        return (store, states) if config.configured and store is not None and states is not None else (None, None)

    def current_session(store):
        signed = request.cookies.get(config.session_cookie_name)
        session_id = verify_opaque_token(signed, config.session_secret)
        if not session_id:
            return None, None
        session = store.load_session(session_id, now())
        if not isinstance(session, dict):
            return None, None
        if re.fullmatch(r"U[0-9a-f]{32}", str(session.get("line_user_id") or "")) is None:
            return None, None
        if not isinstance(session.get("csrf_token"), str) or len(session["csrf_token"]) < 32:
            return None, None
        return session_id, session

    def csrf_matches(session):
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        return constant_time_equals(supplied, session["csrf_token"])

    def line_login():
        store, _states = dependencies()
        if store is None:
            return _private(make_response("LINE Login 尚未完成安全設定", 503))
        if not login_rate_allowed():
            response = _private(make_response("LINE Login 請求過於頻繁", 429))
            response.headers["Retry-After"] = "60"
            return response
        timestamp = now()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier, challenge = create_pkce_pair()
        return_to = safe_return_path(request.args.get("return_to", "/"))
        try:
            store.create_oauth_attempt(state, {
                "nonce": nonce,
                "code_verifier": verifier,
                "return_to": return_to,
                "redirect_uri": config.redirect_uri,
                "expires_at": timestamp + datetime.timedelta(seconds=config.oauth_ttl_seconds),
                "consumed_at": None,
            })
        except Exception:
            return _private(make_response("LINE Login 暫時無法使用", 503))
        location = AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": config.channel_id,
            "redirect_uri": config.redirect_uri,
            "state": state,
            "scope": "openid profile",
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        response = _private(redirect(location, code=302))
        response.set_cookie(
            config.oauth_cookie_name,
            sign_opaque_token(state, config.session_secret),
            max_age=config.oauth_ttl_seconds,
            secure=config.cookie_secure,
            httponly=True,
            samesite="Lax",
            path="/auth/line/callback",
        )
        return response

    def line_callback():
        store, _states = dependencies()
        if store is None:
            return _private(make_response("LINE Login 尚未完成安全設定", 503))
        if request.args.get("error"):
            response = _private(make_response("LINE Login 已取消", 400))
            response.delete_cookie(config.oauth_cookie_name, path="/auth/line/callback")
            return response
        state = request.args.get("state", "")
        code = request.args.get("code", "")
        cookie_state = verify_opaque_token(
            request.cookies.get(config.oauth_cookie_name), config.session_secret
        )
        if (
            not 20 <= len(state) <= 200
            or not 1 <= len(code) <= 2048
            or cookie_state is None
            or not constant_time_equals(state, cookie_state)
        ):
            return _private(make_response("LINE Login 驗證失敗", 400))
        try:
            attempt = store.consume_oauth_attempt(state, now())
        except Exception:
            return _private(make_response("LINE Login 暫時無法使用", 503))
        if not isinstance(attempt, dict) or attempt.get("redirect_uri") != config.redirect_uri:
            return _private(make_response("LINE Login 驗證失敗", 400))
        try:
            token_response = http_post(TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri,
                "client_id": config.channel_id,
                "client_secret": config.channel_secret,
                "code_verifier": attempt["code_verifier"],
            }, timeout=5)
            if token_response.status_code != 200:
                return _private(make_response("LINE Login 暫時無法完成", 503))
            id_token = _safe_json(token_response).get("id_token")
            if not isinstance(id_token, str) or not id_token:
                return _private(make_response("LINE Login 暫時無法完成", 503))
            verify_response = http_post(VERIFY_URL, data={
                "id_token": id_token,
                "client_id": config.channel_id,
                "nonce": attempt["nonce"],
            }, timeout=5)
            if verify_response.status_code != 200:
                return _private(make_response("LINE Login 身分驗證失敗", 400))
            profile = verify_line_claims(
                _safe_json(verify_response), config, attempt["nonce"], now()
            )
        except (KeyError, ValueError):
            return _private(make_response("LINE Login 身分驗證失敗", 400))
        except Exception:
            return _private(make_response("LINE Login 暫時無法完成", 503))

        old_session = verify_opaque_token(
            request.cookies.get(config.session_cookie_name), config.session_secret
        )
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expiration = now() + datetime.timedelta(seconds=config.session_ttl_seconds)
        try:
            if old_session:
                store.delete_session(old_session)
            store.upsert_user(profile["line_user_id"], profile)
            store.create_session(session_id, {
                "line_user_id": profile["line_user_id"],
                "csrf_token": csrf_token,
                "created_at": now(),
                "expires_at": expiration,
            })
        except Exception:
            return _private(make_response("LINE Login 暫時無法完成", 503))

        response = _private(redirect(safe_return_path(attempt.get("return_to")), code=302))
        response.set_cookie(
            config.session_cookie_name,
            sign_opaque_token(session_id, config.session_secret),
            max_age=config.session_ttl_seconds,
            secure=config.cookie_secure,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        response.delete_cookie(config.oauth_cookie_name, path="/auth/line/callback")
        return response

    def account_state():
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _session_id, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        try:
            user = store.get_user(session["line_user_id"])
            state, _version = states.load(session["line_user_id"])
        except Exception:
            return _private(jsonify({"error": "account unavailable"})), 503
        if not isinstance(user, dict):
            return _private(jsonify({"error": "account unavailable"})), 503
        payload = {
            "user": _public_user(user),
            "watchlist": [
                {"code": item["code"], "name": item["name"]}
                for item in state.get("watchlist", [])
                if isinstance(item, dict) and isinstance(item.get("code"), str) and isinstance(item.get("name"), str)
            ],
            "alerts": [
                {key: item.get(key) for key in ("id", "code", "name", "kind", "value")}
                for item in state.get("alerts", []) if isinstance(item, dict)
            ],
            "csrf_token": session["csrf_token"],
        }
        return _private(jsonify(payload))

    def account_page():
        return private_page("account.html", "/account")

    def account_watchlist_page():
        return private_page("account_watchlist.html", "/account/watchlist")

    def private_page(template, return_to):
        store, states = dependencies()
        if store is None:
            return _private(make_response("帳戶功能尚未完成安全設定", 503))
        try:
            _session_id, session = current_session(store)
        except Exception:
            return _private(make_response("帳戶功能暫時無法使用", 503))
        if session is None:
            return redirect(url_for("line_login", return_to=return_to), code=302)
        try:
            user = store.get_user(session["line_user_id"])
            state, _version = states.load(session["line_user_id"])
        except Exception:
            return _private(make_response("帳戶功能暫時無法使用", 503))
        response = make_response(render_template(
            template, user=_public_user(user or {}), state=state,
            csrf_token=session["csrf_token"]
        ))
        return _private(response)

    def mutate_watchlist():
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _session_id, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        if not csrf_matches(session):
            return _private(jsonify({"error": "CSRF validation failed"})), 403
        if not request.is_json:
            return _private(jsonify({"error": "JSON body required"})), 415
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            return _private(jsonify({"error": "invalid request"})), 400
        action = value.get("action")
        code = str(value.get("code") or "").upper()
        if action not in {"add", "remove"} or re.fullmatch(r"[A-Z0-9.]{1,10}", code) is None:
            return _private(jsonify({"error": "invalid request"})), 400
        try:
            if action == "add":
                resolved, name = search_stock(code)
                if resolved != code or not name:
                    return _private(jsonify({"error": "stock not found"})), 404
                state = states.update(
                    session["line_user_id"], lambda current: add_watch(current, code, name)
                )
            else:
                state = states.update(
                    session["line_user_id"], lambda current: remove_watch(current, code)
                )
        except StateError as exc:
            return _private(jsonify({"error": str(exc)})), 400
        except Exception:
            return _private(jsonify({"error": "watchlist unavailable"})), 503
        return _private(jsonify({
            "watchlist": [
                {"code": item["code"], "name": item["name"]}
                for item in state.get("watchlist", [])
            ]
        }))

    def logout():
        store, _states = dependencies()
        if store is None:
            return _private(make_response("帳戶功能尚未完成安全設定", 503))
        try:
            session_id, session = current_session(store)
        except Exception:
            return _private(make_response("帳戶功能暫時無法使用", 503))
        if session is None:
            return _private(make_response("需要登入", 401))
        if not csrf_matches(session):
            return _private(make_response("CSRF 驗證失敗", 403))
        try:
            store.delete_session(session_id)
        except Exception:
            return _private(make_response("登出暫時無法完成", 503))
        response = _private(redirect(url_for("dashboard_page") if "dashboard_page" in app.view_functions else "/", code=302))
        response.delete_cookie(config.session_cookie_name, path="/")
        return response

    app.add_url_rule("/auth/line/login", "line_login", line_login)
    app.add_url_rule("/auth/line/callback", "line_callback", line_callback)
    app.add_url_rule("/auth/logout", "auth_logout", logout, methods=["POST"])
    app.add_url_rule("/api/account/state", "account_state", account_state)
    app.add_url_rule("/api/account/watchlist", "account_watchlist_api", mutate_watchlist, methods=["POST"])
    app.add_url_rule("/account", "account_page", account_page)
    app.add_url_rule("/account/watchlist", "account_watchlist_page", account_watchlist_page)
