"""LINE postback and text-message orchestration."""

import re

from linebot.models import FlexSendMessage, TextSendMessage

from absorb.conversation.errors import InputRejected
from absorb.conversation.policies import validate_question
from line_state import (
    StateError,
    StoreError,
    add_alert,
    add_watch,
    consume_pending,
    remove_watch,
    start_pending,
)
from stock_papi.integrations.line.flex import (
    build_alert_menu_flex,
    build_alerts_flex,
    build_calculator_help_flex,
    build_calculator_menu_flex,
    build_line_navigation_flex,
    build_line_summary_card,
    build_observation_watchlist_flex,
    build_stock_observation_flex,
    build_stock_flex_message,
    build_strong_signals_flex,
    build_tutorial_flex,
    build_watchlist_flex,
    build_welcome_flex,
)


def require_same_pending(state, expected_pending):
    if state.get("pending") != expected_pending:
        raise StateError("提醒設定已變更，請重新操作。")


def find_matching_alert(alerts, code, kind, value):
    return next(
        (
            alert
            for alert in alerts
            if alert.get("code") == code
            and (
                alert.get("kind") == kind
                or {alert.get("kind"), kind} <= {"price", "price_above"}
            )
            and alert.get("value") == value
        ),
        None,
    )


def resolve_postback_stock(code, search_stock_code):
    resolved_code, name = search_stock_code(code)
    if (
        resolved_code != code
        or not name
        or (name == code and code != "TAIEX")
    ):
        return None, None
    return resolved_code, name


def handle_postback_impl(event, deps):
    reply_text = deps["reply_text"]
    update_line_state = deps["update_line_state"]
    store_error_text = deps["store_error_text"]
    resolve_stock = deps["resolve_stock"]
    line_bot_api = deps["line_bot_api"]
    analyze = deps["analyze"]
    build_projection_flex = deps["build_projection_flex"]
    current_web_root = deps["current_web_root"]
    find_matching_alert = deps["find_matching_alert"]
    observation_mode = deps.get("observation_mode", False)

    user_id = getattr(getattr(event, "source", None), "user_id", None)
    if not user_id:
        reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        return
    payload = getattr(getattr(event, "postback", None), "data", "")
    stock_match = re.fullmatch(
        r"(?:watch:(?:add|remove)|alert:menu|calc:menu|calc:custom):([A-Za-z0-9-]+)",
        payload,
    )
    calc_amount_match = re.fullmatch(
        r"calc:amount:([A-Za-z0-9-]+):([0-9]+(?:\.[0-9]+)?)", payload
    )
    alert_start_match = re.fullmatch(
        r"alert:start:([A-Za-z0-9-]+):(price|price_above|price_below|probability)",
        payload,
    )
    alert_trend_match = re.fullmatch(
        r"alert:trend:([A-Za-z0-9-]+):(多頭|空頭)", payload
    )
    alert_remove_match = re.fullmatch(r"alert:remove:([0-9a-fA-F]{32})", payload)
    if not any((stock_match, calc_amount_match, alert_start_match, alert_trend_match, alert_remove_match)):
        reply_text(event, "無效的操作，請重新開啟功能選單。")
        return
    if alert_remove_match:
        alert_id = alert_remove_match.group(1)
        found = {"value": False}

        def delete_alert(state):
            alerts = state.get("alerts", [])
            found["value"] = any(item.get("id") == alert_id for item in alerts)
            state["alerts"] = [item for item in alerts if item.get("id") != alert_id]

        try:
            update_line_state(user_id, delete_alert)
            reply_text(event, "提醒已移除。" if found["value"] else "找不到這筆提醒，可能已經移除。")
        except StoreError:
            reply_text(event, store_error_text())
        return
    match = stock_match or calc_amount_match or alert_start_match or alert_trend_match
    code, name = resolve_stock(match.group(1))
    if not code:
        reply_text(event, "找不到這檔股票，請重新查詢後再操作。")
        return
    if payload == f"alert:menu:{code}":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"設定 {name} 提醒",
                contents=build_alert_menu_flex(
                    code, name, prediction_allowed=not observation_mode
                ),
            ),
        )
        return
    if observation_mode and (
        payload.startswith("calc:")
        or (alert_start_match and alert_start_match.group(2) == "probability")
    ):
        reply_text(
            event,
            "AI 預測研究中；目前只提供收盤價與均線趨勢提醒。",
        )
        return
    if payload == f"calc:menu:{code}":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text=f"{name} 投資試算", contents=build_calculator_menu_flex(code, name)),
        )
        return
    if payload == f"calc:custom:{code}":
        reply_text(event, f"請輸入：試算 {code} 100000\n把 100000 換成你的投入金額。")
        return
    if calc_amount_match:
        data = analyze(code)
        if not data:
            reply_text(event, "查無資料，請稍後再試。")
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{name} 投資試算",
                contents=build_projection_flex(
                    code, name, data, calc_amount_match.group(2), current_web_root()
                ),
            ),
        )
        return
    try:
        if payload == f"watch:add:{code}":
            update_line_state(user_id, lambda state: add_watch(state, code, name))
            reply = f"已將 {name} ({code}) 加入關注。"
        elif payload == f"watch:remove:{code}":
            update_line_state(user_id, lambda state: remove_watch(state, code))
            reply = f"已將 {name} ({code}) 移除關注，相關提醒也已移除。"
        elif alert_start_match:
            kind = alert_start_match.group(2)

            def begin_alert(state):
                add_watch(state, code, name)
                start_pending(state, code, name, kind)

            update_line_state(user_id, begin_alert)
            label = {
                "price": "收盤價站上", "price_above": "收盤價站上",
                "price_below": "收盤價跌破",
            }.get(kind, "五日上漲機率（1 到 99）")
            reply = f"請輸入 {name} 的{label}門檻數字，或輸入「取消」。"
        elif alert_trend_match:
            trend = alert_trend_match.group(2)
            created = {"value": False}

            def create_trend_alert(state):
                created["value"] = False
                add_watch(state, code, name)
                if find_matching_alert(state.get("alerts", []), code, "trend", trend):
                    return
                add_alert(state, code, name, "trend", trend)
                created["value"] = True

            update_line_state(user_id, create_trend_alert)
            reply = (
                f"已建立 {name} 趨勢為{trend}時的提醒。"
                if created["value"] else f"{name} 趨勢為{trend}時的提醒已存在。"
            )
        else:
            reply_text(event, "無效的操作，請重新開啟功能選單。")
            return
        reply_text(event, reply)
    except StateError as error:
        reply_text(event, str(error))
    except StoreError:
        reply_text(event, store_error_text())


def _observation_industry_card(snapshot, category, web_root):
    industries = (
        snapshot.get("industry_observations", [])
        if isinstance(snapshot, dict)
        else []
    )
    item = next(
        (
            value for value in industries
            if isinstance(value, dict) and value.get("name") == category
        ),
        None,
    )
    if item is None:
        return build_line_summary_card(
            "產業觀察",
            ["目前沒有這個產業的已驗證觀察資料。"],
            "開啟產業頁",
            f"{web_root}/market-map",
        )
    relative = item.get("relative_return_5d_pct")
    relative_text = (
        f"{float(relative):+.2f}%"
        if isinstance(relative, (int, float)) and not isinstance(relative, bool)
        else "資料不足"
    )
    breadth = item.get("advancing_ratio_pct")
    breadth_text = (
        f"{float(breadth):.1f}%"
        if isinstance(breadth, (int, float)) and not isinstance(breadth, bool)
        else "資料不足"
    )
    return build_line_summary_card(
        f"{category}｜產業觀察",
        [
            f"近 5 日相對大盤報酬：{relative_text}",
            f"單日上漲家數比例：{breadth_text}",
            f"資料日：{snapshot.get('observation_as_of') or '待更新'}",
        ],
        "查看完整產業資料",
        f"{web_root}/market-map",
    )


def _handle_observation_message(
    event, msg, deps, *, current_state, state_load_failed, user_id
):
    reply_text = deps["reply_text"]
    line_store = deps["line_store"]
    line_bot_api = deps["line_bot_api"]
    store_error_text = deps["store_error_text"]
    search_stock_code = deps["search_stock_code"]
    observe = deps["observe"]
    dashboard_snapshot = deps.get("dashboard_snapshot", lambda: None)
    web_root = deps["web_root"]
    request_host_url = deps["request_host_url"]

    if msg.startswith("試算") or msg == "投資試算":
        reply_text(
            event,
            "AI 預測研究中；目前不提供報酬試算。",
        )
        return True
    if msg in ("大盤預測", "大盤", "今日盤勢"):
        data = observe("TAIEX")
        if not data:
            reply_text(event, "已驗證的大盤觀察資料暫時無法取得。")
            return True
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="台股大盤市場觀察",
                contents=build_stock_observation_flex(
                    "TAIEX",
                    "台股大盤（加權指數）",
                    data,
                    f"{web_root}/market",
                ),
            ),
        )
        return True
    if msg in ("預測", "熱門產業", "強勢訊號", "完整分析"):
        title = "個股異常事件" if msg == "強勢訊號" else "產業與市場觀察"
        card = build_line_summary_card(
            title,
            [
                "AI 預測研究中。",
                "目前只顯示已驗證的市場報酬、廣度、量能與異常事件。",
            ],
            "開啟市場觀察",
            f"{web_root}/market-map" if msg != "完整分析" else f"{web_root}/dashboard",
        )
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text=title, contents=card),
        )
        return True
    if msg == "我的關注":
        if line_store is None or state_load_failed:
            reply_text(event, store_error_text())
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="我的關注",
                    contents=build_observation_watchlist_flex(
                        current_state, web_root
                    ),
                ),
            )
        return True
    if msg == "提醒管理":
        if line_store is None or state_load_failed:
            reply_text(event, store_error_text())
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="提醒管理",
                    contents=build_alerts_flex(
                        current_state, prediction_allowed=False
                    ),
                ),
            )
        return True
    if msg == "功能選單":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="ABSORB 功能選單",
                contents=build_line_navigation_flex(web_root),
            ),
        )
        return True
    if msg == "產業列表":
        categories = list(deps["industry_map"].keys())
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="\n".join(
                    ["產業分類"] + [
                        f"{index}. {category}"
                        for index, category in enumerate(categories[:100], 1)
                    ]
                )
            ),
        )
        return True
    if msg.startswith("選產業_"):
        category = msg.removeprefix("選產業_")
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{category} 產業觀察",
                contents=_observation_industry_card(
                    dashboard_snapshot(), category, web_root
                ),
            ),
        )
        return True
    if msg.startswith("分類第_") and msg.endswith("頁"):
        card = build_line_summary_card(
            "產業觀察",
            ["請開啟產業頁查看目前可用的已驗證產業資料。"],
            "開啟產業頁",
            f"{web_root}/market-map",
        )
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="產業觀察", contents=card),
        )
        return True
    if msg in ("免責聲明", "新手教學"):
        if msg == "免責聲明":
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="本系統目前只呈現市場觀察資料，不構成投資建議，投資盈虧請自負。"
                ),
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="ABSORB 市場觀察指南",
                    contents=build_tutorial_flex(),
                ),
            )
        return True

    code, name = search_stock_code(msg)
    if not code:
        return False
    data = observe(code)
    if not data:
        reply_text(event, "已驗證的個股觀察資料暫時無法取得。")
        return True
    watched = bool(
        current_state
        and any(
            item.get("code") == code
            for item in current_state.get("watchlist", [])
            if isinstance(item, dict)
        )
    )
    url = f"{request_host_url}stock/{code}".replace("http://", "https://")
    line_bot_api.reply_message(
        event.reply_token,
        FlexSendMessage(
            alt_text=f"{name}（{code}）市場觀察",
            contents=build_stock_observation_flex(
                code, name, data, url, watched=watched
            ),
        ),
    )
    return True


def handle_message_impl(event, deps):
    reply_text = deps["reply_text"]
    line_store = deps["line_store"]
    line_bot_api = deps["line_bot_api"]
    get_line_state_bounded = deps["get_line_state_bounded"]
    update_line_state = deps["update_line_state"]
    require_same_pending = deps["require_same_pending"]
    find_matching_alert = deps["find_matching_alert"]
    store_error_text = deps["store_error_text"]
    now = deps["now"]
    is_crypto_query = deps["is_crypto_query"]
    search_stock_code = deps["search_stock_code"]
    analyze = deps["analyze"]
    build_projection_flex = deps["build_projection_flex"]
    build_category_quick_reply = deps["build_category_quick_reply"]
    industry_map = deps["industry_map"]
    load_sector_signal_snapshot = deps["load_sector_signal_snapshot"]
    build_sector_signal_carousel = deps["build_sector_signal_carousel"]
    web_root = deps["web_root"]
    request_host_url = deps["request_host_url"]
    conversation = deps["conversation"]
    is_fixed_command = deps.get("is_fixed_command", lambda _message: False)
    record_metric = deps.get("record_metric", lambda _name: None)
    observation_mode = deps.get("observation_mode", False)

    try:
        msg = validate_question(event.message.text)
    except InputRejected as exc:
        reply_text(event, str(exc))
        return
    user_id = getattr(getattr(event, "source", None), "user_id", None)
    current_state = None
    state_load_failed = False
    if line_store is not None and user_id:
        try:
            current_state = get_line_state_bounded(user_id)
        except StoreError:
            state_load_failed = True
    if current_state and current_state.get("pending"):
        record_metric("command_requests")
        expected_pending = dict(current_state["pending"])
        if observation_mode and expected_pending.get("kind") == "probability":
            try:
                def cancel_probability_pending(state):
                    require_same_pending(state, expected_pending)
                    state["pending"] = None

                update_line_state(user_id, cancel_probability_pending)
            except StateError as error:
                reply_text(event, str(error))
                return
            except StoreError:
                reply_text(event, store_error_text())
                return
            reply_text(
                event,
                "AI 預測仍在研究中，原機率提醒設定已取消；請改用收盤價或均線趨勢提醒。",
            )
            return
        try:
            if msg == "取消":
                def cancel_pending(state):
                    require_same_pending(state, expected_pending)
                    state["pending"] = None
                update_line_state(user_id, cancel_pending)
                reply_text(event, "已取消提醒設定。")
            else:
                outcome = {"alert": None, "created": False, "expired": False}

                def finish_pending(state):
                    outcome.update(alert=None, created=False, expired=False)
                    require_same_pending(state, expected_pending)
                    timestamp = now()
                    if expected_pending["expires_at"] <= timestamp:
                        state["pending"] = None
                        outcome["expired"] = True
                        return
                    preview_state = {"pending": dict(expected_pending), "alerts": []}
                    preview = consume_pending(preview_state, msg, now=timestamp)
                    duplicate = find_matching_alert(
                        state.get("alerts", []), preview["code"], preview["kind"], preview["value"]
                    )
                    if duplicate:
                        state["pending"] = None
                        outcome["alert"] = duplicate
                        return
                    outcome["alert"] = consume_pending(state, msg, now=timestamp)
                    outcome["created"] = True

                update_line_state(user_id, finish_pending)
                if outcome["expired"]:
                    reply_text(event, "提醒設定已逾時，請重新設定。")
                else:
                    alert = outcome["alert"]
                    label = {
                        "price": "收盤價站上", "price_above": "收盤價站上",
                        "price_below": "收盤價跌破",
                    }.get(alert["kind"], "五日上漲機率")
                    reply = (
                        f"已建立 {alert['name']} 的{label}提醒。"
                        if outcome["created"] else f"{alert['name']} 的{label}提醒已存在。"
                    )
                    reply_text(event, reply)
        except StateError as error:
            reply_text(event, str(error))
        except StoreError:
            reply_text(event, store_error_text())
        return

    legacy_ai_match = re.fullmatch(r"(?i)papi\s*(.+)", msg)
    if legacy_ai_match:
        record_metric("command_requests")
        prompt = legacy_ai_match.group(1).strip()
        if is_crypto_query(prompt):
            reply_text(event, "ABSORB 分析目前不支援虛擬貨幣。")
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            reply_text(event, conversation(prompt, user_id))
        return

    if is_fixed_command(msg):
        record_metric("command_requests")

    if observation_mode and _handle_observation_message(
        event,
        msg,
        deps,
        current_state=current_state,
        state_load_failed=state_load_failed,
        user_id=user_id,
    ):
        return

    calc_text = re.fullmatch(r"試算\s+([A-Za-z0-9-]+)\s+([0-9]+(?:\.[0-9]+)?)", msg)
    if calc_text:
        code, name = search_stock_code(calc_text.group(1))
        if not code:
            reply_text(event, "找不到這檔股票，請重新查詢後再操作。")
            return
        data = analyze(code)
        if not data:
            reply_text(event, "查無資料，請稍後再試。")
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{name} 投資試算",
                contents=build_projection_flex(code, name, data, calc_text.group(2), web_root),
            ),
        )
        return
    if msg.startswith("試算"):
        reply_text(event, "請用：試算 2330 100000，或先查詢股票後點選「投資試算」。")
        return
    if msg in ("大盤預測", "大盤", "今日盤勢"):
        data = analyze("TAIEX")
        if not data:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大盤資料暫時無法取得，請稍後再試。"))
            return
        flex_content = build_stock_flex_message(
            "TAIEX", "台股大盤 (加權指數)", data, f"{web_root}/market"
        )
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="📊 台股大盤預測出爐，點擊查看！", contents=flex_content),
        )
    elif msg in ("預測", "熱門產業"):
        quick_reply, _ = build_category_quick_reply(1)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="請選擇產業板塊", contents=build_welcome_flex(), quick_reply=quick_reply),
        )
    elif msg == "我的關注":
        if line_store is None or state_load_failed:
            reply_text(event, store_error_text())
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text="我的關注", contents=build_watchlist_flex(current_state, web_root)),
            )
    elif msg == "強勢訊號":
        if line_store is None or state_load_failed:
            reply_text(event, store_error_text())
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text="強勢訊號", contents=build_strong_signals_flex(current_state, web_root)),
            )
    elif msg == "提醒管理":
        if line_store is None or state_load_failed:
            reply_text(event, store_error_text())
        elif not user_id:
            reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text="提醒管理", contents=build_alerts_flex(current_state)),
            )
    elif msg == "完整分析":
        card = build_line_summary_card(
            "量化分析總覽", ["從市場摘要、強勢訊號與產業雷達開始判讀。"],
            "開啟完整分析", f"{web_root}/dashboard",
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="開啟完整分析", contents=card))
    elif msg == "投資試算":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="投資試算", contents=build_calculator_help_flex()),
        )
    elif msg == "功能選單":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="ABSORB 功能選單", contents=build_line_navigation_flex(web_root)),
        )
    elif msg.startswith("分類第_") and msg.endswith("頁"):
        try:
            page = int(msg.replace("分類第_", "").replace("頁", ""))
        except ValueError:
            page = 1
        quick_reply, _ = build_category_quick_reply(page)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="請選擇產業板塊", contents=build_welcome_flex(), quick_reply=quick_reply),
        )
    elif msg == "產業列表":
        lines = ["📚 產業分類總表\n"] + [
            f"{index}. {category}" for index, category in enumerate(industry_map.keys(), 1)
        ]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(lines[:120])))
    elif msg.startswith("選產業_"):
        category = msg.replace("選產業_", "")
        try:
            snapshot = load_sector_signal_snapshot(line_store) if line_store else None
        except StoreError:
            snapshot = None
        items = (snapshot or {}).get("sectors", {}).get(category, [])
        if items:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text=f"{category} 每日產業預測",
                    contents=build_sector_signal_carousel(category, items),
                ),
            )
        else:
            reply_text(event, "產業資料尚未更新，請稍後再試。你也可以直接輸入股票代碼查詢個股。")
    elif msg == "免責聲明":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="本系統資訊僅供研究參考，不構成投資建議，投資盈虧請自負。"),
        )
    elif msg == "新手教學":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="🎓 新手快速上手指南", contents=build_tutorial_flex()),
        )
    else:
        code, name = search_stock_code(msg)
        if code:
            record_metric("command_requests")
            data = analyze(code)
            if not data:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="查無資料，請稍後再試。"))
                return
            url = f"{request_host_url}stock/{code}".replace("http://", "https://")
            watched = bool(
                current_state
                and any(item.get("code") == code for item in current_state.get("watchlist", []))
            )
            flex_content = build_stock_flex_message(code, name, data, url, watched=watched)
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text=f"📊 {name} ({code}) 預測出爐，點擊查看！", contents=flex_content),
            )
        elif getattr(getattr(event, "source", None), "type", "user") == "user":
            if not user_id:
                reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
            else:
                reply_text(event, conversation(msg, user_id))
