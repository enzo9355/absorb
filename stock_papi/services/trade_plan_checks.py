"""Station-side trade-plan checks: evaluate saved plans, append deduped events.

Pure orchestration over existing Store + pure evaluate(). No strategy math
here (all math lives in trade_plans.py). No new scheduler service.
"""

import hashlib
import json
from datetime import datetime, timezone


def _aware(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        if not isinstance(parsed, datetime):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_session(value):
    try:
        text = str(value or "").strip()[:10]
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except (ValueError, TypeError):
        return None


def _plan_events(assistant, plan_id):
    out = []
    for event in assistant.get("events") or []:
        if isinstance(event, dict) and event.get("plan_id") == plan_id:
            out.append(event)
    return out


def _is_cancelled(assistant, plan_id):
    for event in assistant.get("events") or []:
        if not isinstance(event, dict):
            continue
        detail = event.get("detail") or {}
        if event.get("action") == "cancel_plan" and detail.get("plan_id") == plan_id:
            return True
        if event.get("event_type") == "cancelled" and event.get("plan_id") == plan_id:
            return True
    return False


def _has_event_id(assistant, event_id):
    for event in assistant.get("events") or []:
        if isinstance(event, dict) and event.get("event_id") == event_id:
            return True
    return False


def _load_for_session(load_snapshot, market, symbol, session):
    try:
        import inspect as _inspect
        try:
            params = _inspect.signature(load_snapshot).parameters
        except (TypeError, ValueError):
            params = {}
        if len(params) >= 3:
            return load_snapshot(market, symbol, session)
        return load_snapshot(market, symbol) if session is None else None
    except TypeError:
        try:
            return load_snapshot(market, symbol)
        except Exception:
            return None
    except Exception:
        return None


def _sessions_between(calendar, start_exclusive, end_inclusive):
    sessions = []
    raw = calendar.get("sessions") if isinstance(calendar, dict) else None
    if isinstance(raw, list):
        sessions = [str(s)[:10] for s in raw if str(s)[:10]]
    if not sessions:
        return []
    try:
        start_idx = sessions.index(start_exclusive) if start_exclusive else -1
    except ValueError:
        start_idx = -1
    try:
        end_idx = sessions.index(end_inclusive)
    except ValueError:
        return []
    return sessions[start_idx + 1:end_idx + 1]


def compute_followup(saved_entry, calendar, daily_by_session):
    """訊號後市場表現（非損益）：reference open -> +5/+20 close.

    saved_entry: {"plan": plan, "saved_at": iso}.
    daily_by_session: {session: {"open": float, "close": float, "status": "regular"}}.
    Returns dict with reference_session/open, day5/day20 sessions/closes/changes,
    and status ready/watching/unavailable + counts. Never fabricates opens.
    """
    plan = (saved_entry or {}).get("plan") or {}
    sessions = []
    raw = calendar.get("sessions") if isinstance(calendar, dict) else None
    if isinstance(raw, list):
        sessions = [str(s)[:10] for s in raw if str(s)[:10]]
    available_at = _aware(plan.get("available_at") or plan.get("generated_at"))
    saved_at = _aware((saved_entry or {}).get("saved_at"))
    base = None
    for candidate in (available_at, saved_at):
        if candidate is not None and (base is None or candidate > base):
            base = candidate
    if base is None or not sessions:
        return {"status": "unavailable", "reason": "missing_trigger_time"}
    # First complete session strictly after max(signal available, saved).
    base_date = base.date().isoformat()
    reference = None
    for session in sessions:
        if session > base_date:
            reference = session
            break
    if reference is None:
        return {"status": "watching", "reason": "reference_pending",
                "reference_session": None}
    try:
        ref_idx = sessions.index(reference)
    except ValueError:
        return {"status": "unavailable", "reason": "reference_not_in_calendar"}
    ref_row = (daily_by_session or {}).get(reference) or {}
    ref_open = ref_row.get("open")
    if not isinstance(ref_open, (int, float)) or isinstance(ref_open, bool) or not (ref_open > 0):
        return {"status": "unavailable", "reason": "reference_open_missing",
                "reference_session": reference}
    import math as _math
    if not _math.isfinite(float(ref_open)):
        return {"status": "unavailable", "reason": "reference_open_missing",
                "reference_session": reference}
    # Consistent corporate-action basis required; caller passes adjusted series.
    # If any required session is missing/halted, that leg is unavailable (no close-as-open).
    def _leg(offset):
        idx = ref_idx + offset
        if idx >= len(sessions):
            return {"session": None, "close": None, "change": None, "state": "watching"}
        session = sessions[idx]
        row = (daily_by_session or {}).get(session) or {}
        if str(row.get("status") or "regular").lower() not in {"regular", "ok", ""}:
            return {"session": session, "close": None, "change": None, "state": "unavailable"}
        close = row.get("close")
        if not isinstance(close, (int, float)) or isinstance(close, bool) or not _math.isfinite(float(close)):
            return {"session": session, "close": None, "change": None, "state": "unavailable"}
        change = float(close) / float(ref_open) - 1.0
        return {"session": session, "close": float(close), "change": change, "state": "ready"}
    day5 = _leg(5)
    day20 = _leg(20)
    states = {day5["state"], day20["state"]}
    status = "ready" if states <= {"ready"} else ("watching" if "watching" in states else "unavailable")
    return {"status": status, "reference_session": reference, "reference_open": float(ref_open),
            "day5": day5, "day20": day20,
            "note": "訊號後市場表現，非交易損益；名人報酬、跟單報酬、策略淨報酬一律不稱。"}


def run_trade_plan_checks(store, load_snapshot, *, now, calendar,
                          expected_session, allowed_users,
                          push_fn=None, dry_run=True):
    """每個 plan／snapshot 最多處理一次，回掃描／變更／失敗計數。"""
    from stock_papi.services.trade_plans import evaluate_trade_plan as _evaluate
    now_dt = _aware(now)
    expected = _parse_session(expected_session)
    if now_dt is None or expected is None:
        raise ValueError("invalid now or expected_session")
    allowed = frozenset(allowed_users or ())
    sessions = []
    raw = calendar.get("sessions") if isinstance(calendar, dict) else None
    if isinstance(raw, list):
        sessions = [str(s)[:10] for s in raw if str(s)[:10]]

    summary = {"scanned_users": 0, "scanned_plans": 0, "new_events": 0,
               "failures": 0, "coverage_gaps": [], "preview": []}

    try:
        users = list(store.iter_users())
    except Exception:
        users = []
    for user_id, state, _version in users:
        if user_id not in allowed:
            continue
        summary["scanned_users"] += 1
        assistant = state.get("assistant") if isinstance(state, dict) else None
        if not isinstance(assistant, dict):
            continue
        saved = list(assistant.get("saved_plans") or [])
        if not saved:
            continue

        # Dry-run: evaluate without writing.
        if dry_run:
            for entry in saved:
                if not isinstance(entry, dict):
                    continue
                plan = entry.get("plan") or {}
                plan_id = str(entry.get("plan_id") or plan.get("plan_id") or "")
                if not plan_id or _is_cancelled(assistant, plan_id):
                    continue
                summary["scanned_plans"] += 1
                snapshot = _load_for_session(
                    load_snapshot, plan.get("market"), plan.get("symbol"), expected)
                if not isinstance(snapshot, dict):
                    summary["coverage_gaps"].append({"user": "***", "plan_id": plan_id,
                                                     "session": expected, "reason": "snapshot_missing"})
                    continue
                try:
                    out = _evaluate(plan, snapshot, expected_session=expected,
                                    evaluated_at=now_dt, calendar=calendar)
                except (ValueError, TypeError):
                    summary["failures"] += 1
                    continue
                event = out.get("event")
                if event is None:
                    continue
                # Same-snapshot-as-save: presented already, no retroactive event.
                if (event.get("event_type") == "triggered"
                        and str(snapshot.get("source_snapshot_sha256") or "")
                        == str(plan.get("source_snapshot_sha256") or "")):
                    continue
                if _has_event_id(assistant, event.get("event_id")):
                    continue
                summary["new_events"] += 1
                summary["preview"].append({"plan_id": plan_id, "event": event})
            continue

        # Normal mode: single store.update per user (CAS retry dedupes).
        def _mutate(current, _saved=saved, _uid=user_id):
            current_assistant = current.get("assistant") if isinstance(current, dict) else None
            if not isinstance(current_assistant, dict):
                return
            for entry in _saved:
                if not isinstance(entry, dict):
                    continue
                # Re-check plan still exists and not cancelled inside the transaction.
                live = [s for s in current_assistant.get("saved_plans") or []
                        if isinstance(s, dict) and s.get("plan_id") == entry.get("plan_id")]
                if not live:
                    continue
                plan = entry.get("plan") or {}
                plan_id = str(entry.get("plan_id") or plan.get("plan_id") or "")
                if not plan_id or _is_cancelled(current_assistant, plan_id):
                    continue
                # Per-session catch-up: evaluate each new session in order.
                start_from = str(plan.get("data_as_of") or "")
                targets = _sessions_between(calendar, start_from, expected) or [expected]
                for session in targets:
                    snapshot = _load_for_session(
                        load_snapshot, plan.get("market"), plan.get("symbol"), session)
                    if not isinstance(snapshot, dict):
                        summary["coverage_gaps"].append(
                            {"user": "***", "plan_id": plan_id, "session": session,
                             "reason": "snapshot_missing"})
                        continue
                    try:
                        out = _evaluate(plan, snapshot, expected_session=session,
                                        evaluated_at=now_dt, calendar=calendar)
                    except (ValueError, TypeError):
                        summary["failures"] += 1
                        continue
                    event = out.get("event")
                    if event is None:
                        # Gap recovery transitions are meaningful; detect via last gap marker.
                        if out.get("data_gap"):
                            last = None
                            for ev in reversed(current_assistant.get("events") or []):
                                if isinstance(ev, dict) and ev.get("plan_id") == plan_id:
                                    last = ev
                                    break
                            if last is not None and last.get("event_type") not in {"data_gap", None}:
                                gap_event = {
                                    "event_id": "tpe_" + hashlib.sha256(
                                        json.dumps({"plan_id": plan_id, "session": session,
                                                    "type": "data_gap"}, sort_keys=True).encode()
                                    ).hexdigest()[:24],
                                    "event_type": "data_gap", "new_status": out.get("status"),
                                    "plan_id": plan_id, "session": session,
                                    "reasons": list(out.get("reasons") or []),
                                    "created_at": now_dt.isoformat().replace("+00:00", "Z"),
                                }
                                if not _has_event_id(current_assistant, gap_event["event_id"]):
                                    if len(current_assistant.get("events") or []) >= 200:
                                        summary["failures"] += 1
                                    else:
                                        current_assistant["events"].append(gap_event)
                                        summary["new_events"] += 1
                        continue
                    if (event.get("event_type") == "triggered"
                            and str(snapshot.get("source_snapshot_sha256") or "")
                            == str(plan.get("source_snapshot_sha256") or "")):
                        continue
                    record = dict(event)
                    record.setdefault("plan_id", plan_id)
                    record.setdefault("session", session)
                    record.setdefault("created_at", now_dt.isoformat().replace("+00:00", "Z"))
                    if _has_event_id(current_assistant, record.get("event_id")):
                        continue
                    if len(current_assistant.get("events") or []) >= 200:
                        summary["failures"] += 1
                        continue
                    current_assistant["events"].append(record)
                    summary["new_events"] += 1
                    summary["scanned_plans"] += 1
                    if callable(push_fn):
                        try:
                            push_fn(_uid, dict(record), dict(plan))
                        except Exception:
                            summary["failures"] += 1

        try:
            store.update(user_id, _mutate)
        except Exception:
            summary["failures"] += 1
    return summary
