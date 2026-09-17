"""Bounded, credential-free reads from the public FxTwitter timeline API."""

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from stock_papi.services.x_api import (
    POST_ID_RE, USERNAME_RE, XApiError, _iso, _json_transport, _normalise_time,
)


class FxTwitterClient:
    def __init__(self, *, transport=None):
        self._transport = transport or _json_transport

    def fetch_user_posts(self, username, *, start_time=None, end_time=None, max_pages=3):
        username = str(username or "").strip().lstrip("@").lower()
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("invalid X username")
        if type(max_pages) is not int or not 1 <= max_pages <= 10:
            raise ValueError("max_pages must be between 1 and 10")
        start, end = _normalise_time(start_time), _normalise_time(end_time)
        start = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        end = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
        if start and end and start >= end:
            raise ValueError("start_time must precede end_time")
        posts, seen_ids, seen_cursors = [], set(), set()
        skipped = {"reposts": 0, "unavailable": 0, "outside_window": 0, "duplicates": 0}
        user = {"username": username, "name": username, "id": ""}
        author_id = None
        cursor = None
        stop_reason, has_more = "page_limit", True
        for page in range(1, max_pages + 1):
            if page > 1 and self._transport is _json_transport:
                time.sleep(1)
            params = {"count": 100}
            if cursor:
                params["cursor"] = cursor
            url = f"https://api.fxtwitter.com/2/profile/{username}/statuses?{urlencode(params)}"
            status, body = self._transport(url, {"Accept": "application/json", "User-Agent": "ABSORB-research/1.0"}, 20)
            if status != 200:
                raise XApiError("FxTwitter request failed", status_code=status)
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError, TypeError) as exc:
                raise XApiError("FxTwitter returned invalid JSON") from exc
            if not isinstance(payload, dict) or payload.get("code") != 200 or not isinstance(payload.get("results"), list):
                raise XApiError("FxTwitter returned invalid timeline data")
            for raw in payload["results"]:
                if not isinstance(raw, dict):
                    raise XApiError("FxTwitter returned invalid post")
                if raw.get("type") == "tombstone":
                    skipped["unavailable"] += 1
                    continue
                if raw.get("type") != "status":
                    raise XApiError("FxTwitter returned unsupported post type")
                author = raw.get("author")
                if not isinstance(author, dict) or not isinstance(author.get("screen_name"), str) or not USERNAME_RE.fullmatch(author["screen_name"]):
                    raise XApiError("FxTwitter post has no valid author")
                if not isinstance(author.get("id"), str) or not POST_ID_RE.fullmatch(author["id"]):
                    raise XApiError("FxTwitter post has no valid author id")
                if author["screen_name"].lower() != username or any(raw.get(k) for k in ("reposted_by", "retweeted_status", "repost", "is_retweet")):
                    skipped["reposts"] += 1
                    continue
                if author_id is not None and author["id"] != author_id:
                    raise XApiError("FxTwitter timeline contains conflicting author ids")
                author_id = author["id"]
                post_id, text = raw.get("id"), raw.get("text")
                if not isinstance(post_id, str) or not POST_ID_RE.fullmatch(post_id) or not isinstance(text, str) or not text.strip():
                    raise XApiError("FxTwitter post has invalid id or text")
                try:
                    date = raw["created_at"]
                    try:
                        published = datetime.fromisoformat(date.replace("Z", "+00:00"))
                    except ValueError:
                        published = parsedate_to_datetime(date)
                    if published.tzinfo is None:
                        raise ValueError("missing timezone")
                except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
                    raise XApiError("FxTwitter post has invalid date") from exc
                if (start and published < start) or (end and published >= end):
                    skipped["outside_window"] += 1
                    continue
                if post_id in seen_ids:
                    skipped["duplicates"] += 1
                    continue
                seen_ids.add(post_id)
                user.update(name=str(author.get("name") or username), id=str(author.get("id") or ""))
                posts.append({"id": post_id, "text": text, "created_at": _iso(published), "author_id": user["id"], "source_payload": raw})
            cursors = payload.get("cursor", {})
            if not isinstance(cursors, dict):
                raise XApiError("FxTwitter returned invalid cursor")
            cursor = cursors.get("bottom")
            if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
                raise XApiError("FxTwitter returned invalid cursor")
            if not cursor:
                has_more, stop_reason = False, "exhausted"
                break
            if cursor in seen_cursors:
                stop_reason = "repeated_cursor"
                break
            seen_cursors.add(cursor)
        return {
            "user": user, "posts": posts, "pages_fetched": page,
            "has_more": has_more, "stop_reason": stop_reason, "skipped": skipped,
            "fetched_at": _iso(datetime.now(timezone.utc)),
            "acquisition_method": "fx_twitter_user_timeline",
        }
