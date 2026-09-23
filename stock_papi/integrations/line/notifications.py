import datetime

from line_state import evaluate_alert, top_signals
from stock_papi.integrations.line.flex import build_alert_push_flex


def run_alert_checks(
    store, analyze_fn, push_fn, today, base_url, *, prediction_allowed=True
):
    quotes = {}
    push_failed = False

    def quote_for(code):
        if code in quotes:
            return quotes[code]
        try:
            data = analyze_fn(code)
            if not data or not isinstance(data.get("as_of"), str):
                quotes[code] = None
                return None
            datetime.date.fromisoformat(data["as_of"])
            if prediction_allowed:
                quote = {
                    "code": code,
                    "name": data["name"],
                    "price": float(data["price"]),
                    "prob": int(data["prob"]),
                    "trend": data["trend"],
                    "as_of": data["as_of"],
                }
            else:
                quote = {
                    "code": code,
                    "name": data["name"],
                    "price": float(data["price"]),
                    "trend": {
                        "above_ma20_ma60": "多頭",
                        "above_ma20": "多頭",
                        "below_ma60": "空頭",
                        "mixed": "盤整",
                    }.get(data.get("trend_observation"), "資料不足"),
                    "as_of": data["as_of"],
                }
            quotes[code] = quote
        except Exception:
            quotes[code] = None
        return quotes[code]

    for user_id, observed, _ in store.iter_users():
        observed_codes = [
            item["code"] for item in observed.get("watchlist", [])
            if isinstance(item, dict) and item.get("code")
        ]
        watched = [
            quote for code in observed_codes
            for quote in [quote_for(code)]
            if quote is not None
        ]
        if not watched:
            continue
        prior_as_of = {
            item.get("code"): item.get("as_of")
            for item in observed.get("signals", {}).get("items", [])
            if isinstance(item, dict) and item.get("code") and isinstance(item.get("as_of"), str)
        }
        fresh_codes = {
            quote["code"] for quote in watched
            if not prior_as_of.get(quote["code"]) or quote["as_of"] > prior_as_of[quote["code"]]
        }
        if not fresh_codes:
            continue

        latest_as_of = max(item["as_of"] for item in watched)
        signal_items = (
            top_signals(watched)
            if prediction_allowed
            else [dict(item) for item in watched]
        )
        hits = []
        for alert in observed.get("alerts", []):
            quote = quotes.get(alert.get("code"))
            if (
                not alert.get("enabled")
                or (
                    not prediction_allowed
                    and alert.get("kind") == "probability"
                )
                or alert.get("last_triggered_date") == today
                or quote is None
                or quote["code"] not in fresh_codes
            ):
                continue
            try:
                if evaluate_alert(alert, quote):
                    hits.append({"alert": alert, "quote": quote})
            except (KeyError, TypeError, ValueError):
                continue

        if hits:
            messages = [
                build_alert_push_flex(hits[start:start + 12], base_url)
                for start in range(0, len(hits), 12)
            ]
            try:
                push_fn(user_id, messages[0] if len(messages) == 1 else messages)
            except Exception:
                push_failed = True
                continue
        triggered_ids = {hit["alert"]["id"] for hit in hits}

        def merge_scheduler_fields(state):
            current_codes = [
                item["code"] for item in state.get("watchlist", [])
                if isinstance(item, dict) and item.get("code")
            ]
            if current_codes == observed_codes:
                state["signals"] = {
                    "as_of": latest_as_of,
                    "items": [dict(item) for item in signal_items],
                }
            for alert in state.get("alerts", []):
                if alert.get("id") in triggered_ids:
                    alert["last_triggered_date"] = today

        store.update(user_id, merge_scheduler_fields)
    if push_failed:
        raise RuntimeError("部分 LINE 提醒發送失敗")


def deliver_trade_plan_event(store, user_id, event_id, plan, *, allowed_users, push_fn, build_flex=None):
    """選擇性 LINE 推播：站內先有事件，只有 opt-in 才寄送。

    Delivery states: pending -> sending -> sent | failed | unknown.
    - Claim with CAS (document updateTime); two workers racing: loser sees
      sending/sent and stops (no duplicate push, no infinite retry).
    - Explicit provider rejection -> failed (retryable later).
    - Timeout/unknown or record-after-push failure -> unknown (stop auto retry,
      station message retained; never misreport sent, never blind-resend).
    - No exactly-once claim (see spec 8.1); event_id is the stable retry key.
    Returns delivery status string.
    """
    try:
        from stock_papi.config.capabilities import conditional_advice_allowed as _allowed
    except Exception:
        return "skipped"
    allowed = frozenset(allowed_users or ())

    def _find(current):
        assistant = current.get("assistant") if isinstance(current, dict) else None
        if not isinstance(assistant, dict):
            return None, None
        for event in assistant.get("events") or []:
            if isinstance(event, dict) and event.get("event_id") == event_id:
                return assistant, event
        return assistant, None

    try:
        state, _ = store.load(user_id)
    except Exception:
        return "skipped"
    assistant, event = _find(state)
    if event is None:
        return "skipped"
    # Re-check exit/cancel/opt-in immediately before sending.
    if not _allowed(f"line:{user_id}", allowed):
        return "skipped"
    if not bool(assistant.get("line_notifications_enabled")):
        return "skipped"
    cancelled = False
    for ev in assistant.get("events") or []:
        if isinstance(ev, dict) and ev.get("action") == "cancel_plan" and (ev.get("detail") or {}).get("plan_id") == event.get("plan_id"):
            cancelled = True
    if cancelled:
        return "skipped"
    delivery = str((event.get("delivery") or {}).get("status") or event.get("delivery_status") or "pending")
    if delivery in {"sent", "unknown", "sending"}:
        return delivery

    # CAS claim: pending/failed -> sending.
    def _claim(current):
        _assistant, _event = _find(current)
        if _event is None:
            raise ValueError("event_gone")
        current_status = str((_event.get("delivery") or {}).get("status") or _event.get("delivery_status") or "pending")
        if current_status in {"sent", "unknown", "sending"}:
            raise ValueError("already_claimed")
        _event["delivery"] = {"status": "sending"}
    try:
        store.update(user_id, _claim)
    except Exception:
        # Lost the race or store unavailable: never push twice.
        try:
            state2, _ = store.load(user_id)
            _, ev2 = _find(state2)
            if ev2 is not None:
                return str((ev2.get("delivery") or {}).get("status") or "sending")
        except Exception:
            pass
        return "sending"

    # Build minimal flex (no rich-menu changes).
    contents = None
    try:
        flex_builder = build_flex or __import__(
            "stock_papi.integrations.line.flex", fromlist=["build_trade_plan_push_flex"]).build_trade_plan_push_flex
        contents = flex_builder(
            reason=str((event.get("reasons") or ["條件變動"])[0]),
            data_as_of=str(plan.get("data_as_of") or ""),
            status=str(event.get("new_status") or event.get("event_type") or ""),
            plan_url="/account/trading",
            symbol=str(plan.get("symbol") or ""))
    except Exception:
        contents = {"type": "text", "text": "交易計畫更新，請查看 /account/trading"}

    # Push with stable idempotency key = event_id (retry key, not exactly-once proof).
    try:
        if push_fn is None:
            raise ValueError("push_unavailable")
        push_fn(user_id, contents, event_id)
    except Exception as exc:
        message = str(exc or "")
        explicit = any(term in message.lower() for term in ("reject", "refus", "invalid", "forbidden", "bad request", "400", "403"))
        timeout_like = any(term in message.lower() for term in ("timeout", "timed out", "unknown", "ambiguous"))
        final = "failed" if explicit and not timeout_like else "unknown"
        # Timeout/ambiguous after-accept: stop auto retry, keep station message.
        if not timeout_like and "timeout" in message.lower():
            final = "unknown"

        def _record_fail(current):
            _, ev = _find(current)
            if ev is None:
                return
            ev["delivery"] = {"status": final}
        try:
            store.update(user_id, _record_fail)
        except Exception:
            pass
        return final

    def _record_sent(current):
        _, ev = _find(current)
        if ev is None:
            raise ValueError("event_gone")
        ev["delivery"] = {"status": "sent"}
    try:
        store.update(user_id, _record_sent)
    except Exception:
        # Push accepted but record failed: must NOT misreport sent nor blind-resend.
        def _record_unknown(current):
            _, ev = _find(current)
            if ev is not None:
                ev["delivery"] = {"status": "unknown"}
        try:
            store.update(user_id, _record_unknown)
        except Exception:
            pass
        return "unknown"
    return "sent"
