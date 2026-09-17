"""Small, read-only X API v2 client for reviewed opinion candidates.

This module never promotes API responses into the public opinion catalog.  It
only fetches a bounded user timeline and converts it into pending v2 rows for
manual review.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from stock_papi.services.public_opinions import parse_opinion_markers


DEFAULT_BASE_URL = "https://api.x.com/2"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_PAGES = 10
MAX_PAGE_SIZE = 100
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
POST_ID_RE = re.compile(r"^[0-9]+$")
_TIMELINE_FIELDS = (
    "id,text,created_at,author_id,conversation_id,lang,public_metrics,"
    "referenced_tweets,edit_history_tweet_ids"
)


class XApiError(RuntimeError):
    """A bounded, safe-to-display X API failure."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class XApiConfig:
    bearer_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_pages: int = DEFAULT_MAX_PAGES

    @classmethod
    def from_environment(cls) -> "XApiConfig":
        token = (os.getenv("X_API_BEARER_TOKEN") or "").strip()
        base_url = (os.getenv("X_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        try:
            timeout = float(os.getenv("X_API_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        try:
            max_pages = int(os.getenv("X_API_MAX_PAGES") or DEFAULT_MAX_PAGES)
        except ValueError:
            max_pages = DEFAULT_MAX_PAGES
        return cls(
            bearer_token=token,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=max(1.0, min(timeout, 60.0)),
            max_pages=max(1, min(max_pages, 50)),
        )


def _json_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise XApiError("X source response exceeds size limit")
            return int(response.status), body
    except HTTPError as exc:
        body = exc.read(4096)
        detail = "HTTP request failed"
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                detail = str(errors[0].get("detail") or errors[0].get("title") or detail)
        except (UnicodeError, ValueError, TypeError):
            pass
        raise XApiError(detail[:240], status_code=int(exc.code)) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise XApiError("X API network request failed") from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_time(value: str | datetime | None, *, end_of_day: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("time must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("time must include a timezone")
    if end_of_day and len(str(value).strip()) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return _iso(parsed)


def _canonical_profile(username: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("invalid X username")
    return f"https://x.com/{username}"


def canonical_post_url(username: str, post_id: str) -> str:
    """Return a canonical, query-free public URL for one X post."""

    if not USERNAME_RE.fullmatch(str(username or "")):
        raise ValueError("invalid X username")
    if not POST_ID_RE.fullmatch(str(post_id or "")):
        raise ValueError("invalid X post id")
    return f"https://x.com/{username}/status/{post_id}"


def _source_hash(post: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(post), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class XApiClient:
    """Bounded X API v2 client with injectable transport for tests."""

    def __init__(
        self,
        config: XApiConfig,
        *,
        transport: Callable[[str, Mapping[str, str], float], tuple[int, bytes]] | None = None,
    ):
        self.config = config
        self._transport = transport or _json_transport
        if not config.bearer_token:
            raise XApiError("X_API_BEARER_TOKEN is not configured")
        parts = urlsplit(config.base_url)
        if (
            parts.scheme != "https"
            or parts.netloc.lower() != "api.x.com"
            or parts.path.rstrip("/") != "/2"
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise XApiError("X API base URL must be https://api.x.com/2")

    def _request(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith("/") or ".." in path.split("/"):
            raise XApiError("invalid X API path")
        url = f"{self.config.base_url}{path}"
        query = [(str(key), str(value)) for key, value in (params or {}).items() if value not in (None, "")]
        if query:
            url = f"{url}?{urlencode(query)}"
        status, body = self._transport(
            url,
            {
                "Authorization": f"Bearer {self.config.bearer_token}",
                "Accept": "application/json",
                "User-Agent": "ABSORB-research/1.0",
            },
            self.config.timeout_seconds,
        )
        if status < 200 or status >= 300:
            raise XApiError("X API returned an unsuccessful response", status_code=status)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError, AttributeError) as exc:
            raise XApiError("X API returned invalid JSON", status_code=status) from exc
        if not isinstance(payload, dict):
            raise XApiError("X API response must be an object", status_code=status)
        errors = payload.get("errors")
        if errors:
            raise XApiError("X API response contains errors", status_code=status)
        return payload

    def lookup_user(self, username: str) -> dict[str, Any]:
        username = str(username or "").strip().lstrip("@").lower()
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("invalid X username")
        payload = self._request(
            f"/users/by/username/{quote(username, safe='')}",
            {"user.fields": "id,name,username,description,public_metrics,verified"},
        )
        user = payload.get("data")
        if (
            not isinstance(user, dict)
            or not POST_ID_RE.fullmatch(str(user.get("id") or "").strip())
        ):
            raise XApiError("X user was not found")
        return user

    def fetch_user_posts(
        self,
        username: str,
        *,
        start_time: str | datetime | None = None,
        end_time: str | datetime | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any]:
        pages = max_pages if max_pages is not None else self.config.max_pages
        if not isinstance(pages, int) or pages < 1 or pages > 50:
            raise ValueError("max_pages must be between 1 and 50")
        start = _normalise_time(start_time)
        end = _normalise_time(end_time, end_of_day=True)
        user = self.lookup_user(username)
        posts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        next_token: str | None = None
        page_count = 0
        while page_count < pages:
            page_count += 1
            payload = self._request(
                f"/users/{quote(str(user['id']), safe='')}/tweets",
                {
                    "max_results": MAX_PAGE_SIZE,
                    "exclude": "retweets,replies",
                    "tweet.fields": _TIMELINE_FIELDS,
                    "expansions": "author_id",
                    "user.fields": "id,name,username,description,public_metrics,verified",
                    "start_time": start,
                    "end_time": end,
                    "pagination_token": next_token,
                },
            )
            data = payload.get("data") or []
            if not isinstance(data, list):
                raise XApiError("X timeline data must be a list")
            for item in data:
                if not isinstance(item, dict):
                    continue
                post_id = str(item.get("id") or "").strip()
                if post_id and post_id not in seen_ids:
                    seen_ids.add(post_id)
                    posts.append(dict(item))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            candidate_token = str(meta.get("next_token") or "").strip()
            if not candidate_token or candidate_token in seen_tokens:
                break
            seen_tokens.add(candidate_token)
            next_token = candidate_token
        return {
            "user": dict(user),
            "posts": posts,
            "pages_fetched": page_count,
            "has_more": bool(next_token and page_count >= pages),
            "fetched_at": _iso(_utc_now()),
        }


def build_pending_candidate(
    result: Mapping[str, Any],
    *,
    creator_id: str,
    creator_name: str | None = None,
    market: str | None = None,
    symbol: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Convert API posts to a v2 candidate catalog; never mark rows confirmed."""

    user = result.get("user") if isinstance(result.get("user"), dict) else {}
    username = str(user.get("username") or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("result user has no valid username")
    if not str(creator_id or "").strip():
        raise ValueError("creator_id is required")
    captured_at = now or _utc_now()
    captured = _iso(captured_at)
    method = result.get("acquisition_method", "x_api_v2_user_timeline")
    if method not in {"x_api_v2_user_timeline", "fx_twitter_user_timeline"}:
        raise ValueError("unsupported acquisition method")
    free_source = method == "fx_twitter_user_timeline"
    catalog_id = "public-opinions-fxtwitter-candidate" if free_source else "public-opinions-x-api-candidate"
    catalog_version = f"{catalog_id}-{captured[:10]}"
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for post in result.get("posts") or []:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or "").strip()
        text = str(post.get("text") or "").strip()
        if not POST_ID_RE.fullmatch(post_id) or not text or post_id in seen_ids:
            continue
        seen_ids.add(post_id)
        published_at = str(post.get("created_at") or "").strip()
        if not published_at:
            continue
        try:
            parsed_published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed_published.tzinfo is None or parsed_published.utcoffset() is None:
            continue
        parsed = parse_opinion_markers({"text": text})
        source_url = canonical_post_url(username, post_id)
        stance = parsed.get("stance") or "unclear"
        direction = {"bullish": "long", "bearish": "short"}.get(stance, "hold")
        rows.append(
            {
                "id": f"x-{post_id}",
                "opinion_id": f"x:{post_id}",
                "creator_id": creator_id,
                "source_url": source_url,
                "source_kind": "x_post",
                "source_platform": "X",
                "acquisition_method": method,
                "origin_group_id": f"x:{post.get('conversation_id') or post_id}",
                "continuation_of": "",
                "withdraws_id": "",
                "supersedes_id": "",
                "market": str(market or "").upper(),
                "symbol": str(symbol or "").upper(),
                "security_status": "pending_review" if market and symbol else "unmapped",
                "published_at": _iso(parsed_published),
                "first_seen_at": captured,
                "reviewed_at": captured,
                "review_status": "pending_review",
                "source_status": "available",
                "content_type": parsed.get("content_type") or "original_opinion",
                "stance": stance,
                "recommendation_kind": parsed.get("recommendation_kind") or "mention",
                "horizon": parsed.get("horizon") or "unspecified",
                "conditions": parsed.get("conditions") or [],
                "direction": direction,
                "text": text,
                "raw_payload_sha256": _source_hash(post),
            }
        )
    created_dates = [row["published_at"] for row in rows]
    reviewed_through = max(created_dates, default=None)
    coverage = {
        "creator_id": creator_id,
        "source": method,
        "checked_at": captured,
        "reviewed_through": reviewed_through or captured,
        "catalog_version": catalog_version,
        "canonical_profile_url": _canonical_profile(username),
        "identity_evidence": [_canonical_profile(username)],
        "post_permalink_status": "available",
        "sample_start": min(created_dates, default=captured)[:10],
        "sample_end": max(created_dates, default=captured)[:10],
        "verified_post_count": 0,
        "acquisition_method": method,
        "rights_note": (
            "Fetched through third-party FxTwitter without credentials; access does not grant republication rights. Human review required."
            if free_source else "Fetched through the official X API; every row requires human review before promotion."
        ),
        "last_success_at": captured,
        "gaps": [
            "API candidates are pending human identity, market and stance review.",
            "No row is eligible for confirmed consensus until review_status is changed explicitly.",
            "Timeline completeness is not guaranteed; inspect fetch_meta.has_more and skipped counts.",
        ],
        "status": "pending_review",
        "reviewer": "fx_twitter_connector" if free_source else "x_api_connector",
    }
    creator = {
        "id": creator_id,
        "name": creator_name or str(user.get("name") or username),
        "platform": "X",
        "handle": username,
        "canonical_profile_url": _canonical_profile(username),
        "identity_status": "pending_review",
        "source_status": "available",
        "description": "X post candidate feed; requires manual review before public promotion.",
    }
    return {
        "schema_version": 2,
        "catalog_id": catalog_id,
        "catalog_version": catalog_version,
        "generated_at": captured,
        "creators": [creator],
        "coverage": [coverage],
        "opinions": rows,
        "outcomes": [],
        "fetch_meta": {
            "username": username,
            "user_id": str(user.get("id") or ""),
            "pages_fetched": int(result.get("pages_fetched") or 0),
            "fetched_at": str(result.get("fetched_at") or captured),
            "has_more": bool(result.get("has_more")),
            "acquisition_method": method,
            "stop_reason": result.get("stop_reason"),
            "skipped": result.get("skipped", {}),
        },
    }
