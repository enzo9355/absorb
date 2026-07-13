"""LINE state access and sector-snapshot persistence helpers."""

import json
import urllib.parse

from line_state import StoreError


def get_line_state(store, user_id):
    if store is None:
        raise StoreError("關注功能尚未設定")
    return store.load(user_id)[0]


def get_line_state_bounded(store, user_id, timeout, slots, logger, max_workers, queue_module, threading_module):
    if store is None:
        raise StoreError("關注功能尚未設定")
    result = queue_module.Queue(maxsize=1)
    slots = slots
    if not slots.acquire(blocking=False):
        logger.warning(f"Firestore read slots exhausted (MAX_WORKERS={max_workers}) for user {user_id}")
        raise StoreError("關注功能讀取忙碌")

    def load_state():
        try:
            value = (False, None)
            try:
                value = (True, store.load(user_id)[0])
            except BaseException as exc:
                logger.error(f"Firestore load exception for user {user_id}: {type(exc).__name__} - {exc}", exc_info=True)
            try:
                result.put_nowait(value)
            except BaseException:
                pass
        finally:
            slots.release()

    try:
        threading_module.Thread(target=load_state, daemon=True).start()
    except BaseException as error:
        slots.release()
        if isinstance(error, Exception):
            raise StoreError("關注功能讀取失敗") from None
        raise
    try:
        succeeded, state = result.get(timeout=timeout)
    except queue_module.Empty:
        raise StoreError("關注功能讀取逾時") from None
    if not succeeded:
        raise StoreError("關注功能讀取失敗")
    return state


def update_line_state(store, user_id, mutate):
    if store is None:
        raise StoreError("關注功能尚未設定")
    return store.update(user_id, mutate)


def store_error_text(store):
    if store is None:
        return "關注功能尚未設定，請稍後再試。"
    return "關注功能暫時無法使用，請稍後再試。"


def _system_document_url(store, document_id):
    return (
        "https://firestore.googleapis.com/v1/projects/"
        f"{store.project_id}/databases/(default)/documents/system/"
        f"{urllib.parse.quote(document_id, safe='')}"
    )


def save_sector_signal_snapshot(store, snapshot):
    body = {
        "fields": {
            "payload": {
                "stringValue": json.dumps(
                    snapshot, ensure_ascii=False, separators=(",", ":")
                )
            }
        }
    }
    response = store._request(
        "PATCH",
        _system_document_url(store, SECTOR_SNAPSHOT_DOC),
        timeout=10,
        params={"updateMask.fieldPaths": "payload"},
        json=body,
    )
    if response.status_code != 200:
        raise StoreError(
            f"sector snapshot write failed with status {response.status_code}"
        )


def load_sector_signal_snapshot(store):
    response = store._request(
        "GET", _system_document_url(store, SECTOR_SNAPSHOT_DOC), timeout=5
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise StoreError(
            f"sector snapshot read failed with status {response.status_code}"
        )
    try:
        raw = response.json().get("fields", {}).get("payload", {}).get("stringValue")
        snapshot = json.loads(raw)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("sectors"), dict):
            raise ValueError("invalid snapshot")
        return snapshot
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StoreError("sector snapshot response was invalid") from None


def refresh_sector_signals(
    store, fetch_activity, build_snapshot, save_snapshot, market_map, analyze
):
    activity = fetch_activity()
    snapshot = build_snapshot(market_map, analyze, activity=activity)
    save_snapshot(store, snapshot)
    return snapshot
