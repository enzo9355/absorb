"""LINE Login 的純函式、設定與 token 驗證邊界。"""

import base64
import datetime
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from stock_papi.shared.validation import constant_time_equals


@dataclass(frozen=True)
class LineLoginConfig:
    channel_id: str
    channel_secret: str
    redirect_uri: str
    session_secret: str
    cookie_secure: bool = True
    session_cookie_name: str = "stock_papi_session"
    oauth_cookie_name: str = "stock_papi_oauth"
    oauth_ttl_seconds: int = 600
    session_ttl_seconds: int = 7 * 24 * 60 * 60

    @classmethod
    def from_env(cls):
        secure = (os.getenv("AUTH_COOKIE_SECURE") or "true").strip().lower()
        return cls(
            channel_id=(os.getenv("LINE_LOGIN_CHANNEL_ID") or "").strip(),
            channel_secret=(os.getenv("LINE_LOGIN_CHANNEL_SECRET") or "").strip(),
            redirect_uri=(os.getenv("LINE_LOGIN_REDIRECT_URI") or "").strip(),
            session_secret=(os.getenv("SESSION_SECRET") or "").strip(),
            cookie_secure=secure not in {"0", "false", "no"},
        )

    @property
    def configured(self):
        if re.fullmatch(r"[0-9]{5,20}", self.channel_id) is None:
            return False
        if not self.channel_secret or len(self.session_secret.encode("utf-8")) < 32:
            return False
        parsed = urlsplit(self.redirect_uri)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        return bool(
            parsed.path
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
            and (
                (self.cookie_secure and parsed.scheme == "https")
                or (not self.cookie_secure and local_http)
            )
        )


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def safe_return_path(value):
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 2048:
        return "/"
    decoded = unquote(value)
    if decoded.startswith("//") or "\\" in decoded or any(ord(char) < 32 for char in decoded):
        return "/"
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return "/"
    return decoded


def sign_opaque_token(value, secret):
    if not isinstance(value, str) or not value:
        raise ValueError("opaque token is required")
    signature = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return f"{value}.{_b64url(signature)}"


def verify_opaque_token(value, secret):
    if not isinstance(value, str) or "." not in value:
        return None
    token, supplied = value.rsplit(".", 1)
    try:
        expected = sign_opaque_token(token, secret).rsplit(".", 1)[1]
    except ValueError:
        return None
    return token if constant_time_equals(supplied, expected) else None


def _https_picture(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("LINE picture URL is invalid")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("LINE picture URL must be HTTPS")
    return value


def verify_line_claims(claims, config, expected_nonce, now):
    """再次驗證官方 verify endpoint 回傳的 OIDC claims。"""
    if not isinstance(claims, dict):
        raise ValueError("LINE ID token claims are invalid")
    if claims.get("iss") != "https://access.line.me":
        raise ValueError("LINE issuer mismatch")
    audience = claims.get("aud")
    if audience != config.channel_id and not (
        isinstance(audience, list) and config.channel_id in audience
    ):
        raise ValueError("LINE audience mismatch")
    expiration = claims.get("exp")
    if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        raise ValueError("LINE token expiration is invalid")
    if expiration <= now.timestamp():
        raise ValueError("LINE ID token expired")
    nonce = claims.get("nonce")
    if not constant_time_equals(nonce, expected_nonce):
        raise ValueError("LINE nonce mismatch")
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or re.fullmatch(r"U[0-9a-f]{32}", user_id) is None:
        raise ValueError("LINE subject is invalid")
    name = claims.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(char) < 32 for char in name):
        raise ValueError("LINE display name is invalid")
    return {
        "line_user_id": user_id,
        "display_name": name.strip(),
        "picture_url": _https_picture(claims.get("picture")),
        "account_status": "active",
        "plan": "free",
        "schema_version": 1,
    }


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)
