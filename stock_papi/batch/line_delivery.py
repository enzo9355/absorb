"""LINE report notification adapter; secrets are read only from the environment."""

import json
import os
import re
import urllib.request


def line_sender(message, audience):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token or any(character.isspace() for character in token):
        raise RuntimeError("LINE channel access token is unavailable")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if audience == "broadcast":
        url = "https://api.line.me/v2/bot/message/broadcast"
        document = {"messages": [{"type": "text", "text": message}]}
    elif audience == "admin":
        user_id = os.environ.get("REPORT_ADMIN_USER_ID", "")
        if re.fullmatch(r"U[0-9a-f]{32}", user_id) is None:
            raise RuntimeError("report administrator user id is unavailable")
        url = "https://api.line.me/v2/bot/message/push"
        document = {
            "to": user_id,
            "messages": [{"type": "text", "text": message}],
        }
    else:
        raise ValueError("unsupported LINE notification audience")
    request = urllib.request.Request(
        url,
        data=json.dumps(document, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in {200, 202}:
            raise RuntimeError("LINE notification request failed")
