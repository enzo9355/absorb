import datetime

from line_state import evaluate_alert, top_signals
from stock_papi.integrations.line.flex import build_alert_push_flex


def run_alert_checks(store, analyze_fn, push_fn, today, base_url):
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
            quotes[code] = {
                "code": code, "name": data["name"], "price": float(data["price"]),
                "prob": int(data["prob"]), "trend": data["trend"], "as_of": data["as_of"],
            }
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
        signal_items = top_signals(watched)
        hits = []
        for alert in observed.get("alerts", []):
            quote = quotes.get(alert.get("code"))
            if (
                not alert.get("enabled")
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

