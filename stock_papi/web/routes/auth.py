"""LINE Login、server-side session 與共用 LINE 使用者狀態路由。"""

import datetime
import hmac
import logging
import re
import secrets
import threading
from collections import defaultdict, deque
from urllib.parse import urlencode, urlsplit

from flask import (
    jsonify, make_response, redirect, render_template, request, url_for,
)

from line_state import StateError, add_watch, remove_watch
from stock_papi.services.auth import (
    create_pkce_pair,
    safe_return_path,
    sign_opaque_token,
    verify_line_claims,
    verify_opaque_token,
)
from stock_papi.services.company_events import build_watchlist_summary


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
    load_events=None, load_events_status=None, stock_observation=None,
    trading_beta_users=None, trade_plan_builder=None,
    login_callback_hosts=None,
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
        return isinstance(supplied, str) and hmac.compare_digest(supplied, session["csrf_token"])

    def private_watchlist_summary(state):
        if callable(load_events_status):
            try:
                events, event_status = load_events_status()
                if event_status == "unavailable":
                    raise ValueError("event reader unavailable")
            except Exception:
                return {
                    "status": "unavailable",
                    "reason": "事件資料尚未更新，稍後再試",
                    "as_of": None,
                    "changed": [],
                    "new_events": [],
                    "upcoming_events": [],
                    "all": [],
                }
            if not isinstance(events, list):
                return {
                    "status": "unavailable",
                    "reason": "事件資料尚未更新，稍後再試",
                    "as_of": None,
                    "changed": [],
                    "new_events": [],
                    "upcoming_events": [],
                    "all": [],
                }
            try:
                return build_watchlist_summary(
                    state.get("watchlist", []) if isinstance(state, dict) else [],
                    events,
                    observation_for=stock_observation,
                    as_of=now().date(),
                    event_status=event_status,
                )
            except Exception:
                return {
                    "status": "unavailable",
                    "reason": "事件資料尚未更新，稍後再試",
                    "as_of": None,
                    "changed": [],
                    "new_events": [],
                    "upcoming_events": [],
                    "all": [],
                }
        if not callable(load_events):
            return {
                "status": "unavailable",
                "reason": "事件資料 reader 尚未接入",
                "as_of": None,
                "changed": [],
                "new_events": [],
                "upcoming_events": [],
                "all": [],
            }
        try:
            events = load_events()
            if not isinstance(events, list):
                raise ValueError("event reader returned invalid data")
            return build_watchlist_summary(
                state.get("watchlist", []) if isinstance(state, dict) else [],
                events,
                observation_for=stock_observation,
                as_of=now().date(),
            )
        except Exception:
            return {
                "status": "unavailable",
                "reason": "事件資料尚未更新，稍後再試",
                "as_of": None,
                "changed": [],
                "new_events": [],
                "upcoming_events": [],
                "all": [],
            }

    def _callback_hosts():
        try:
            hosts = login_callback_hosts() if callable(login_callback_hosts) else login_callback_hosts
        except Exception:
            return frozenset()
        if isinstance(hosts, (set, frozenset)):
            return frozenset(str(item).strip().lower() for item in hosts if str(item).strip())
        return frozenset()

    def _callback_redirect_uri():
        """redirect_uri for this request's host if allowlisted, else configured.

        Default (empty allowlist) preserves existing behavior exactly. The
        allowlist is server-side config, never user input; callback and token
        exchange both pin the stored value, so a mid-flow host switch fails
        closed with the same 400.
        """
        try:
            host = (urlsplit(request.host_url).hostname or "").lower()
        except Exception:
            return config.redirect_uri
        if host and host in _callback_hosts():
            forwarded = (request.headers.get("X-Forwarded-Proto", "") or "").lower().split(",")[0].strip()
            secure = bool(request.is_secure or forwarded == "https"
                          or host in {"localhost", "127.0.0.1"})
            if secure:
                scheme = "https" if host not in {"localhost", "127.0.0.1"} else request.scheme
                return f"{scheme}://{host}/auth/line/callback"
        return config.redirect_uri

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
        redirect_uri = _callback_redirect_uri()
        try:
            store.create_oauth_attempt(state, {
                "nonce": nonce,
                "code_verifier": verifier,
                "return_to": return_to,
                "redirect_uri": redirect_uri,
                "expires_at": timestamp + datetime.timedelta(seconds=config.oauth_ttl_seconds),
                "consumed_at": None,
            })
        except Exception:
            return _private(make_response("LINE Login 暫時無法使用", 503))
        location = AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": config.channel_id,
            "redirect_uri": redirect_uri,
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
            or not hmac.compare_digest(state, cookie_state)
        ):
            return _private(make_response("LINE Login 驗證失敗", 400))
        try:
            attempt = store.consume_oauth_attempt(state, now())
        except Exception:
            return _private(make_response("LINE Login 暫時無法使用", 503))
        if not isinstance(attempt, dict) or attempt.get("redirect_uri") != _callback_redirect_uri():
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
            # Diagnosis-only: status code without bodies, params, or secrets.
            logging.getLogger("auth").warning(
                "line_token_status=%s", getattr(token_response, "status_code", "unknown"))
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
            logging.getLogger("auth").warning(
                "line_verify_status=%s", getattr(verify_response, "status_code", "unknown"))
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
            "watchlist_summary": private_watchlist_summary(state),
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
        context = {
            "user": _public_user(user or {}),
            "state": state,
            "csrf_token": session["csrf_token"],
        }
        if template == "account_watchlist.html":
            context["watchlist_summary"] = private_watchlist_summary(state)
        response = make_response(render_template(template, **context))
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

    def _trading_beta_set():
        try:
            users = trading_beta_users() if callable(trading_beta_users) else trading_beta_users
        except Exception:
            return frozenset()
        if isinstance(users, (set, frozenset)):
            return frozenset(str(v) for v in users)
        return frozenset()

    def _trading_principal(session):
        try:
            from stock_papi.config.capabilities import conditional_advice_allowed as _allowed
        except Exception:
            return None, False
        user_id = str(session.get("line_user_id") or "")
        if not user_id:
            return None, False
        allowed = bool(_allowed(f"line:{user_id}", _trading_beta_set()))
        return user_id, allowed

    def _trading_body():
        try:
            length = request.content_length
        except Exception:
            length = None
        if length is not None and length > 16 * 1024:
            return None, (_private(jsonify({"error": "body too large"})), 400)
        if not request.is_json:
            return None, (_private(jsonify({"error": "JSON body required"})), 400)
        try:
            raw = request.get_data(cache=True) or b""
        except Exception:
            raw = b""
        if len(raw) > 16 * 1024:
            return None, (_private(jsonify({"error": "body too large"})), 400)
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            return None, (_private(jsonify({"error": "invalid request"})), 400)
        return value, None

    def trading_page():
        store, states = dependencies()
        if store is None:
            return _private(make_response("帳戶功能尚未完成安全設定", 503))
        try:
            _sid, session = current_session(store)
        except Exception:
            return _private(make_response("帳戶功能暫時無法使用", 503))
        if session is None:
            return redirect(url_for("line_login", return_to="/account/trading"), code=302)
        _user_id, allowed = _trading_principal(session)
        if not allowed:
            response = make_response(render_template("account_trading.html",
                csrf_token=session["csrf_token"], trading_locked=True))
            response.status_code = 403
            return _private(response)
        try:
            user = store.get_user(session["line_user_id"])
        except Exception:
            user = {}
        from line_state import empty_assistant as _empty_assistant
        response = make_response(render_template("account_trading.html",
            user=_public_user(user or {}), csrf_token=session["csrf_token"],
            trading_locked=False))
        return _private(response)

    def trading_api():
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _sid, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        user_id, allowed = _trading_principal(session)
        if not allowed:
            return _private(jsonify({"error": "trading beta not enabled"})), 403
        try:
            state, _version = states.load(user_id)
        except Exception:
            return _private(jsonify({"error": "account unavailable"})), 503
        assistant = state.get("assistant") if isinstance(state, dict) else None
        if assistant is None:
            try:
                from line_state import empty_assistant as _empty_assistant
                assistant = _empty_assistant()
            except Exception:
                assistant = None
        return _private(jsonify({"assistant": assistant}))

    def trading_export():
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _sid, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        user_id, allowed = _trading_principal(session)
        if not allowed:
            return _private(jsonify({"error": "trading beta not enabled"})), 403
        try:
            state, _version = states.load(user_id)
        except Exception:
            return _private(jsonify({"error": "account unavailable"})), 503
        assistant = state.get("assistant") if isinstance(state, dict) else {}
        payload = {"assistant": assistant}
        text = __import__("json").dumps(payload, ensure_ascii=False)
        for forbidden in ("access_token", "id_token", "bucket", "gcs", "service_account"):
            if forbidden in text.lower():
                pass
        response = make_response(__import__("json").dumps(
            {"saved_plans": (assistant or {}).get("saved_plans", []),
             "events": (assistant or {}).get("events", []),
             "feedback": (assistant or {}).get("feedback", []),
             "view_preference": (assistant or {}).get("view_preference"),
             "followed_subject_ids": (assistant or {}).get("followed_subject_ids", []),
             "followed_creator_ids": (assistant or {}).get("followed_creator_ids", []),
             "line_notifications_enabled": (assistant or {}).get("line_notifications_enabled", False)},
            ensure_ascii=False))
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=trading-export.json"
        return _private(response)

    def trading_mutate():
        from line_state import StateError as _StateError
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _sid, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        if not csrf_matches(session):
            return _private(jsonify({"error": "CSRF validation failed"})), 403
        user_id, allowed = _trading_principal(session)
        if not allowed:
            return _private(jsonify({"error": "trading beta not enabled"})), 403
        body, error = _trading_body()
        if error:
            return error
        # Strict unknown-field rejection is enforced inside apply_assistant_command;
        # pre-check non-finite numbers here for clear 400s.
        import math as _math
        def _has_nonfinite(value):
            if isinstance(value, bool):
                return False
            if isinstance(value, (int, float)):
                return not _math.isfinite(float(value))
            if isinstance(value, list):
                return any(_has_nonfinite(v) for v in value)
            if isinstance(value, dict):
                return any(_has_nonfinite(v) for v in value.values())
            return False
        if _has_nonfinite(body):
            return _private(jsonify({"error": "non-finite number"})), 400
        action = body.get("action")
        verified_plan = None
        if action == "save_plan":
            builder_fn = trade_plan_builder
            if builder_fn is None or not callable(builder_fn):
                return _private(jsonify({"error": "plan source unavailable"})), 503
            try:
                verified_plan = builder_fn(str(body.get("market") or ""),
                                           str(body.get("symbol") or ""),
                                           list(body.get("evidence_ids") or []))
            except Exception:
                return _private(jsonify({"error": "plan source unavailable"})), 503
            if not isinstance(verified_plan, dict):
                return _private(jsonify({"error": "plan source unavailable"})), 503
        try:
            from stock_papi.services.trade_plans import apply_assistant_command as _apply
            state = states.update(
                user_id,
                lambda current: _apply(current, body, now=now(), verified_plan=verified_plan),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "stale_plan":
                return _private(jsonify({"error": "stale_plan"})), 409
            if message in {"assistant_capacity_reached", "saved_plan_too_large",
                           "event_too_large", "assistant_too_large"}:
                return _private(jsonify({"error": "assistant_capacity_reached"})), 409
            if message in {"assistant_corrupted"}:
                return _private(jsonify({"error": "assistant unavailable"})), 503
            return _private(jsonify({"error": "invalid request"})), 400
        except _StateError as exc:
            return _private(jsonify({"error": str(exc)})), 400
        except Exception:
            return _private(jsonify({"error": "account unavailable"})), 503
        return _private(jsonify({"assistant": state.get("assistant")}))

    def trade_plan_preview(market, symbol):
        store, states = dependencies()
        if store is None:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        try:
            _sid, session = current_session(store)
        except Exception:
            return _private(jsonify({"error": "authentication unavailable"})), 503
        if session is None:
            return _private(jsonify({"error": "authentication required"})), 401
        if not csrf_matches(session):
            # GET preview uses session cookie; CSRF not required for safe reads.
            pass
        user_id, allowed = _trading_principal(session)
        if not allowed:
            return _private(jsonify({"error": "trading beta not enabled"})), 403
        builder_fn = trade_plan_builder
        if builder_fn is None or not callable(builder_fn):
            return _private(jsonify({"error": "plan source unavailable"})), 503
        try:
            plan = builder_fn(str(market or "").upper(), str(symbol or "").upper(), [])
        except Exception:
            return _private(jsonify({"error": "plan source unavailable"})), 503
        if not isinstance(plan, dict):
            return _private(jsonify({"error": "plan source unavailable"})), 503
        safe = {key: plan.get(key) for key in (
            "schema_version", "plan_id", "policy_version", "market", "symbol",
            "instrument_type", "data_as_of", "generated_at", "available_at",
            "eligible_session", "expires_session", "action", "conditions",
            "supporting_evidence", "opposing_evidence", "limitations",
            "external_evidence_ids", "rsi_method", "volume_method",
            "params", "unheld_guidance", "held_guidance")}
        safe["source_hash"] = plan.get("source_snapshot_sha256")
        return _private(jsonify({"plan": safe}))

    app.add_url_rule("/auth/line/login", "line_login", line_login)
    app.add_url_rule("/auth/line/callback", "line_callback", line_callback)
    app.add_url_rule("/auth/logout", "auth_logout", logout, methods=["POST"])
    app.add_url_rule("/api/account/state", "account_state", account_state)
    app.add_url_rule("/api/account/watchlist", "account_watchlist_api", mutate_watchlist, methods=["POST"])
    app.add_url_rule("/account", "account_page", account_page)
    app.add_url_rule("/account/watchlist", "account_watchlist_page", account_watchlist_page)
    app.add_url_rule("/account/trading", "account_trading_page", trading_page)
    app.add_url_rule("/api/account/trading", "account_trading_api", trading_api)
    app.add_url_rule("/api/account/trading", "account_trading_mutate", trading_mutate, methods=["POST"])
    app.add_url_rule("/api/account/trading/export", "account_trading_export", trading_export)
    app.add_url_rule("/api/account/trade-plan/<market>/<symbol>", "account_trade_plan_preview", trade_plan_preview)
