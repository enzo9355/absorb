import datetime

from stock_papi.integrations.line import press_block as pb
from stock_papi.shared.formatting import format_sentiment_summary as _format_sentiment_summary
from stock_papi.services.recommendation_engine import recommend_analysis


ABSORB_NAVY = pb.INK
ABSORB_INK = pb.INK
ABSORB_MUTED = pb.MUTED
ABSORB_SURFACE = pb.PAPER


def _observation_trend_label(value):
    return {
        "above_ma20_ma60": "站上 MA20 與 MA60",
        "above_ma20": "站上 MA20",
        "below_ma60": "低於 MA60",
        "mixed": "均線交錯",
    }.get(value, "資料不足")


def _stock_observation_bubble(code, name, body, url, watched):
    return pb.bubble(
        f"{name} ({code})",
        body,
        footer=pb.button_stack([
            pb.button(
                "移除關注" if watched else "加入關注",
                {
                    "type": "postback",
                    "data": f"watch:{'remove' if watched else 'add'}:{code}",
                },
            ),
            pb.button(
                "設定實況提醒",
                {"type": "postback", "data": f"alert:menu:{code}"},
            ),
            pb.button(
                "查看完整觀察",
                {"type": "uri", "uri": url},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="mega",
        eyebrow_text="ABSORB｜市場觀察",
    )


def _format_price_or_unavailable(value):
    try:
        if value is None:
            return "資料不足"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "資料不足"


def build_stock_observation_flex(code, name, data, url, watched=False):
    """Render verified actual-market fields without model or backtest content."""
    data = data if isinstance(data, dict) else {}
    if data.get("observation_kind") in {
        "officially_suspended",
        "official_no_regular_trade",
    }:
        body = [
            pb.eyebrow(str(data.get("status_label") or "暫停交易")),
            pb.disclaimer(f"官方狀態驗證日 {data.get('observation_as_of') or '待更新'}"),
        ]
        if data.get("last_regular_close") is not None:
            body.append(pb.disclaimer(
                "最後正常交易收盤 "
                f"{_format_price_or_unavailable(data.get('last_regular_close'))}"
                f"（{data.get('latest_regular_price_date') or '待更新'}）"
            ))
        return _stock_observation_bubble(code, name, body, url, watched)
    risk_events = [
        str(value)[:120]
        for value in data.get("risk_events", [])
        if isinstance(value, str) and value.strip()
    ][:3]
    try:
        volume_ratio_text = (
            f"{float(data.get('volume_ratio')):.2f}"
            if data.get("volume_ratio") is not None
            else "資料不足"
        )
    except (TypeError, ValueError):
        volume_ratio_text = "資料不足"
    try:
        change_text = (
            f"{float(data.get('change_pct')):+.2f}%"
            if data.get("change_pct") is not None
            else "資料不足"
        )
    except (TypeError, ValueError):
        change_text = "資料不足"
    body = [
        pb.eyebrow("AI 預測研究中"),
        pb.disclaimer("目前只顯示已驗證的市場觀察資料。"),
        {"type": "separator", "margin": "md", "color": pb.RULE},
        pb.kv_table([
            (
                "最新收盤",
                _format_price_or_unavailable(data.get("price")),
            ),
            (
                "均線狀態",
                _observation_trend_label(data.get("trend_observation")),
            ),
            (
                "量比",
                volume_ratio_text,
            ),
        ]),
        pb.disclaimer(f"資料日期 {data.get('as_of') or '待更新'}"),
    ]
    if data.get("change_pct") is not None:
        body.insert(
            4,
            pb.kv_table([(
                "日變動",
                change_text,
                pb.delta_color(data.get("change_pct")),
            )]),
        )
    if risk_events:
        body.extend(
            [
                {"type": "separator", "margin": "md", "color": pb.RULE},
                pb.headline("已觸發事件", size="md"),
                *[
                    pb.disclaimer(f"• {event}")
                    for event in risk_events
                ],
            ]
        )
    return _stock_observation_bubble(code, name, body, url, watched)


def _trend_delta_value(trend):
    text = str(trend or "")
    if "多" in text and "空" not in text:
        return 1
    if "空" in text and "多" not in text:
        return -1
    return 0


def _safe_number(value):
    try:
        if value is None:
            return None
        number = float(value)
        import math as _math
        return number if _math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def build_stock_flex_message(code, name, data, url, watched=False):
    data = data if isinstance(data, dict) else {}
    prob = _safe_number(data.get("prob"))
    s_score = _safe_number(data.get("s_score"))
    price = _safe_number(data.get("price"))
    if prob is None or price is None or not isinstance(data.get("trend"), str):
        return _empty_line_bubble(
            f"{name} ({code})",
            f"此標的資料不足，無法產生完整分析（資料日期 {data.get('as_of') or '待更新'}）。請等待下一次收盤更新。",
        )
    color_prob = pb.delta_color(prob - 50)
    color_s = pb.delta_color(s_score - 50 if s_score is not None else 0)
    color_trend = pb.delta_color(_trend_delta_value(data.get("trend")))
    sentiment_summary = _format_sentiment_summary(data)

    body_contents = []
    try:
        tz_taipei = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
        today = datetime.datetime.now(tz_taipei).date()
        as_of_date = datetime.date.fromisoformat(data["as_of"])
        if (today - as_of_date).days >= 1:
            body_contents.append(
                pb.eyebrow(f"資料延遲：此預測基於 {data['as_of']} 的市場數據。")
            )
    except Exception:
        pass

    recommendation = data.get("recommendation")
    if not isinstance(recommendation, dict):
        try:
            recommendation = recommend_analysis(
                data,
                current_date=datetime.date.fromisoformat(str(data.get("as_of"))),
            ).to_dict()
        except Exception:
            try:
                recommendation = recommend_analysis(data).to_dict()
            except Exception:
                recommendation = {"action": "資料不足", "headline": "目前無法取得足夠資料進行推薦"}
    if not isinstance(recommendation, dict) or not recommendation.get("action"):
        recommendation = {"action": "資料不足", "headline": "目前無法取得足夠資料進行推薦"}
    output_label = data.get("model_output_label") or "五日上漲機率"
    output_suffix = "%" if output_label == "五日上漲機率" else ""
    s_status = data.get("s_status") or "資料不足"
    s_score_text = f"{s_score:.1f}" if s_score is not None else "資料不足"
    body_contents.extend([
        pb.headline(str(recommendation.get("action", "資料不足"))),
        pb.disclaimer(str(recommendation.get("headline", "目前無法取得足夠資料"))),
        {"type": "separator", "margin": "md", "color": pb.RULE},
        pb.kv_table([
            ("最新收盤", f"{price:.2f}"),
            ("當前趨勢", data.get("trend"), color_trend),
            ("新聞／輿論情緒", f"{s_status} ({s_score_text})", color_s),
            (output_label, f"{prob:g}{output_suffix}", color_prob),
        ]),
        pb.disclaimer(sentiment_summary),
        *([pb.eyebrow(str(data["calibration_notice"]))]
          if data.get("calibration_notice") else []),
    ])

    return pb.bubble(
        f"{name} ({code})",
        body_contents,
        footer=pb.button_stack([
            pb.button(
                "移除關注" if watched else "加入關注",
                {
                    "type": "postback",
                    "data": f"watch:{'remove' if watched else 'add'}:{code}",
                },
            ),
            pb.button(
                "設定提醒",
                {"type": "postback", "data": f"alert:menu:{code}"},
            ),
            pb.button(
                "投資試算",
                {"type": "postback", "data": f"calc:menu:{code}"},
            ),
            pb.button(
                "查看完整分析",
                {"type": "uri", "uri": url},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="mega",
        eyebrow_text="ABSORB｜個股研究",
    )


def _empty_line_bubble(title, description, action=None):
    footer = None
    if action:
        footer = pb.button_stack([pb.button(action.get("label", "查股票"), action)])
    return pb.bubble(
        title,
        [pb.disclaimer(description)],
        footer=footer,
        size="kilo",
        eyebrow_text="ABSORB｜空狀態",
    )


def _watchlist_card(item, snapshot, base_url, empty_detail="待收盤更新"):
    item = item if isinstance(item, dict) else {}
    code = str(item.get("code") or "")
    name = str(item.get("name") or code or "未知標的")
    if isinstance(snapshot, dict):
        label = snapshot.get("model_output_label") or "五日上漲機率"
        suffix = "%" if label == "五日上漲機率" else ""
        price = _safe_number(snapshot.get("price"))
        price_text = f"{price:.2f}" if price is not None else "資料不足"
        prob = snapshot.get("prob")
        prob_text = f"{prob}{suffix}" if isinstance(prob, (int, float)) else "資料不足"
        rows = [
            ("收盤價", price_text),
            (label, prob_text),
            ("趨勢", str(snapshot.get("trend") or "資料不足")),
            ("資料日期", str(snapshot.get("as_of") or "待更新")),
        ]
    else:
        rows = [("狀態", str(empty_detail))]
    return pb.bubble(
        f"{name} ({code})",
        [pb.kv_table(rows)],
        footer=pb.button_stack([
            pb.button(
                "移除關注",
                {"type": "postback", "data": f"watch:remove:{code}"},
            ),
            pb.button(
                "設定提醒",
                {"type": "postback", "data": f"alert:menu:{code}"},
            ),
            pb.button(
                "查看完整分析",
                {"type": "uri", "uri": f"{base_url.rstrip('/')}/stock/{code}"},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="kilo",
        eyebrow_text="ABSORB｜我的關注",
    )


def build_watchlist_flex(state, base_url):
    state = state if isinstance(state, dict) else {}
    raw_watchlist = state.get("watchlist", []) or []
    watchlist = [
        item for item in raw_watchlist
        if isinstance(item, dict) and item.get("code")
    ][:12]
    if not watchlist:
        return _empty_line_bubble(
            "我的關注",
            "尚未加入關注股票。請先查詢個股，再點選「加入關注」。",
            {"type": "message", "label": "查股票", "text": "2330"},
        )
    signals = state.get("signals", {})
    signal_items = signals.get("items", []) if isinstance(signals, dict) else []
    snapshots = {
        item.get("code"): item
        for item in (signal_items or [])
        if isinstance(item, dict) and item.get("code")
    }
    return {
        "type": "carousel",
        "contents": [
            _watchlist_card(item, snapshots.get(item.get("code")), base_url)
            for item in watchlist
        ],
    }


def build_observation_watchlist_flex(state, base_url):
    watchlist = [
        item for item in state.get("watchlist", [])
        if isinstance(item, dict) and item.get("code") and item.get("name")
    ][:12]
    if not watchlist:
        return _empty_line_bubble(
            "我的關注",
            "尚未加入關注股票。請先查詢個股，再點選「加入關注」。",
            {"type": "message", "label": "查股票", "text": "2330"},
        )
    return {
        "type": "carousel",
        "contents": [
            _watchlist_card(
                item, None, base_url, "開啟個股頁查看最新已驗證觀察。"
            )
            for item in watchlist
        ],
    }


def _alert_condition_text(alert):
    alert = alert if isinstance(alert, dict) else {}
    kind = alert.get("kind")
    value = _safe_number(alert.get("value"))
    value_text = f"{value:g}" if value is not None else "資料不足"
    if kind in {"price", "price_above"}:
        return f"收盤價站上 {value_text}"
    if kind == "price_below":
        return f"收盤價跌破 {value_text}"
    if kind == "probability":
        return f"模型輸出達到 {value_text}"
    return f"趨勢為{alert.get('value') or '資料不足'}"


def _alert_management_card(alert):
    alert = alert if isinstance(alert, dict) else {}
    name = str(alert.get("name") or alert.get("code") or "未知標的")
    code = str(alert.get("code") or "")
    alert_id = str(alert.get("id") or "")
    return pb.bubble(
        f"{name} ({code})",
        [pb.eyebrow("提醒管理"), pb.disclaimer(_alert_condition_text(alert))],
        footer=pb.button_stack([
            pb.button(
                "取消提醒",
                {"type": "postback", "data": f"alert:remove:{alert_id}"},
            ),
        ]),
        size="kilo",
        eyebrow_text="ABSORB｜提醒管理",
    )


def build_alerts_flex(state, prediction_allowed=True):
    state = state if isinstance(state, dict) else {}
    alerts = [
        alert for alert in (state.get("alerts", []) or [])
        if isinstance(alert, dict)
        and alert.get("enabled", True)
        and (prediction_allowed or alert.get("kind") != "probability")
        and alert.get("code")
    ][:12]
    if not alerts:
        return _empty_line_bubble("提醒管理", "尚未設定提醒。請先查詢個股，再點選「設定提醒」。")
    return {"type": "carousel", "contents": [_alert_management_card(alert) for alert in alerts]}


def build_alert_menu_flex(code, name, prediction_allowed=True):
    choices = [
        ("站上收盤價", f"alert:start:{code}:price_above"),
        ("跌破收盤價", f"alert:start:{code}:price_below"),
        ("趨勢為多頭", f"alert:trend:{code}:多頭"),
        ("趨勢為空頭", f"alert:trend:{code}:空頭"),
    ]
    if prediction_allowed:
        choices.insert(
            2,
            ("上漲機率門檻", f"alert:start:{code}:probability"),
        )
    return pb.bubble(
        "設定提醒",
        [
            pb.headline(f"{name} ({code})"),
            *[
                pb.button(label, {"type": "postback", "data": payload})
                for label, payload in choices
            ],
        ],
        size="kilo",
        eyebrow_text="ABSORB｜提醒管理",
    )


def build_calculator_menu_flex(code, name):
    choices = [("1 萬", 10000), ("5 萬", 50000), ("10 萬", 100000)]
    return pb.bubble(
        f"{name} 投資試算",
        [
            pb.disclaimer("請選擇投入金額，或點自訂金額查看輸入格式。"),
            *[
                pb.button(
                    label,
                    {"type": "postback", "data": f"calc:amount:{code}:{amount}"},
                )
                for label, amount in choices
            ],
            pb.button(
                "自訂金額",
                {"type": "postback", "data": f"calc:custom:{code}"},
            ),
        ],
        size="kilo",
        eyebrow_text="ABSORB｜投資試算",
    )


def _signal_card(item, base_url):
    item = item if isinstance(item, dict) else {}
    code = str(item.get("code") or "")
    name = str(item.get("name") or code or "未知標的")
    label = item.get("model_output_label") or "五日上漲機率"
    suffix = "%" if label == "五日上漲機率" else ""
    price = _safe_number(item.get("price"))
    price_text = f"{price:.2f}" if price is not None else "資料不足"
    prob = item.get("prob")
    prob_text = f"{prob}{suffix}" if isinstance(prob, (int, float)) else "資料不足"
    return pb.bubble(
        f"{name} ({code})",
        [pb.kv_table([
            ("收盤價", price_text),
            (label, prob_text),
            ("趨勢", str(item.get("trend") or "資料不足")),
            ("資料日期", str(item.get("as_of") or "待更新")),
        ])],
        footer=pb.button_stack([
            pb.button(
                "查看完整分析",
                {"type": "uri", "uri": f"{base_url.rstrip('/')}/stock/{code}"},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="kilo",
        eyebrow_text="ABSORB｜強勢訊號",
    )


def build_strong_signals_flex(state, base_url):
    state = state if isinstance(state, dict) else {}
    signals = state.get("signals", {})
    raw_items = signals.get("items", []) if isinstance(signals, dict) else []
    items = [item for item in (raw_items or []) if isinstance(item, dict) and item.get("code")][:5]
    if not items:
        return _empty_line_bubble("強勢訊號", "尚無最新強勢訊號，請等待下一次收盤更新。")
    return {
        "type": "carousel",
        "contents": [_signal_card(item, base_url) for item in items],
    }


def build_alert_push_flex(hits, base_url):
    safe_hits = [
        hit for hit in (hits or [])
        if isinstance(hit, dict)
        and isinstance(hit.get("alert"), dict)
        and isinstance(hit.get("quote"), dict)
        and hit.get("quote", {}).get("code")
    ]
    if not 1 <= len(safe_hits) <= 12:
        raise ValueError("LINE Flex carousel requires 1 to 12 bubbles")

    def bubble(hit):
        alert, quote = hit["alert"], hit["quote"]
        alert_value = _safe_number(alert.get("value"))
        alert_value_text = f"{alert_value:g}" if alert_value is not None else "資料不足"
        quote_price = _safe_number(quote.get("price"))
        quote_price_text = f"{quote_price:.2f}" if quote_price is not None else "資料不足"
        if alert.get("kind") in {"price", "price_above"}:
            condition = f"條件：收盤價站上 {alert_value_text}"
            current = f"今日收盤價：{quote_price_text}"
        elif alert.get("kind") == "price_below":
            condition = f"條件：收盤價跌破 {alert_value_text}"
            current = f"今日收盤價：{quote_price_text}"
        elif alert.get("kind") == "probability":
            label = quote.get("model_output_label") or "模型輸出"
            condition = f"條件：{label}達到 {alert_value_text}"
            current = f"目前{label}：{quote.get('prob') if isinstance(quote.get('prob'), (int, float)) else '資料不足'}"
        else:
            condition = f"條件：趨勢為{alert.get('value') or '資料不足'}"
            current = f"目前趨勢：{quote.get('trend') or '資料不足'}"
        return pb.bubble(
            "股票提醒",
            [
                pb.headline(f"{quote.get('name') or quote.get('code')} ({quote.get('code')})"),
                pb.disclaimer(condition),
                pb.headline(current, color=pb.POSITIVE, size="sm"),
                pb.disclaimer(f"資料日期：{quote.get('as_of') or '待更新'}"),
            ],
            footer=pb.button_stack([
                pb.button(
                    "查看完整分析",
                    {"type": "uri", "uri": f"{base_url.rstrip('/')}/stock/{quote['code']}"},
                    style="primary",
                    color=pb.BRICK,
                ),
            ]),
            size="kilo",
            eyebrow_text="ABSORB｜股票提醒",
        )

    return {"type": "carousel", "contents": [bubble(hit) for hit in safe_hits]}


def build_line_summary_card(title, lines, cta_label, url, accent=pb.BRICK, action=None):
    """建立只有一個主要動作的 LINE 摘要卡。"""
    action = action or {"type": "uri", "label": cta_label, "uri": url}
    return pb.bubble(
        title,
        [
            pb.headline(title, size="lg"),
            *[pb.disclaimer(line) for line in lines],
        ],
        footer=pb.button_stack([
            pb.button(cta_label, action, style="primary", color=accent),
        ]),
        size="kilo",
        eyebrow_text="ABSORB｜市場觀察",
    )


def build_line_navigation_flex(base_url):
    """Rich Menu 入口的可預覽 Flex 版本。"""
    root = base_url.rstrip("/")
    entries = [
        ("看大盤", "查看市場報酬、廣度與風險狀態", "查看市場", {"type": "uri", "label": "查看市場", "uri": f"{root}/market"}),
        ("看產業", "查看產業實際報酬與市場廣度", "查看產業", {"type": "uri", "label": "查看產業", "uri": f"{root}/industries"}),
        ("查自選", "自選股票清單", "開啟關注", {"type": "message", "label": "開啟關注", "text": "我的關注"}),
        ("設提醒", "管理收盤價與均線趨勢通知", "管理提醒", {"type": "message", "label": "管理提醒", "text": "提醒管理"}),
        ("查股票", "輸入股票代碼查看實際資料", "查台積電", {"type": "message", "label": "查台積電", "text": "2330"}),
        ("市場觀察", "查看完整市場與事件頁面", "開啟觀察", {"type": "uri", "label": "開啟觀察", "uri": f"{root}/dashboard"}),
    ]
    return {
        "type": "carousel",
        "contents": [build_line_summary_card(title, [description], cta, root, action=action) for title, description, cta, action in entries],
    }


def build_calculator_help_flex():
    return build_line_summary_card(
        "投資試算",
        [
            "先輸入股票代碼，例如 2330。",
            "查詢結果會出現「投資試算」按鈕，可直接選 1 萬 / 5 萬 / 10 萬。",
            "自訂金額可輸入：試算 2330 100000",
        ],
        "輸入 2330 開始",
        "2330",
        action={"type": "message", "label": "輸入 2330 開始", "text": "2330"},
    )


def build_welcome_flex():
    return pb.bubble(
        "已驗證市場觀察",
        [
            pb.headline(
                "AI 預測研究中；目前正式服務只呈現已驗證的市場實況。",
                size="md",
            ),
            pb.disclaimer(
                "您可以：\n1. 開啟產業實際強弱頁\n2. 直接輸入股票代碼（如 2330）\n3. 輸入「大盤」查看市場實況\n4. 管理關注與收盤價提醒"
            ),
        ],
        footer=pb.button_stack([
            pb.button(
                "新手怎麼看？（教學）",
                {"type": "message", "text": "新手教學"},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="mega",
        eyebrow_text="ABSORB｜市場觀察",
    )


def build_tutorial_flex():
    return pb.bubble(
        "新手快速上手指南",
        [
            pb.headline(
                "正式服務只呈現已發生的市場資料，可先掌握以下三個重點：",
                size="sm",
            ),
            {"type": "separator", "margin": "md", "color": pb.RULE},
            pb.headline("1. 看「市場廣度」", size="md"),
            pb.disclaimer("上漲家數與站上均線比例，可觀察漲勢是否由多數股票共同參與。"),
            pb.headline("2. 看「相對報酬」", size="md"),
            pb.disclaimer("產業報酬扣除同期大盤報酬，只描述已發生的相對強弱。"),
            pb.headline("3. 看「異常事件」", size="md"),
            pb.disclaimer("價格、量能、技術或資料品質超過條件時才列出；事件本身不是買賣指令。"),
        ],
        size="mega",
        eyebrow_text="ABSORB｜教學",
    )
