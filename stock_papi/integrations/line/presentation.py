"""Remaining LINE presentation builders with explicit data dependencies."""

from linebot.models import MessageAction, QuickReply, QuickReplyButton

from stock_papi.integrations.line import press_block as pb
from stock_papi.integrations.line.flex import _empty_line_bubble
from stock_papi.quant.projection import calculate_investment_projection
from stock_papi.shared.symbol import get_instrument_type


def build_category_quick_reply(categories, page_size, page=1):
    cats = list(categories)
    total = 1 if not cats else (len(cats) + page_size - 1) // page_size
    page = max(1, min(page, total))
    start = (page - 1) * page_size
    items = [QuickReplyButton(action=MessageAction(label=c[:20], text=f"選產業_{c}")) for c in cats[start:start + page_size]]
    if page < total and len(items) < 13:
        items.append(QuickReplyButton(action=MessageAction(label="更多分類", text=f"分類第_{page + 1}頁")))
    return QuickReply(items=items), f"請選擇市場類別（第 {page}/{total} 頁）"


def build_projection_flex(code, name, data, amount, base_url):
    projection = calculate_investment_projection(amount, data)
    if not projection["ok"]:
        return _empty_line_bubble("投資試算", "金額不足買進 1 股，請提高投入金額後再試。")
    return pb.bubble(
        f"{name} ({code})",
        [
            pb.headline(
                f"投入 {projection['amount']:,.0f} 元，約可買 {projection['shares']:,} 股。",
                color=pb.POSITIVE,
                size="sm",
            ),
            pb.kv_table([
                ("AI 策略歷史估算損益", f"{projection['strategy_profit']:,.0f} 元"),
                ("買進持有歷史估算損益", f"{projection['buy_hold_profit']:,.0f} 元"),
            ]),
            pb.disclaimer("這是歷史回測換算，不代表未來獲利。"),
        ],
        footer=pb.button_stack([
            pb.button(
                "查看完整分析",
                {"type": "uri", "uri": f"{base_url.rstrip('/')}/stock/{code}"},
                style="primary",
                color=pb.BRICK,
            ),
        ]),
        size="kilo",
        eyebrow_text="ABSORB｜投資試算",
    )


def _build_stock_row(code, get_stock_name):
    name = get_stock_name(code)
    return {
        "type": "box",
        "layout": "horizontal",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": pb.PAPER,
        "spacing": "sm",
        "margin": "md",
        "action": { "type": "message", "label": f"查詢 {code}", "text": code },
        "contents": [
            {**pb.eyebrow(code), "flex": 2},
            {**pb.headline(name, size="md"), "flex": 4},
            {**pb.disclaimer("前往分析"), "align": "end", "gravity": "center", "flex": 3},
        ]
    }


def build_industry_carousel(cat, arr, get_stock_name):
    bubbles = []
    aggr_list = list(arr or [])[:5]
    if aggr_list:
        bubbles.append(pb.bubble(
            f"{cat}｜激進型推薦",
            [_build_stock_row(c, get_stock_name) for c in aggr_list],
            size="mega",
            eyebrow_text="ABSORB｜產業觀察",
        ))
    cons_list = list(arr or [])[5:10]
    if cons_list:
        bubbles.append(pb.bubble(
            f"{cat}｜保守型推薦",
            [_build_stock_row(c, get_stock_name) for c in cons_list],
            size="mega",
            eyebrow_text="ABSORB｜產業觀察",
        ))
    if not bubbles:
        return _empty_line_bubble(
            f"{cat}｜產業觀察",
            "目前尚無此產業推薦名單，請等待下一次收盤更新。",
        )
    return { "type": "carousel", "contents": bubbles }


def _build_sector_signal_row(item):
    code = str(item.get("code") or "")
    name = str(item.get("name") or code or "資料不足")
    prob = item.get("prob")
    prob_text = f"{prob}%" if isinstance(prob, (int, float)) else "資料不足"
    trend = item.get("trend") or "資料不足"
    score = item.get("score")
    score_text = f"{float(score):.1f}" if isinstance(score, (int, float)) else "資料不足"
    as_of = item.get("as_of") or "待更新"
    foreign_net_5 = item.get("foreign_net_5")
    foreign_suffix = ""
    try:
        if get_instrument_type(code) != "ETF" and foreign_net_5 is not None:
            foreign_suffix = f"｜外資5日 {float(foreign_net_5):,.0f}"
    except (TypeError, ValueError):
        foreign_suffix = ""
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": pb.PAPER,
        "spacing": "xs",
        "margin": "md",
        "action": {"type": "message", "label": f"查詢 {code}", "text": code},
        "contents": [
            pb.headline(f"{name} ({code})", size="md"),
            pb.disclaimer(f"五日上漲機率 {prob_text}｜{trend}{foreign_suffix}"),
            pb.eyebrow(f"排序分數 {score_text}｜資料 {as_of}"),
        ],
    }


def build_sector_signal_carousel(category, items, display_limit):
    safe_items = [item for item in (items or []) if isinstance(item, dict) and item.get("code")]
    try:
        limit = max(0, int(display_limit))
    except (TypeError, ValueError):
        limit = len(safe_items)
    rows = [_build_sector_signal_row(item) for item in safe_items[:limit]]
    if not rows:
        return _empty_line_bubble(
            f"{category}｜每日產業預測",
            "目前尚無產業訊號，請等待下一次收盤更新。",
        )
    return pb.bubble(
        f"{category}｜每日產業預測",
        rows,
        size="mega",
        eyebrow_text="ABSORB｜產業觀察",
    )
