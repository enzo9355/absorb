import datetime as dt
import unittest

from flask import Flask

from stock_papi.services.auth import LineLoginConfig, sign_opaque_token
from stock_papi.web.routes.auth import register_auth_routes


NOW = dt.datetime(2026, 9, 17, 8, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
USER_ID = "U" + "a" * 32


class _AuthStore:
    def __init__(self):
        self.sessions = {
            "session-1": {
                "line_user_id": USER_ID,
                "csrf_token": "c" * 32,
                "expires_at": NOW + dt.timedelta(days=1),
            }
        }

    def load_session(self, session_id, now):
        return self.sessions.get(session_id)

    def get_user(self, user_id):
        return {"display_name": "測試使用者"} if user_id == USER_ID else None


class _LineStore:
    def load(self, user_id):
        return {
            "watchlist": [{"code": "2330", "name": "台積電"}, {"code": "1101", "name": "台泥"}],
            "alerts": [],
        }, None


class WatchlistEventsRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder="../templates", static_folder="../static")
        app.config["TESTING"] = True
        app.add_url_rule("/stock/<code>", "stock_page", lambda code: code)
        app.add_url_rule("/events", "research_events_page", lambda: "events")
        register_auth_routes(
            app,
            config=LineLoginConfig(
                "1234567890", "secret", "http://localhost/callback", "s" * 32,
                cookie_secure=False,
            ),
            auth_store=lambda: self.auth_store,
            line_store=lambda: _LineStore(),
            search_stock=lambda _code: (None, None),
            http_post=lambda *args, **kwargs: None,
            now=lambda: NOW,
            load_events=lambda: [{
                "id": "event-1",
                "source_id": "source-1",
                "symbol": "2330",
                "name": "台積電",
                "market": "TW",
                "event_type": "法說會",
                "title": "法說會日期公告",
                "summary": "公司公告已提供日期。",
                "published_at": "2026-09-16T09:00:00+08:00",
                "effective_at": "2026-09-17T14:00:00+08:00",
                "period_start": None,
                "period_end": None,
                "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
                "source_title": "TWSE OpenAPI",
                "source_publisher": "臺灣證券交易所",
                "source_locator": "t187ap04_L",
                "source_checked_at": "2026-09-17T08:00:00+08:00",
                "source_status": "available",
                "status": "confirmed",
                "correction_of": None,
            }],
            stock_observation=lambda code: {
                "observation_as_of": "2026-09-16",
                "change_pct": 1.2,
                "volume_ratio": 1.1,
                "risk_events": [],
            } if code == "2330" else None,
        )
        self.auth_store = _AuthStore()
        self.client = app.test_client()
        self.client.set_cookie(
            "stock_papi_session",
            sign_opaque_token("session-1", "s" * 32),
        )

    def test_private_page_orders_status_changes_upcoming_and_all_watchlist(self):
        response = self.client.get("/account/watchlist")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertLess(html.index("資料更新狀態"), html.index("有新變化的公司"))
        self.assertLess(html.index("有新變化的公司"), html.index("接下來已公布事件"))
        self.assertLess(html.index("接下來已公布事件"), html.index("全部關注公司"))
        self.assertIn("法說會日期公告", html)
        self.assertIn("台泥", html)


if __name__ == "__main__":
    unittest.main()
