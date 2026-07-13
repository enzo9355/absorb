"""LINE webhook, broadcast, and scheduled-task route registration."""

import datetime
import hmac

from flask import abort, request
from linebot.exceptions import InvalidSignatureError
from linebot.models import FlexSendMessage, TextSendMessage


def register_line_routes(
    app, *, handler, get_line_bot_api, get_line_store,
    get_broadcast_token, get_alert_task_token, analyze,
    get_broadcast_insight, refresh_sector_signals, run_alert_checks,
):
    def broadcast_weekly():
        token = get_broadcast_token()
        if not token:
            return "廣播功能未設定", 503
        if not hmac.compare_digest(request.args.get("token", ""), token):
            return "身份驗證失敗", 403
        data = analyze("TAIEX")
        if not data:
            return "分析失敗", 500
        insight = get_broadcast_insight(
            "台股大盤", {"price": data["price"], "prob": data["prob"]},
            data["bt"], data["news"],
        )
        url = f"{request.host_url}market".replace("http://", "https://")
        message = (
            f"🌞 周一 AI 投資晨報\n\n📊 大盤分析：\n{insight}"
            f"\n\n🔗 點擊查看 AI 預測軌跡：\n{url}"
        )
        try:
            get_line_bot_api().broadcast(TextSendMessage(text=message))
            return f"廣播成功：{datetime.datetime.now()}", 200
        except Exception as exc:
            return f"發送失敗：{str(exc)}", 500

    def callback():
        try:
            handler.handle(
                request.get_data(as_text=True),
                request.headers.get("X-Line-Signature", ""),
            )
        except InvalidSignatureError:
            abort(400)
        return "OK"

    def refresh_sector_signals_task():
        token = get_alert_task_token()
        if not token:
            return "產業預測排程尚未設定", 503
        if not hmac.compare_digest(
            request.headers.get("Authorization", ""), f"Bearer {token}"
        ):
            return "身份驗證失敗", 403
        store = get_line_store()
        if store is None:
            return "關注功能尚未設定", 503
        try:
            snapshot = refresh_sector_signals(store)
        except Exception:
            return "產業預測排程執行失敗", 500
        return f"產業預測排程執行完成：{snapshot.get('as_of')}", 200

    def check_alerts_task():
        token = get_alert_task_token()
        if not token:
            return "提醒排程尚未設定", 503
        if not hmac.compare_digest(
            request.headers.get("Authorization", ""), f"Bearer {token}"
        ):
            return "身份驗證失敗", 403
        store = get_line_store()
        if store is None:
            return "關注功能尚未設定", 503

        def push(user_id, contents):
            messages = contents if isinstance(contents, list) else [contents]
            messages = [
                FlexSendMessage(alt_text="股票提醒已觸發", contents=message)
                for message in messages
            ]
            get_line_bot_api().push_message(
                user_id, messages[0] if len(messages) == 1 else messages
            )

        try:
            run_alert_checks(
                store,
                analyze,
                push,
                datetime.date.today().isoformat(),
                request.host_url.replace("http://", "https://").rstrip("/"),
            )
        except Exception:
            return "提醒排程執行失敗", 500
        return "提醒排程執行完成", 200

    app.add_url_rule(
        "/broadcast_weekly", "broadcast_weekly", broadcast_weekly, methods=["GET"]
    )
    app.add_url_rule("/callback", "callback", callback, methods=["POST"])
    app.add_url_rule(
        "/tasks/refresh-sector-signals",
        "refresh_sector_signals_task",
        refresh_sector_signals_task,
        methods=["POST"],
    )
    app.add_url_rule(
        "/tasks/check-alerts", "check_alerts_task", check_alerts_task, methods=["POST"]
    )
