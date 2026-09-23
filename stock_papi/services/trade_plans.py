"""Conditional daily trade plans (us_daily_breakout_v1). Pure functions only.

No HTTP clients, no LLM, no store access. All time/calendar inputs are
injected by the application layer (America/New_York sessions + official
snapshot publish point). Never falls back to Taipei date.today() or
Monday-to-Friday estimation.
"""

import hashlib
import json
import math
from datetime import datetime, timezone

POLICY_VERSION = "us_daily_breakout_v1"
PLAN_SCHEMA_VERSION = 1
RSI_METHOD = "rsi14_wilder_last61_v1"
VOLUME_METHOD = "volume_ratio_t_over_avg20_v1"

ACTION_WAIT = "wait"
ACTION_ENTRY = "entry_review"
ACTION_AVOID = "avoid_chasing"
ACTION_EXIT = "exit_review"
ACTION_INSUFFICIENT = "insufficient"

STATUS_WATCHING = "watching"
STATUS_TRIGGERED = "triggered"
STATUS_INVALIDATED = "invalidated"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"

TERMINAL_STATUSES = frozenset({STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_CANCELLED, STATUS_COMPLETED})

_HEX64 = __import__("re").compile(r"^[0-9a-fA-F]{64}$")

_ACTION_TEXT = {
    ACTION_WAIT: "等待條件確認",
    ACTION_ENTRY: "條件符合，可評估進場",
    ACTION_AVOID: "暫不追價",
    ACTION_EXIT: "檢查退出條件",
    ACTION_INSUFFICIENT: "暫停評估",
}


def action_text(action):
    return _ACTION_TEXT.get(action, action)


def is_terminal_status(status):
    return status in TERMINAL_STATUSES


def _finite(value):
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _parse_session(value):
    try:
        text = str(value or "").strip()[:10]
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except (ValueError, TypeError):
        return None


def _aware(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _calendar_index(calendar):
    sessions = []
    if isinstance(calendar, dict):
        raw = calendar.get("sessions")
        if isinstance(raw, list):
            for item in raw:
                session = _parse_session(item)
                if session:
                    sessions.append(session)
    # Preserve order, dedupe, require sorted ascending without silent repair.
    # If input is unsorted or has duplicates, treat calendar as invalid.
    if not sessions:
        return None, "calendar_empty"
    if any(sessions[i] >= sessions[i + 1] for i in range(len(sessions) - 1)):
        return None, "calendar_not_strictly_sorted"
    return sessions, None


def _rsi_last61(closes):
    """Wilder RSI(14) over exactly the last 61 closes. See spec 5.2.3."""
    if len(closes) < 61:
        return None
    window = closes[-61:]
    diffs = [window[i] - window[i - 1] for i in range(1, len(window))]
    # First 14 diffs -> arithmetic mean seed.
    gains = [max(d, 0.0) for d in diffs[:14]]
    losses = [max(-d, 0.0) for d in diffs[:14]]
    avg_gain = sum(gains) / 14.0
    avg_loss = sum(losses) / 14.0
    for diff in diffs[14:]:
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * 13.0 + gain) / 14.0
        avg_loss = (avg_loss * 13.0 + loss) / 14.0
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _validate_plan_daily_rows(snapshot):
    daily = snapshot.get("daily")
    if not isinstance(daily, list) or len(daily) < 61:
        return None, "insufficient_history"
    rows = []
    seen = set()
    for index, row in enumerate(daily):
        if not isinstance(row, dict):
            return None, "invalid_daily_row"
        session = _parse_session(row.get("date"))
        if session is None:
            return None, "invalid_daily_date"
        if session in seen:
            return None, "duplicate_daily_date"
        seen.add(session)
        status = str(row.get("status") or "regular").strip().lower()
        if status not in {"regular", "ok", ""}:
            return None, "non_regular_session"
        open_ = _finite(row.get("open"))
        high = _finite(row.get("high"))
        low = _finite(row.get("low"))
        close = _finite(row.get("close"))
        volume = _finite(row.get("volume"))
        if open_ is None or high is None or low is None or close is None or volume is None:
            return None, "non_finite_ohlcv"
        if volume <= 0 or close <= 0 or high <= 0 or low <= 0 or open_ <= 0:
            return None, "non_positive_ohlcv"
        if not (high >= low and high >= open_ >= low and high >= close >= low):
            return None, "invalid_ohlc_range"
        rows.append({"date": session, "open": open_, "high": high,
                     "low": low, "close": close, "volume": volume})
    # Strictly ascending; do not sort or drop rows silently.
    for i in range(len(rows) - 1):
        if rows[i]["date"] >= rows[i + 1]["date"]:
            return None, "daily_not_sorted"
    return rows, None


def _plan_id(policy_version, market, symbol, snapshot_hash, frozen, evidence_ids):
    canonical = json.dumps({
        "policy_version": policy_version,
        "market": market,
        "symbol": symbol,
        "source_snapshot_sha256": snapshot_hash,
        "frozen": frozen,
        "evidence_ids": sorted(evidence_ids or []),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "tp_" + digest[:32]


def _event_id(plan_id, snapshot_hash, event_type, new_status):
    canonical = json.dumps({
        "plan_id": plan_id,
        "snapshot_hash": snapshot_hash,
        "event_type": event_type,
        "new_status": new_status,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "tpe_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _held_unheld_guidance(action):
    if action == ACTION_ENTRY:
        return ("你未持有：條件符合，可於下個完整交易時段評估是否進場；開盤跳空超過上限則放棄原價。",
                "你已標記持有：本計畫為進場規則，不作加碼建議；重點看失效／退出檢查。")
    if action == ACTION_AVOID:
        return ("你未持有：已超出計畫容許價格或過熱，暫不追價。",
                "你已標記持有：不追價；若已持有，依原失效條件檢查退出。")
    if action == ACTION_EXIT:
        return ("你未持有：取消這份進場計畫。",
                "你已標記持有：檢查退出條件（收盤確認，盤中跳空風險未被消除）。")
    if action == ACTION_WAIT:
        return ("你未持有：等待條件確認，不要預先進場。",
                "你已標記持有：等待中；以失效價與到期日為準，不預設持有即安全。")
    return ("你未持有：暫停評估，先補齊資料。",
            "你已標記持有：暫停評估，先補齊資料；不要依缺資料訊號加減碼。")


def build_trade_plan(snapshot, *, expected_session, generated_at, calendar, evidence_ids=()):
    """產生規則結果，無副作用；不接受 caller 提供的勝率或行動標籤。"""
    reasons = []
    evidence_ids = tuple(sorted(str(v) for v in (evidence_ids or ())))
    generated = _aware(generated_at)
    expected = _parse_session(expected_session)
    sessions, calendar_error = _calendar_index(calendar)
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    def insufficient(reason, detail=""):
        plan = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": _plan_id(POLICY_VERSION,
                                str(snapshot.get("market") or "").upper() or "US",
                                str(snapshot.get("symbol") or "").upper() or "UNKNOWN",
                                str(snapshot.get("source_snapshot_sha256") or "missing"),
                                {"insufficient": reason}, evidence_ids),
            "policy_version": POLICY_VERSION,
            "market": str(snapshot.get("market") or "").upper(),
            "symbol": str(snapshot.get("symbol") or "").upper(),
            "instrument_type": str(snapshot.get("instrument_type") or ""),
            "source_snapshot_sha256": str(snapshot.get("source_snapshot_sha256") or ""),
            "source_ref": snapshot.get("source_ref") or {"label": "unverified"},
            "data_as_of": str(snapshot.get("as_of") or snapshot.get("data_as_of") or ""),
            "generated_at": generated.isoformat().replace("+00:00", "Z") if generated else "",
            "available_at": generated.isoformat().replace("+00:00", "Z") if generated else "",
            "eligible_session": "",
            "expires_session": "",
            "action": ACTION_INSUFFICIENT,
            "conditions": {"reason": reason, "detail": detail},
            "supporting_evidence": [],
            "opposing_evidence": [reason],
            "limitations": ["日線規則試用版，尚未驗證獲利能力；資料不足時停止產生可進場建議。", reason],
            "external_evidence_ids": list(evidence_ids),
            "rsi_method": RSI_METHOD,
            "volume_method": VOLUME_METHOD,
            "params": {"ma_fast": 20, "ma_slow": 60, "volume_ratio": 1.2,
                       "rsi_ceiling": 70, "entry_buffer": 0.03, "expiry_sessions": 5},
        }
        unheld, held = _held_unheld_guidance(ACTION_INSUFFICIENT)
        plan["unheld_guidance"] = unheld
        plan["held_guidance"] = held
        return plan

    if generated is None:
        return insufficient("invalid_generated_at")
    if expected is None:
        return insufficient("invalid_expected_session")
    if calendar_error:
        return insufficient(calendar_error)
    if expected not in sessions:
        return insufficient("calendar_missing_expected_session")
    market = str(snapshot.get("market") or "").strip().upper()
    symbol = str(snapshot.get("symbol") or "").strip().upper()
    instrument = str(snapshot.get("instrument_type") or "").strip()
    kind = str(snapshot.get("observation_kind") or "").strip()
    snapshot_hash = str(snapshot.get("source_snapshot_sha256") or "").strip()
    if market != "US":
        return insufficient("unsupported_market")
    if instrument != "common_stock":
        return insufficient("unsupported_instrument")
    if kind != "regular_price":
        return insufficient("unsupported_observation_kind")
    if not symbol:
        return insufficient("missing_symbol")
    if not _HEX64.match(snapshot_hash):
        return insufficient("unverified_snapshot")
    corporate = str(snapshot.get("corporate_action_status") or snapshot.get("corporate_action") or "ok")
    if corporate not in {"ok", "regular", "", "none"}:
        # Any split/merge/uncomparable marker blocks new plans; frozen levels must not be rewritten.
        if "uncompar" in corporate.lower() or "split" in corporate.lower() or "merge" in corporate.lower():
            return insufficient("corporate_action_uncomparable")
        return insufficient("corporate_action_uncomparable")
    if isinstance(snapshot.get("corporate_action_uncomparable"), bool) and snapshot.get("corporate_action_uncomparable"):
        return insufficient("corporate_action_uncomparable")

    rows, daily_error = _validate_plan_daily_rows(snapshot)
    if daily_error:
        return insufficient(daily_error)
    if rows[-1]["date"] != expected:
        # Snapshot behind or ahead of the injected expected session.
        if rows[-1]["date"] > expected:
            return insufficient("future_snapshot")
        return insufficient("stale_snapshot")
    # Require 61 consecutive sessions ending at expected (no silent repair).
    try:
        end_index = sessions.index(expected)
    except ValueError:
        return insufficient("calendar_missing_expected_session")
    if end_index < 60:
        return insufficient("insufficient_calendar_history")
    expected_window = sessions[end_index - 60:end_index + 1]
    daily_dates = [r["date"] for r in rows[-61:]]
    if daily_dates != expected_window:
        return insufficient("non_consecutive_sessions")

    closes = [r["close"] for r in rows]
    last61 = rows[-61:]
    closes61 = [r["close"] for r in last61]
    ma20 = sum(closes[-20:]) / 20.0
    ma60 = sum(closes[-60:]) / 60.0
    volumes20 = [r["volume"] for r in rows[-21:-1]]
    avg20 = sum(volumes20) / 20.0
    volume_ratio = rows[-1]["volume"] / avg20 if avg20 > 0 else None
    rsi = _rsi_last61(closes61)
    if rsi is None or volume_ratio is None:
        return insufficient("indicator_unavailable")

    prior20_high = max(r["high"] for r in rows[-21:-1])
    trigger = prior20_high
    ceiling = trigger * 1.03
    invalidation = ma20
    close_t = rows[-1]["close"]

    if not (invalidation < trigger):
        # Structure invalid: do not fabricate an entry plan.
        frozen = {"trigger_price": trigger, "entry_ceiling": ceiling,
                  "invalidation_price": invalidation, "blocked": "invalidation_not_below_trigger"}
        plan_id = _plan_id(POLICY_VERSION, market, symbol, snapshot_hash, frozen, evidence_ids)
        unheld, held = _held_unheld_guidance(ACTION_WAIT)
        try:
            eligible = sessions[end_index + 1]
        except IndexError:
            eligible = ""
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "policy_version": POLICY_VERSION,
            "market": market, "symbol": symbol, "instrument_type": instrument,
            "source_snapshot_sha256": snapshot_hash,
            "source_ref": snapshot.get("source_ref") or {"label": "verified_reader"},
            "data_as_of": expected,
            "generated_at": generated.isoformat().replace("+00:00", "Z"),
            "available_at": generated.isoformat().replace("+00:00", "Z"),
            "eligible_session": eligible,
            "expires_session": sessions[end_index + 5] if end_index + 5 < len(sessions) else "",
            "action": ACTION_WAIT,
            "conditions": {"trigger_price": trigger, "entry_ceiling": ceiling,
                           "invalidation_price": invalidation, "close": close_t,
                           "ma20": ma20, "ma60": ma60, "volume_ratio": volume_ratio,
                           "rsi": rsi, "reason": "invalidation_not_below_trigger",
                           "note": "收盤確認，盤中跳空風險未被消除"},
            "supporting_evidence": [f"Close {close_t}；MA20 {ma20:.4f}；MA60 {ma60:.4f}"],
            "opposing_evidence": ["失效價不低於觸發價，結構不支援進場"],
            "limitations": ["日線規則試用版，尚未驗證獲利能力。", "收盤確認，盤中跳空風險未被消除。"],
            "external_evidence_ids": list(evidence_ids),
            "rsi_method": RSI_METHOD, "volume_method": VOLUME_METHOD,
            "params": {"ma_fast": 20, "ma_slow": 60, "volume_ratio": 1.2,
                       "rsi_ceiling": 70, "entry_buffer": 0.03, "expiry_sessions": 5},
            "unheld_guidance": unheld, "held_guidance": held,
        }

    trend_ok = close_t >= ma20 >= ma60
    breakout_ok = close_t > trigger
    volume_ok = volume_ratio >= 1.2
    rsi_ok = rsi < 70.0
    ceiling_ok = close_t <= ceiling

    if (not trend_ok) or (not breakout_ok) or (not volume_ok):
        action = ACTION_WAIT
        reason = "conditions_not_met"
    elif (not rsi_ok) or (not ceiling_ok):
        action = ACTION_AVOID
        reason = "overheated_or_extended"
    else:
        action = ACTION_ENTRY
        reason = "all_conditions_met"

    frozen = {"trigger_price": trigger, "entry_ceiling": ceiling, "invalidation_price": invalidation}
    plan_id = _plan_id(POLICY_VERSION, market, symbol, snapshot_hash, frozen, evidence_ids)
    try:
        eligible = sessions[end_index + 1]
    except IndexError:
        eligible = ""
    expires = sessions[end_index + 5] if end_index + 5 < len(sessions) else ""
    unheld, held = _held_unheld_guidance(action)
    supporting = [
        f"趨勢 Close {close_t} >= MA20 {ma20:.4f} >= MA60 {ma60:.4f}" if trend_ok else f"趨勢未成立 Close {close_t} MA20 {ma20:.4f} MA60 {ma60:.4f}",
        f"突破 trigger {trigger}，收盤 {close_t}" if breakout_ok else f"未突破 trigger {trigger}",
        f"量比 {volume_ratio:.4f}（門檻 1.2）" if volume_ok else f"量比不足 {volume_ratio:.4f}",
    ]
    opposing = []
    if not rsi_ok:
        opposing.append(f"RSI {rsi:.2f} >= 70 過熱")
    if not ceiling_ok:
        opposing.append(f"收盤 {close_t} 超出上限 {ceiling}")
    if not trend_ok:
        opposing.append("趨勢條件未成立")
    if not breakout_ok:
        opposing.append("未突破觸發價")
    if not volume_ok:
        opposing.append("量能不足")
    opposing.append("突破可能失敗；外部觀點與數據矛盾時並列，不自動升級買進。")
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "policy_version": POLICY_VERSION,
        "market": market, "symbol": symbol, "instrument_type": instrument,
        "source_snapshot_sha256": snapshot_hash,
        "source_ref": snapshot.get("source_ref") or {"label": "verified_reader"},
        "data_as_of": expected,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "available_at": generated.isoformat().replace("+00:00", "Z"),
        "eligible_session": eligible,
        "expires_session": expires,
        "action": action,
        "conditions": {"trigger_price": trigger, "entry_ceiling": ceiling,
                       "invalidation_price": invalidation, "close": close_t,
                       "ma20": ma20, "ma60": ma60, "volume_ratio": volume_ratio,
                       "rsi": rsi, "reason": reason,
                       "note": "收盤確認，盤中跳空風險未被消除；入場建議最早適用於 generated_at 之後的下一個完整交易時段。"},
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "limitations": ["日線規則試用版，尚未驗證獲利能力；方向分數不得變成百分比勝率。",
                        "收盤確認，盤中跳空風險未被消除；開盤跳空超過上限不得稱可原價成交。"],
        "external_evidence_ids": list(evidence_ids),
        "rsi_method": RSI_METHOD, "volume_method": VOLUME_METHOD,
        "params": {"ma_fast": 20, "ma_slow": 60, "volume_ratio": 1.2,
                   "rsi_ceiling": 70, "entry_buffer": 0.03, "expiry_sessions": 5},
        "unheld_guidance": unheld, "held_guidance": held,
    }


def evaluate_trade_plan(plan, snapshot, *, expected_session, evaluated_at, calendar):
    """回傳狀態、action、原因與可去重的 event；不覆寫 plan。"""
    plan = plan if isinstance(plan, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    evaluated = _aware(evaluated_at)
    expected = _parse_session(expected_session)
    sessions, calendar_error = _calendar_index(calendar)
    frozen = {
        "trigger_price": (plan.get("conditions") or {}).get("trigger_price"),
        "entry_ceiling": (plan.get("conditions") or {}).get("entry_ceiling"),
        "invalidation_price": (plan.get("conditions") or {}).get("invalidation_price"),
    }
    plan_id = str(plan.get("plan_id") or "")
    snapshot_hash = str(snapshot.get("source_snapshot_sha256") or "missing")
    base_action = str(plan.get("action") or ACTION_WAIT)
    was_entry = base_action == ACTION_ENTRY

    def result(status, action, reasons, event_type=None, data_gap=False):
        event = None
        if event_type is not None:
            event = {"event_id": _event_id(plan_id, snapshot_hash, event_type, status),
                     "event_type": event_type, "new_status": status, "reasons": list(reasons)}
        return {"status": status, "action": action, "reasons": list(reasons),
                "event": event, "data_gap": data_gap,
                "plan_id": plan_id, "expected_session": expected or "",
                "evaluated_at": evaluated.isoformat().replace("+00:00", "Z") if evaluated else ""}

    if evaluated is None or expected is None or calendar_error or expected not in (sessions or []):
        preserved = STATUS_TRIGGERED if was_entry else STATUS_WATCHING
        return result(preserved, ACTION_INSUFFICIENT, ["evaluation_unavailable"], data_gap=True)

    # Re-validate snapshot freshness/continuity; gaps never become signals.
    rows, daily_error = _validate_plan_daily_rows(snapshot)
    if daily_error or rows[-1]["date"] != expected:
        preserved = STATUS_TRIGGERED if was_entry else STATUS_WATCHING
        reason = daily_error or ("stale_snapshot" if rows and rows[-1]["date"] != expected else "invalid_snapshot")
        return result(preserved, ACTION_INSUFFICIENT, [reason], data_gap=True)
    try:
        end_index = sessions.index(expected)
    except ValueError:
        preserved = STATUS_TRIGGERED if was_entry else STATUS_WATCHING
        return result(preserved, ACTION_INSUFFICIENT, ["calendar_missing_session"], data_gap=True)

    # Expiry for never-triggered plans.
    expires_session = str(plan.get("expires_session") or "")
    if not was_entry and expires_session and expected > expires_session:
        return result(STATUS_EXPIRED, ACTION_INSUFFICIENT, ["plan_expired"], event_type="expired")

    # Completion for initially-triggered plans after 20 sessions.
    if was_entry:
        try:
            trigger_index = sessions.index(str(plan.get("data_as_of") or ""))
            if end_index - trigger_index >= 20:
                return result(STATUS_COMPLETED, base_action, ["observation_window_completed"], event_type="completed")
        except ValueError:
            pass

    trigger = frozen.get("trigger_price")
    ceiling = frozen.get("entry_ceiling")
    invalidation = frozen.get("invalidation_price")
    if trigger is None or ceiling is None or invalidation is None:
        return result(STATUS_WATCHING, ACTION_INSUFFICIENT, ["frozen_levels_missing"], data_gap=True)

    closes = [r["close"] for r in rows]
    rsi = _rsi_last61(closes[-61:])
    volumes20 = [r["volume"] for r in rows[-21:-1]]
    avg20 = sum(volumes20) / 20.0 if len(volumes20) == 20 else None
    volume_ratio = rows[-1]["volume"] / avg20 if avg20 else None
    ma20 = sum(closes[-20:]) / 20.0
    ma60 = sum(closes[-60:]) / 60.0 if len(closes) >= 60 else None
    close_now = rows[-1]["close"]
    if rsi is None or volume_ratio is None or ma60 is None:
        preserved = STATUS_TRIGGERED if was_entry else STATUS_WATCHING
        return result(preserved, ACTION_INSUFFICIENT, ["indicator_unavailable"], data_gap=True)

    # Invalidation only applies to triggered (entry) structures; never invent exits for waiting plans.
    if was_entry and close_now < invalidation:
        return result(STATUS_INVALIDATED, ACTION_EXIT, ["close_below_invalidation"], event_type="invalidated")

    trend_ok = close_now >= ma20 >= ma60
    breakout_ok = close_now > trigger
    volume_ok = volume_ratio >= 1.2
    rsi_ok = rsi < 70.0
    ceiling_ok = close_now <= ceiling
    if trend_ok and breakout_ok and volume_ok and rsi_ok and ceiling_ok:
        return result(STATUS_TRIGGERED, ACTION_ENTRY, ["conditions_met"], event_type="triggered")
    if (not rsi_ok) or (not ceiling_ok):
        # Overheated/extended: watching unless originally triggered (stay triggered, no new event to avoid spam?).
        if was_entry:
            return result(STATUS_TRIGGERED, ACTION_AVOID, ["overheated_but_triggered"], event_type=None)
        return result(STATUS_WATCHING, ACTION_AVOID, ["overheated_or_extended"], event_type=None)
    return result(STATUS_WATCHING if not was_entry else STATUS_TRIGGERED,
                  ACTION_WAIT, ["conditions_not_met"], event_type=None)









_ASSISTANT_ACTIONS = {
    "set_preferences", "follow_subject", "unfollow_subject",
    "follow_creator", "unfollow_creator", "save_plan", "cancel_plan",
    "set_position_context", "set_notifications", "feedback",
}
_ASSISTANT_FIELDS = {
    "set_preferences": {"action", "view_preference", "request_id"},
    "follow_subject": {"action", "subject_id", "request_id"},
    "unfollow_subject": {"action", "subject_id", "request_id"},
    "follow_creator": {"action", "creator_id", "request_id"},
    "unfollow_creator": {"action", "creator_id", "request_id"},
    "save_plan": {"action", "market", "symbol", "expected_plan_id", "evidence_ids",
                  "position_context", "request_id"},
    "cancel_plan": {"action", "plan_id", "request_id"},
    "set_position_context": {"action", "plan_id", "position_context", "request_id"},
    "set_notifications": {"action", "enabled", "request_id"},
    "feedback": {"action", "category", "helpful", "text", "page", "plan_id",
                 "activity_id", "request_id"},
}
_ASSISTANT_LIMITS = {
    "follows": 20, "plans": 20, "events": 200, "feedback": 20,
}


def _assistant_now_iso(now):
    parsed = _aware(now)
    if parsed is None:
        raise ValueError("invalid now")
    return parsed.isoformat().replace("+00:00", "Z")


def _assistant_seen_requests(assistant):
    seen = set()
    for event in assistant.get("events") or []:
        if isinstance(event, dict) and event.get("request_id"):
            seen.add(str(event["request_id"]))
    for plan in assistant.get("saved_plans") or []:
        if isinstance(plan, dict) and plan.get("request_id"):
            seen.add(str(plan["request_id"]))
    for item in assistant.get("feedback") or []:
        if isinstance(item, dict) and item.get("request_id"):
            seen.add(str(item["request_id"]))
    return seen


def _assistant_ensure_room(assistant, *, extra_event=True, extra_plan=None, extra_feedback=None):
    import json as _json
    if extra_plan is not None:
        if len(assistant.get("saved_plans") or []) >= _ASSISTANT_LIMITS["plans"]:
            raise ValueError("assistant_capacity_reached")
        try:
            size = len(_json.dumps(extra_plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            raise ValueError("saved_plan_unserializable")
        if size > 8 * 1024:
            raise ValueError("saved_plan_too_large")
    if extra_feedback is not None:
        if len(assistant.get("feedback") or []) >= _ASSISTANT_LIMITS["feedback"]:
            raise ValueError("assistant_capacity_reached")
    if extra_event:
        if len(assistant.get("events") or []) >= _ASSISTANT_LIMITS["events"]:
            raise ValueError("assistant_capacity_reached")
    # Total size guard (UTF-8 JSON <= 450KB) after tentative addition.
    trial = {
        "schema_version": 1,
        "view_preference": assistant.get("view_preference"),
        "followed_subject_ids": list(assistant.get("followed_subject_ids") or []),
        "followed_creator_ids": list(assistant.get("followed_creator_ids") or []),
        "saved_plans": list(assistant.get("saved_plans") or []) + ([extra_plan] if extra_plan is not None else []),
        "events": list(assistant.get("events") or []) + ([{"_pad": "x"}] if extra_event else []),
        "feedback": list(assistant.get("feedback") or []) + ([extra_feedback] if extra_feedback is not None else []),
        "line_notifications_enabled": bool(assistant.get("line_notifications_enabled")),
    }
    try:
        import json as _json2
        total = len(_json2.dumps(trial, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        raise ValueError("assistant_unserializable")
    if total > 450 * 1024:
        raise ValueError("assistant_capacity_reached")


def _assistant_event(request_id, action, now_iso, detail=None):
    canonical = json.dumps({"request_id": request_id, "action": action},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event_id = "ae_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    event = {"event_id": event_id, "request_id": request_id, "action": action,
             "created_at": now_iso, "detail": detail or {}}
    try:
        if len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 1024:
            raise ValueError("assistant_capacity_reached")
    except (TypeError, ValueError):
        raise ValueError("assistant_capacity_reached")
    return event


def _validate_uuid(value):
    import re as _re
    if not isinstance(value, str) or _re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value) is None:
        raise ValueError("invalid_request_id")
    return value


def apply_assistant_command(state, command, *, now, verified_plan=None):
    """驗證並更新 assistant 子狀態；只在 store.update 內呼叫。"""
    import copy as _copy
    if not isinstance(state, dict):
        raise ValueError("invalid_state")
    if "_assistant_invalid" in state:
        raise ValueError("assistant_corrupted")
    assistant = state.get("assistant")
    if assistant is None:
        from line_state import empty_assistant as _empty
        assistant = _empty()
        state["assistant"] = assistant
    if not isinstance(assistant, dict):
        raise ValueError("assistant_corrupted")
    if not isinstance(command, dict):
        raise ValueError("invalid_command")
    action = command.get("action")
    if action not in _ASSISTANT_ACTIONS:
        raise ValueError("unknown_action")
    allowed = _ASSISTANT_FIELDS[action]
    if set(command.keys()) != allowed:
        raise ValueError("unknown_fields")
    request_id = _validate_uuid(command.get("request_id"))
    now_iso = _assistant_now_iso(now)
    seen = _assistant_seen_requests(assistant)
    if request_id in seen:
        return  # Idempotent replay (store conflict retry): single event preserved.

    def _emit(event_action, detail=None, *, with_event=True):
        if with_event:
            _assistant_ensure_room(assistant, extra_event=True)
            assistant["events"].append(_assistant_event(request_id, event_action, now_iso, detail))

    if action == "set_preferences":
        preference = command.get("view_preference")
        if preference not in {"data", "people", "combined"}:
            raise ValueError("invalid_view_preference")
        if assistant.get("view_preference") == preference:
            return  # Pure reset of same value: no event.
        _assistant_ensure_room(assistant, extra_event=True)
        assistant["view_preference"] = preference
        _emit("set_preferences", {"view_preference": preference})
        return

    if action in {"follow_subject", "unfollow_subject", "follow_creator", "unfollow_creator"}:
        key = "followed_subject_ids" if "subject" in action else "followed_creator_ids"
        field = "subject_id" if "subject" in action else "creator_id"
        target = command.get(field)
        if not isinstance(target, str) or not target.strip() or len(target) > 200 or target.strip() != target:
            raise ValueError("invalid_follow_id")
        current = list(assistant.get(key) or [])
        if action.startswith("follow_"):
            if target in current:
                return  # Idempotent; still record request to prevent replays?
            total = len(assistant.get("followed_subject_ids") or []) + len(assistant.get("followed_creator_ids") or [])
            if total >= _ASSISTANT_LIMITS["follows"]:
                raise ValueError("assistant_capacity_reached")
            _assistant_ensure_room(assistant, extra_event=True)
            current.append(target)
            assistant[key] = current
            _emit(action, {field: target})
        else:
            if target not in current:
                return
            _assistant_ensure_room(assistant, extra_event=True)
            assistant[key] = [v for v in current if v != target]
            _emit(action, {field: target})
        return

    if action == "save_plan":
        if verified_plan is None or not isinstance(verified_plan, dict):
            raise ValueError("verified_plan_required")
        market = str(command.get("market") or "").strip().upper()
        symbol = str(command.get("symbol") or "").strip().upper()
        expected_plan_id = str(command.get("expected_plan_id") or "").strip()
        evidence_ids = command.get("evidence_ids")
        position = command.get("position_context")
        if market not in {"US"}:
            raise ValueError("unsupported_market")
        if not symbol:
            raise ValueError("invalid_symbol")
        if not expected_plan_id:
            raise ValueError("missing_expected_plan_id")
        if not isinstance(evidence_ids, list) or any(not isinstance(v, str) for v in evidence_ids):
            raise ValueError("invalid_evidence_ids")
        if position not in {"unheld", "held"}:
            raise ValueError("invalid_position_context")
        if verified_plan.get("plan_id") != expected_plan_id:
            raise ValueError("stale_plan")
        if verified_plan.get("market") != market or verified_plan.get("symbol") != symbol:
            raise ValueError("stale_plan")
        if verified_plan.get("action") == ACTION_INSUFFICIENT:
            raise ValueError("cannot_save_insufficient")
        for saved in assistant.get("saved_plans") or []:
            if isinstance(saved, dict) and saved.get("plan", {}).get("plan_id") == expected_plan_id:
                return  # Same content re-save: no duplicate.
        saved_entry = {"plan": _copy.deepcopy(verified_plan), "saved_at": now_iso,
                       "position_context": position, "request_id": request_id,
                       "plan_id": expected_plan_id}
        _assistant_ensure_room(assistant, extra_event=True, extra_plan=saved_entry)
        assistant["saved_plans"].append(saved_entry)
        # Initial observation: entry plans start triggered (no retroactive push); others watching.
        initial = STATUS_TRIGGERED if verified_plan.get("action") == ACTION_ENTRY else STATUS_WATCHING
        _emit("save_plan", {"plan_id": expected_plan_id, "initial_status": initial,
                            "position_context": position})
        return

    if action == "cancel_plan":
        plan_id = str(command.get("plan_id") or "").strip()
        if not plan_id:
            raise ValueError("missing_plan_id")
        found = any(isinstance(s, dict) and s.get("plan_id") == plan_id
                    for s in assistant.get("saved_plans") or [])
        if not found:
            raise ValueError("plan_not_found")
        _assistant_ensure_room(assistant, extra_event=True)
        _emit("cancel_plan", {"plan_id": plan_id, "status": STATUS_CANCELLED})
        return

    if action == "set_position_context":
        plan_id = str(command.get("plan_id") or "").strip()
        position = command.get("position_context")
        if not plan_id:
            raise ValueError("missing_plan_id")
        if position not in {"unheld", "held"}:
            raise ValueError("invalid_position_context")
        target = None
        for saved in assistant.get("saved_plans") or []:
            if isinstance(saved, dict) and saved.get("plan_id") == plan_id:
                target = saved
                break
        if target is None:
            raise ValueError("plan_not_found")
        if target.get("position_context") == position:
            return
        _assistant_ensure_room(assistant, extra_event=True)
        target["position_context"] = position
        _emit("set_position_context", {"plan_id": plan_id, "position_context": position})
        return

    if action == "set_notifications":
        enabled = command.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("invalid_enabled")
        if bool(assistant.get("line_notifications_enabled")) is enabled:
            return
        _assistant_ensure_room(assistant, extra_event=True)
        assistant["line_notifications_enabled"] = enabled
        _emit("set_notifications", {"enabled": enabled})
        return

    if action == "feedback":
        category = command.get("category")
        helpful = command.get("helpful")
        text = command.get("text")
        page = command.get("page")
        plan_id = command.get("plan_id")
        activity_id = command.get("activity_id")
        if category not in {"general", "plan", "activity", "ui"}:
            raise ValueError("invalid_category")
        if helpful not in {"helpful", "unhelpful", "data_issue"}:
            raise ValueError("invalid_helpful")
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError("invalid_feedback_text")
        for key, val in (("page", page), ("plan_id", plan_id), ("activity_id", activity_id)):
            if val not in (None, "") and (not isinstance(val, str) or len(val) > 500):
                raise ValueError(f"invalid_{key}")
        entry = {"feedback_id": "fb_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16],
                 "request_id": request_id, "category": category, "helpful": helpful,
                 "text": text, "page": page or "", "plan_id": plan_id or "",
                 "activity_id": activity_id or "", "policy_version": POLICY_VERSION,
                 "created_at": now_iso}
        _assistant_ensure_room(assistant, extra_event=True, extra_feedback=entry)
        assistant["feedback"].append(entry)
        _emit("feedback", {"feedback_id": entry["feedback_id"]})
        return

    raise ValueError("unknown_action")


def trigger_reference_session(plan, saved_at, calendar):
    """首次有效觸發 available_at 與 saved_at 之後第一個完整交易時段。"""
    available = _aware(plan.get("available_at") or plan.get("generated_at"))
    saved = _aware(saved_at)
    base = None
    for candidate in (available, saved):
        if candidate is not None and (base is None or candidate > base):
            base = candidate
    if base is None:
        return None
    sessions = []
    raw = calendar.get("sessions") if isinstance(calendar, dict) else None
    if isinstance(raw, list):
        sessions = [str(s)[:10] for s in raw if str(s)[:10]]
    base_date = base.date().isoformat()
    for session in sessions:
        if session > base_date:
            return session
    return None
