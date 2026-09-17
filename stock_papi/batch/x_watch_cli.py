"""One free polling pass; Windows Task Scheduler supplies the five-minute cadence."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_papi.batch.x_opinions_cli import _write_json
from stock_papi.services.fx_twitter import FxTwitterClient
from stock_papi.services.x_api import POST_ID_RE, XApiError, build_pending_candidate


SOURCES = {"unusual_whales": "unusual-whales", "aleabitoreddit": "candidate_serenity",
           "michaelsikand": "michael-sikand"}
ROOT = Path(__file__).resolve().parents[2] / "data" / "research"
INTERVAL_SECONDS = 300


def _read(path):
    if not path.exists():
        return {}
    if path.stat().st_size > 2_000_000:
        raise ValueError("watch input exceeds size limit")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("watch input must be an object")
    return document


def _archive(root, handle, creator_id, row):
    post_id = str(row.get("opinion_id", "")).removeprefix("x:")
    if (not POST_ID_RE.fullmatch(post_id) or row.get("creator_id") != creator_id
            or row.get("review_status") != "pending_review" or not isinstance(row.get("text"), str)):
        raise ValueError("invalid candidate identity or review state")
    path = root / "x-history" / handle / (post_id + ".json")
    original = _read(path)
    if original:
        if original.get("creator_id") != creator_id or original.get("opinion_id") != row["opinion_id"]:
            raise ValueError("archive identity mismatch")
        row["first_seen_at"] = original["first_seen_at"]
        # Metrics change every poll; only changed text creates an additional local version.
        if original["text"] != row["text"]:
            digest = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
            revision = path.with_name(f"{post_id}-{digest}.json")
            if not revision.exists():
                _write_json(revision, row)
        return False
    _write_json(path, row)
    return True


def run_once(root=ROOT, *, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    stamp = now.isoformat().replace("+00:00", "Z")
    status_path = root / "x-watch-status.json"
    state = _read(status_path)
    accounts = state.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        raise ValueError("invalid watch account state")
    state.update(schema_version=1, checked_at=stamp, interval_seconds=INTERVAL_SECONDS)
    client = FxTwitterClient()
    for handle, creator_id in SOURCES.items():
        health = accounts.setdefault(handle, {})
        if health.get("retry_after") and now < datetime.fromisoformat(health["retry_after"].replace("Z", "+00:00")):
            continue
        health.update(last_attempt_at=stamp, new_posts=0)
        try:
            path = root / "x-candidates" / (handle + ".json")
            previous = _read(path)
            if previous and (previous.get("catalog_id") != "public-opinions-fxtwitter-candidate"
                             or not isinstance(previous.get("opinions"), list)):
                raise ValueError("invalid previous candidate; refusing replacement")
            previous_meta = previous.get("fetch_meta", {})
            if previous and previous_meta.get("username") != handle:
                raise ValueError("previous candidate account mismatch")
            for row in previous.get("opinions", []):
                _archive(root, handle, creator_id, row)
            result = client.fetch_user_posts(handle, max_pages=3)
            old_id, new_id = previous_meta.get("user_id"), result["user"].get("id")
            if old_id and new_id and old_id != new_id:
                raise ValueError("account author ID changed; review required")
            candidate = build_pending_candidate(result, creator_id=creator_id, now=now)
            # Retain the account binding even when the upstream returns an empty timeline.
            candidate["fetch_meta"]["user_id"] = new_id or old_id or ""
            new_posts = sum(_archive(root, handle, creator_id, row) for row in candidate["opinions"])
            _write_json(path, candidate)
            health.update(status="ok", last_success_at=stamp, failures=0, retry_after=None,
                          new_posts=new_posts, fetched_posts=len(candidate["opinions"]),
                          has_more=candidate["fetch_meta"]["has_more"], error=None)
        except (XApiError, OSError, ValueError, KeyError, TypeError) as exc:
            failures = int(health.get("failures", 0)) + 1
            delay = min(3600, INTERVAL_SECONDS * 2 ** min(failures - 1, 4))
            health.update(status="error", failures=failures, error=str(exc)[:400],
                          retry_after=(now + timedelta(seconds=delay)).isoformat())
        _write_json(status_path, state)
    _write_json(status_path, state)
    return state


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    # OS-owned lock is released on crashes, unlike a persistent PID marker.
    with (ROOT / "x-watch.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        try:
            state = run_once()
            print(json.dumps(state, ensure_ascii=True))
            return 2 if any(a.get("status") == "error" for a in state["accounts"].values()) else 0
        except (OSError, ValueError) as exc:
            print(f"X watcher failed: {exc}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
