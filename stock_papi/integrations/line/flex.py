import datetime

from stock_papi.shared.formatting import format_sentiment_summary as _format_sentiment_summary
from stock_papi.services.recommendation_engine import recommend_analysis


def build_stock_flex_message(code, name, data, url, watched=False):
    color_prob = "#10b981" if data['prob'] >= 50 else "#ef4444"
    color_s = "#10b981" if data['s_score'] >= 50 else "#ef4444"
    color_trend = "#10b981" if "多" in data['trend'] else "#ef4444"
    sentiment_summary = _format_sentiment_summary(data)

    body_contents = []
    try:
        tz_taipei = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
        today = datetime.datetime.now(tz_taipei).date()
        as_of_date = datetime.date.fromisoformat(data["as_of"])
        if (today - as_of_date).days >= 1:
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "backgroundColor": "#fffbeb",
                "borderColor": "#fef3c7",
                "borderWidth": "1px",
                "cornerRadius": "6px",
                "paddingAll": "8px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"⚠️ 數據延遲：此預測基於 {data['as_of']} 的市場數據。",
                        "color": "#b45309",
                        "size": "xs",
                        "wrap": True,
                        "weight": "bold"
                    }
                ]
            })
    except Exception:
        pass

    recommendation = data.get("recommendation")
    if not isinstance(recommendation, dict):
        try:
            recommendation = recommend_analysis(
                data,
                current_date=datetime.date.fromisoformat(str(data.get("as_of"))),
            ).to_dict()
        except (TypeError, ValueError):
            recommendation = recommend_analysis(data).to_dict()
    body_contents.extend([
        {
            "type": "text",
            "text": str(recommendation["action"]),
            "color": "#0f172a",
            "size": "xl",
            "weight": "bold",
            "wrap": True,
        },
        {
            "type": "text",
            "text": str(recommendation["headline"]),
            "color": "#475569",
            "size": "sm",
            "wrap": True,
        },
        {"type": "separator", "margin": "md", "color": "#cbd5e1"},
    ])

    body_contents.extend([
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                { "type": "text", "text": "💰 最新收盤", "color": "#64748b", "size": "sm", "flex": 4 },
                { "type": "text", "text": f"{data['price']:.2f}", "color": "#0f172a", "size": "md", "weight": "bold", "align": "end", "flex": 5 }
            ]
        },
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                { "type": "text", "text": "📈 當前趨勢", "color": "#64748b", "size": "sm", "flex": 4 },
                { "type": "text", "text": data['trend'], "color": color_trend, "size": "md", "weight": "bold", "align": "end", "flex": 5 }
            ]
        },
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                { "type": "text", "text": "🌡 新聞／輿論情緒", "color": "#64748b", "size": "sm", "flex": 4, "wrap": True },
                { "type": "text", "text": f"{data['s_status']} ({data['s_score']:.1f})", "color": color_s, "size": "md", "weight": "bold", "align": "end", "flex": 5 }
            ]
        },
        {
            "type": "text",
            "text": sentiment_summary,
            "color": "#64748b",
            "size": "xs",
            "align": "end",
            "wrap": True
        },
        { "type": "separator", "margin": "md", "color": "#cbd5e1" },
        {
            "type": "box",
            "layout": "horizontal",
            "margin": "md",
            "contents": [
                { "type": "text", "text": "🎯 五日上漲機率", "color": "#0f172a", "size": "md", "weight": "bold", "flex": 4 },
                { "type": "text", "text": f"{data['prob']}%", "color": color_prob, "size": "lg", "weight": "bold", "align": "end", "flex": 5 }
            ]
        }
    ])

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": f"📊 {name} ({code})",
                    "color": "#ffffff",
                    "weight": "bold",
                    "size": "xl"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#f8fafc",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": body_contents
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#f8fafc",
            "paddingAll": "16px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "移除關注" if watched else "加入關注",
                        "data": f"watch:{'remove' if watched else 'add'}:{code}",
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "設定提醒",
                        "data": f"alert:menu:{code}",
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "投資試算",
                        "data": f"calc:menu:{code}",
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#39c6a3",
                    "action": {
                        "type": "uri",
                        "label": "查看完整分析",
                        "uri": url,
                    }
                }
            ]
        }
    }


def _empty_line_bubble(title, description):
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": description, "color": "#64748b", "size": "sm", "wrap": True},
            ],
        },
    }


def _watchlist_card(item, snapshot, base_url):
    code = item["code"]
    name = item["name"]
    if snapshot:
        details = [
            f"收盤價 {snapshot['price']:.2f}",
            f"五日上漲機率 {snapshot['prob']}%",
            f"趨勢 {snapshot['trend']}",
            f"資料日期 {snapshot['as_of']}",
        ]
    else:
        details = ["待收盤更新"]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{name} ({code})", "weight": "bold", "size": "lg", "wrap": True},
                *[
                    {"type": "text", "text": detail, "color": "#64748b", "size": "sm", "wrap": True}
                    for detail in details
                ],
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "14px", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "secondary", "action": {
                    "type": "postback", "label": "移除關注", "data": f"watch:remove:{code}",
                }},
                {"type": "button", "style": "secondary", "action": {
                    "type": "postback", "label": "設定提醒", "data": f"alert:menu:{code}",
                }},
                {"type": "button", "style": "primary", "color": "#39c6a3", "action": {
                    "type": "uri", "label": "查看完整分析",
                    "uri": f"{base_url.rstrip('/')}/stock/{code}",
                }},
            ],
        },
    }


def build_watchlist_flex(state, base_url):
    watchlist = state.get("watchlist", [])[:12]
    if not watchlist:
        return _empty_line_bubble("我的關注", "尚未加入關注股票。請先查詢個股，再點選「加入關注」。")
    snapshots = {
        item.get("code"): item
        for item in state.get("signals", {}).get("items", [])
        if isinstance(item, dict)
    }
    return {
        "type": "carousel",
        "contents": [
            _watchlist_card(item, snapshots.get(item.get("code")), base_url)
            for item in watchlist
        ],
    }


def _alert_condition_text(alert):
    if alert["kind"] in {"price", "price_above"}:
        return f"收盤價站上 {float(alert['value']):g}"
    if alert["kind"] == "price_below":
        return f"收盤價跌破 {float(alert['value']):g}"
    if alert["kind"] == "probability":
        return f"AI 勝率達到 {float(alert['value']):g}%"
    return f"趨勢為{alert['value']}"


def _alert_management_card(alert):
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "提醒管理", "weight": "bold", "size": "sm", "color": "#39c6a3"},
                {"type": "text", "text": f"{alert['name']} ({alert['code']})", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": _alert_condition_text(alert), "color": "#64748b", "size": "sm", "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "14px",
            "contents": [{"type": "button", "style": "secondary", "action": {
                "type": "postback", "label": "取消提醒", "data": f"alert:remove:{alert['id']}",
            }}],
        },
    }


def build_alerts_flex(state):
    alerts = [alert for alert in state.get("alerts", []) if alert.get("enabled", True)][:12]
    if not alerts:
        return _empty_line_bubble("提醒管理", "尚未設定提醒。請先查詢個股，再點選「設定提醒」。")
    return {"type": "carousel", "contents": [_alert_management_card(alert) for alert in alerts]}


def build_alert_menu_flex(code, name):
    choices = [
        ("站上收盤價", f"alert:start:{code}:price_above"),
        ("跌破收盤價", f"alert:start:{code}:price_below"),
        ("AI 勝率門檻", f"alert:start:{code}:probability"),
        ("趨勢為多頭", f"alert:trend:{code}:多頭"),
        ("趨勢為空頭", f"alert:trend:{code}:空頭"),
    ]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"設定 {name} ({code}) 提醒", "weight": "bold", "size": "lg", "wrap": True},
                *[
                    {"type": "button", "style": "secondary", "action": {
                        "type": "postback", "label": label, "data": payload,
                    }}
                    for label, payload in choices
                ],
            ],
        },
    }


def build_calculator_menu_flex(code, name):
    choices = [("1 萬", 10000), ("5 萬", 50000), ("10 萬", 100000)]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{name} 投資試算", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": "請選擇投入金額，或點自訂金額查看輸入格式。", "color": "#64748b", "size": "sm", "wrap": True},
                *[
                    {"type": "button", "style": "secondary", "action": {
                        "type": "postback", "label": label, "data": f"calc:amount:{code}:{amount}",
                    }}
                    for label, amount in choices
                ],
                {"type": "button", "style": "secondary", "action": {
                    "type": "postback", "label": "自訂金額", "data": f"calc:custom:{code}",
                }},
            ],
        },
    }


def _signal_card(item, base_url):
    code = item["code"]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{item['name']} ({code})", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": f"收盤價 {item['price']:.2f}", "color": "#64748b", "size": "sm"},
                {"type": "text", "text": f"五日上漲機率 {item['prob']}%", "color": "#64748b", "size": "sm"},
                {"type": "text", "text": f"趨勢 {item['trend']}", "color": "#64748b", "size": "sm"},
                {"type": "text", "text": f"資料日期 {item['as_of']}", "color": "#64748b", "size": "sm"},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "14px",
            "contents": [{"type": "button", "style": "primary", "color": "#39c6a3", "action": {
                "type": "uri", "label": "查看完整分析",
                "uri": f"{base_url.rstrip('/')}/stock/{code}",
            }}],
        },
    }


def build_strong_signals_flex(state, base_url):
    items = state.get("signals", {}).get("items", [])[:5]
    if not items:
        return _empty_line_bubble("強勢訊號", "尚無最新強勢訊號，請等待下一次收盤更新。")
    return {
        "type": "carousel",
        "contents": [_signal_card(item, base_url) for item in items],
    }


def build_alert_push_flex(hits, base_url):
    if not 1 <= len(hits) <= 12:
        raise ValueError("LINE Flex carousel requires 1 to 12 bubbles")

    def bubble(hit):
        alert, quote = hit["alert"], hit["quote"]
        if alert["kind"] in {"price", "price_above"}:
            condition = f"條件：收盤價站上 {float(alert['value']):g}"
            current = f"今日收盤價：{quote['price']:.2f}"
        elif alert["kind"] == "price_below":
            condition = f"條件：收盤價跌破 {float(alert['value']):g}"
            current = f"今日收盤價：{quote['price']:.2f}"
        elif alert["kind"] == "probability":
            condition = f"條件：AI 勝率達到 {float(alert['value']):g}%"
            current = f"目前 AI 勝率：{quote['prob']}%"
        else:
            condition = f"條件：趨勢為{alert['value']}"
            current = f"目前趨勢：{quote['trend']}"
        return {
            "type": "bubble", "size": "kilo",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#081321",
                "paddingAll": "16px", "contents": [{
                    "type": "text", "text": "🔔 股票提醒", "color": "#39c6a3",
                    "weight": "bold", "size": "sm",
                }],
            },
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"{quote['name']} ({quote['code']})", "weight": "bold", "size": "lg", "wrap": True},
                    {"type": "text", "text": condition, "size": "sm", "color": "#64748b", "wrap": True},
                    {"type": "text", "text": current, "size": "sm", "color": "#0f766e", "weight": "bold", "wrap": True},
                    {"type": "text", "text": f"資料日期：{quote['as_of']}", "size": "xs", "color": "#94a3b8"},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "paddingAll": "14px",
                "contents": [{"type": "button", "style": "primary", "color": "#39c6a3", "action": {
                    "type": "uri", "label": "查看完整分析",
                    "uri": f"{base_url.rstrip('/')}/stock/{quote['code']}",
                }}],
            },
        }

    return {"type": "carousel", "contents": [bubble(hit) for hit in hits]}


def build_line_summary_card(title, lines, cta_label, url, accent="#39c6a3", action=None):
    """建立只有一個主要動作的 LINE 摘要卡。"""
    action = action or {"type": "uri", "label": cta_label, "uri": url}
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#081321",
            "paddingAll": "16px", "contents": [{
                "type": "text", "text": "AI QUANT", "color": accent,
                "size": "xs", "weight": "bold",
            }],
        },
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#0d1a2b",
            "paddingAll": "18px", "spacing": "md", "contents": [
                {"type": "text", "text": title, "color": "#eef6ff", "size": "lg", "weight": "bold", "wrap": True},
                *[{"type": "text", "text": line, "color": "#8fa4bd", "size": "sm", "wrap": True} for line in lines],
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "backgroundColor": "#0d1a2b",
            "paddingAll": "14px", "contents": [{
                "type": "button", "style": "primary", "color": accent,
                "action": action,
            }],
        },
    }


def build_line_navigation_flex(base_url):
    """Rich Menu 入口的可預覽 Flex 版本。"""
    root = base_url.rstrip("/")
    entries = [
        ("看大盤", "今天盤面偏強還是偏弱", "查看盤勢", {"type": "uri", "label": "查看盤勢", "uri": f"{root}/market"}),
        ("找機會", "產業預測與熱門題材", "選擇產業", {"type": "message", "label": "選擇產業", "text": "預測"}),
        ("查自選", "自選股票清單", "開啟關注", {"type": "message", "label": "開啟關注", "text": "我的關注"}),
        ("設提醒", "收盤與趨勢通知", "管理提醒", {"type": "message", "label": "管理提醒", "text": "提醒管理"}),
        ("算報酬", "投入金額試算", "開始試算", {"type": "message", "label": "開始試算", "text": "投資試算"}),
        ("深度分析", "圖表、回測、新聞", "開啟分析", {"type": "uri", "label": "開啟分析", "uri": f"{root}/dashboard"}),
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
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "20px",
            "contents": [
                { "type": "text", "text": "🤖 AI 選股助理", "color": "#38bdf8", "weight": "bold", "size": "xl" }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                { "type": "text", "text": "歡迎使用 AI 量化投資預測！", "color": "#f8fafc", "size": "md", "weight": "bold", "wrap": True },
                { "type": "text", "text": "您可以：\n1️⃣ 點擊下方選單選擇有興趣的【產業】\n2️⃣ 直接輸入【股票代碼】(如 2330)\n3️⃣ 輸入【大盤】查看今日走勢", "color": "#94a3b8", "size": "sm", "wrap": True, "margin": "md" }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "color": "#334155",
                    "action": { "type": "message", "label": "🎓 新手怎麼看？(教學)", "text": "新手教學" }
                }
            ]
        }
    }


def build_tutorial_flex():
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#6366f1",
            "paddingAll": "20px",
            "contents": [
                { "type": "text", "text": "🎓 新手快速上手指南", "color": "#ffffff", "weight": "bold", "size": "xl" }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#f8fafc",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                { "type": "text", "text": "不用擔心看不懂複雜的數據，只要掌握以下三個重點：", "color": "#475569", "size": "sm", "wrap": True, "weight": "bold", "margin": "sm" },
                { "type": "separator", "margin": "md", "color": "#cbd5e1" },
                { "type": "text", "text": "🎯 1. 看「五日上漲機率」", "color": "#0f172a", "size": "md", "weight": "bold", "margin": "md" },
                { "type": "text", "text": "AI 會根據過去的數據估計五個交易日後上漲的機率。大於 60% 代表機率偏高（綠字），低於 40% 建議保守觀望（紅字）。", "color": "#64748b", "size": "sm", "wrap": True },
                { "type": "text", "text": "🌡 2. 看「新聞情緒」", "color": "#0f172a", "size": "md", "weight": "bold", "margin": "md" },
                { "type": "text", "text": "我們會自動分析最近的新聞是利多還利空。「樂觀貪婪」代表市場氣氛好，「悲觀恐慌」代表市場害怕。", "color": "#64748b", "size": "sm", "wrap": True },
                { "type": "text", "text": "📖 3. 專有名詞看不懂？", "color": "#0f172a", "size": "md", "weight": "bold", "margin": "md" },
                { "type": "text", "text": "直接點擊個股的「📈 查看圖表與回測報告」，滑到網頁最下方，就有白話文的【新手投資小辭典】幫你翻譯各種專業術語喔！", "color": "#64748b", "size": "sm", "wrap": True }
            ]
        }
    }
