"""Small, shared building blocks for the ABSORB PRESS BLOCK visual language."""

PAPER = "#F0ECE3"
INK = "#17151A"
BRICK = "#8A2F18"
RULE = "#8A8377"
MUTED = "#655E57"
POSITIVE = "#2F6F4E"
ON_INK_MUTED = "#CFC7BC"

# Stable names for callers that want to make the visual contract explicit.
PRESS_PAPER = PAPER
PRESS_INK = INK
PRESS_BRICK = BRICK
PRESS_RULE = RULE


def ink_header(title, subtitle=None, eyebrow_text="ABSORB"):
    contents = []
    if eyebrow_text:
        contents.append({
            "type": "text",
            "text": str(eyebrow_text),
            "color": PAPER,
            "weight": "bold",
            "size": "xs",
            "wrap": True,
        })
    if title:
        contents.append(headline(title, color=PAPER))
    if subtitle:
        contents.append({
            "type": "text",
            "text": str(subtitle),
            "color": ON_INK_MUTED,
            "size": "sm",
            "wrap": True,
        })
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": INK,
        "paddingAll": "20px",
        "spacing": "xs",
        "contents": contents,
    }


def eyebrow(text, color=BRICK):
    return {
        "type": "text",
        "text": str(text),
        "color": color,
        "weight": "bold",
        "size": "xs",
        "wrap": True,
    }


def headline(text, color=INK, size="xl", margin=None):
    item = {
        "type": "text",
        "text": str(text),
        "color": color,
        "weight": "bold",
        "size": size,
        "wrap": True,
    }
    if margin:
        item["margin"] = margin
    return item


def kv_table(rows):
    def row_item(row):
        label, value, *colors = row
        value_color = colors[0] if colors else INK
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": str(label), "color": MUTED, "size": "sm", "flex": 4, "wrap": True},
                {"type": "text", "text": str(value), "color": value_color, "size": "sm", "weight": "bold", "align": "end", "flex": 5, "wrap": True},
            ],
        }

    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [row_item(row) for row in rows],
    }


def disclaimer(text):
    return {
        "type": "text",
        "text": str(text),
        "color": MUTED,
        "size": "xs",
        "wrap": True,
    }


def button(label, action, style="secondary", color=None):
    action = dict(action)
    action.setdefault("label", str(label))
    item = {"type": "button", "style": style, "action": action}
    if color or style == "primary":
        item["color"] = color or BRICK
    return item


def button_stack(buttons):
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": PAPER,
        "paddingAll": "14px",
        "spacing": "sm",
        "contents": list(buttons),
    }


def bubble(title, body, footer=None, subtitle=None, size="kilo", eyebrow_text="ABSORB"):
    contents = body if isinstance(body, list) else [body]
    result = {
        "type": "bubble",
        "size": size,
        "header": ink_header(title, subtitle, eyebrow_text),
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PAPER,
            "paddingAll": "20px",
            "spacing": "md",
            "contents": contents,
        },
    }
    if footer:
        result["footer"] = footer if isinstance(footer, dict) else button_stack(footer)
    return result


def delta_color(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return INK
    if value > 0:
        return POSITIVE
    if value < 0:
        return BRICK
    return MUTED
