"""Remaining LINE presentation builders with explicit data dependencies."""

from linebot.models import MessageAction, QuickReply, QuickReplyButton

from stock_papi.integrations.line.flex import _empty_line_bubble
from stock_papi.quant.projection import calculate_investment_projection


def build_category_quick_reply(categories, page_size, page=1):
    cats = list(categories)
    total = 1 if not cats else (len(cats) + page_size - 1) // page_size
    page = max(1, min(page, total))
    start = (page - 1) * page_size
    items = [QuickReplyButton(action=MessageAction(label=c[:20], text=f"選產業_{c}")) for c in cats[start:start + page_size]]
    if page < total and len(items) < 13:
        items.append(QuickReplyButton(action=MessageAction(label="更多分類▶", text=f"分類第_{page + 1}頁")))
    return QuickReply(items=items), f"請選擇市場類別（第 {page}/{total} 頁）👇"


def build_projection_flex(code, name, data, amount, base_url):
    projection = calculate_investment_projection(amount, data)
    if not projection["ok"]:
        return _empty_line_bubble("投資試算", "金額不足買進 1 股，請提高投入金額後再試。")
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{name} ({code})", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": f"投入 {projection['amount']:,.0f} 元，約可買 {projection['shares']:,} 股。", "color": "#0f766e", "weight": "bold", "size": "sm", "wrap": True},
                {"type": "text", "text": f"AI 策略歷史估算損益：{projection['strategy_profit']:,.0f} 元", "color": "#64748b", "size": "sm", "wrap": True},
                {"type": "text", "text": f"買進持有歷史估算損益：{projection['buy_hold_profit']:,.0f} 元", "color": "#64748b", "size": "sm", "wrap": True},
                {"type": "text", "text": "這是歷史回測換算，不代表未來獲利。", "color": "#94a3b8", "size": "xs", "wrap": True},
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


def _build_stock_row(code, get_stock_name):
    name = get_stock_name(code)
    return {
        "type": "box",
        "layout": "horizontal",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": "#ffffff",
        "spacing": "sm",
        "margin": "md",
        "action": { "type": "message", "label": f"查詢 {code}", "text": code },
        "contents": [
            { "type": "text", "text": f"{code}", "color": "#64748b", "size": "sm", "weight": "bold", "flex": 2 },
            { "type": "text", "text": f"{name}", "color": "#0f172a", "size": "md", "weight": "bold", "flex": 4 },
            { "type": "text", "text": "前往分析 ▶", "color": "#0284c7", "size": "xs", "align": "end", "gravity": "center", "flex": 3 }
        ]
    }


def build_industry_carousel(cat, arr, get_stock_name):
    bubbles = []
    aggr_list = arr[:5]
    if aggr_list:
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#ef4444",
                "paddingAll": "16px",
                "contents": [ { "type": "text", "text": f"🔥 {cat} | 激進型推薦", "color": "#ffffff", "weight": "bold", "size": "lg" } ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#f8fafc",
                "paddingAll": "12px",
                "contents": [_build_stock_row(c, get_stock_name) for c in aggr_list]
            }
        })
    cons_list = arr[5:10]
    if cons_list:
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#3b82f6",
                "paddingAll": "16px",
                "contents": [ { "type": "text", "text": f"🛡️ {cat} | 保守型推薦", "color": "#ffffff", "weight": "bold", "size": "lg" } ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#f8fafc",
                "paddingAll": "12px",
                "contents": [_build_stock_row(c, get_stock_name) for c in cons_list]
            }
        })
    return { "type": "carousel", "contents": bubbles }


def _build_sector_signal_row(item):
    code = item["code"]
    name = item["name"]
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": "#ffffff",
        "spacing": "xs",
        "margin": "md",
        "action": {"type": "message", "label": f"查詢 {code}", "text": code},
        "contents": [
            {
                "type": "text", "text": f"{name} ({code})",
                "color": "#0f172a", "size": "md", "weight": "bold", "wrap": True,
            },
            {
                "type": "text",
                "text": f"AI勝率 {item['prob']}%｜{item['trend']}｜外資5日 {item['foreign_net_5']:,.0f}",
                "color": "#475569", "size": "xs", "wrap": True,
            },
            {
                "type": "text",
                "text": f"排序分數 {item['score']:.1f}｜資料 {item['as_of']}",
                "color": "#0284c7", "size": "xs", "wrap": True,
            },
        ],
    }


def build_sector_signal_carousel(category, items, display_limit):
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f766e",
            "paddingAll": "16px",
            "contents": [{
                "type": "text", "text": f"📊 {category}｜每日產業預測",
                "color": "#ffffff", "weight": "bold", "size": "lg", "wrap": True,
            }],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#f8fafc",
            "paddingAll": "12px",
            "contents": [
                _build_sector_signal_row(item)
                for item in items[:display_limit]
            ],
        },
    }
