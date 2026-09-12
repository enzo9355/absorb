import datetime as dt
import inspect
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, render_template


os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app
from stock_papi.batch.calendar import TradingCalendarSet
from stock_papi.web import routes as web_routes

from tests.test_batch_calendar import calendar_document
from tests.test_observation_public_surfaces import (
    observation_dashboard,
    quant_snapshot,
)


_CSS_FILES = (
    "tokens.css",
    "base.css",
    "pages.css",
    "layout.css",
    "components.css",
    "utilities.css",
)


def css_bundle():
    static_root = Path(__file__).resolve().parents[1] / "static"
    return "\n".join(
        (static_root / name).read_text(encoding="utf-8")
        for name in _CSS_FILES
    )


def css_compact():
    return re.sub(r"\s+", "", css_bundle())


def prediction_product(market="TW", symbol="2330", as_of="2026-07-15"):
    return {
        "schema_version": 1,
        "kind": "absorb-five-session-predictions",
        "market": market,
        "as_of": as_of,
        "model_version": "lgbm-5d-v1",
        "backtest_sha256": "b" * 64,
        "entities": {
            symbol: {
                "symbol": symbol,
                "entity_type": "market_index" if symbol.startswith("^") or symbol == "TAIEX" else "security",
                "as_of": as_of,
                "target_session": "2026-07-22",
                "current_price": 23150.25 if symbol == "TAIEX" else 164.0,
                "up_probability": 0.68,
                "predicted_return_5d": 0.0427,
                "predicted_price": 24138.765675 if symbol == "TAIEX" else 171.0028,
                "predicted_change_pct": 4.27,
            }
        },
    }


class WebProductTests(unittest.TestCase):
    @patch.object(stock_app, "_published_prediction_snapshot")
    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_dashboard_plainly_marks_uncalibrated_research_prediction(
        self, load_snapshot, load_prediction
    ):
        snapshot = observation_dashboard()
        snapshot["market_index"] = {
            "symbol": "TAIEX", "name": "加權指數", "as_of": "2026-07-15",
            "price": 23150.25, "change": 188.4, "change_pct": 0.82,
            "open": 22982.1, "high": 23210.8, "low": 22940.6,
            "candles": [], "ma20": [], "returns": {},
            "source": {"provider": "TWSE", "kind": "official_index_daily"},
        }
        estimate = prediction_product(symbol="TAIEX")
        estimate["schema_version"] = 2
        estimate["validation_mode"] = "research"
        estimate.pop("backtest_sha256")
        load_snapshot.return_value = snapshot
        load_prediction.return_value = estimate

        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)

        self.assertIn("模型推估上漲機率（未校準）", html)
        self.assertIn("未經回測校準", html)
        self.assertNotIn("目前正式預測", html)

    @patch.object(stock_app, "_published_prediction_snapshot")
    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_dashboard_renders_verified_market_index_level_and_candles(
        self, load_snapshot, load_prediction
    ):
        snapshot = observation_dashboard()
        snapshot["market_index"] = {
            "symbol": "TAIEX",
            "name": "加權指數",
            "as_of": "2026-07-15",
            "price": 23150.25,
            "change": 188.4,
            "change_pct": 0.82,
            "open": 22982.1,
            "high": 23210.8,
            "low": 22940.6,
            "candles": [
                {
                    "time": "2026-07-14",
                    "open": 22800.0,
                    "high": 23010.0,
                    "low": 22760.0,
                    "close": 22961.85,
                },
                {
                    "time": "2026-07-15",
                    "open": 22982.1,
                    "high": 23210.8,
                    "low": 22940.6,
                    "close": 23150.25,
                },
            ],
            "ma20": [
                {"time": "2026-07-14", "value": 22790.0},
                {"time": "2026-07-15", "value": 22820.0},
            ],
            "returns": {},
            "source": {"provider": "TWSE", "kind": "official_index_daily"},
        }
        load_snapshot.return_value = snapshot
        load_prediction.return_value = prediction_product(symbol="TAIEX")

        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)

        for marker in (
            "加權指數",
            "23,150.25",
            "+188.40",
            "+0.82%",
            'id="market-index-chart"',
            'role="img"',
            "加權指數最近五個交易日 OHLC",
            'id="market-index-chart-data"',
            '"time": "2026-07-15"',
            "五日上漲機率",
            "68.0%",
            "24,138.77",
            "+4.27%",
            "2026-07-22",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_chart_rejects_unverified_embedded_prediction_display(self, fetch):
        snapshot = quant_snapshot()
        snapshot["prediction_display"] = {
            "status": "published",
            "as_of": snapshot["as_of"],
            "horizon_sessions": 5,
            "direction": "up",
            "probability_up_pct": 68.0,
            "target_price": 171.0,
            "expected_return_pct": 4.27,
            "model_version": "lgbm-ohlc-5d-v1",
            "validation": {
                "oos_samples": 75,
                "direction_accuracy_pct": 57.3,
                "brier": 0.241,
                "price_mae_pct": 3.2,
            },
            "points": [
                {"time": snapshot["as_of"], "value": 164.0},
                {"time": "2026-07-21", "value": 171.0},
            ],
        }
        fetch.return_value = snapshot

        response = stock_app.app.test_client().get("/stock/2330")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI 五日預測尚未發布", html)
        self.assertIn("個股最近五個交易日 OHLC", html)
        self.assertNotIn("五日上漲機率", html)
        self.assertNotIn("171.00", html)
        self.assertNotIn('"prediction"', html)
        self.assertNotIn('"AI_P"', html)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_stock_events_are_split_into_supported_categories_with_severity(self, load):
        snapshot = observation_dashboard()
        snapshot["stock_events"] = [
            {"symbol": "6955", "name": "邦睿生技-創", "event_type": "price_move", "severity": "high", "observation": "單日跌幅異常", "metric_value": -10.83, "unit": "pct", "as_of": "2026-08-26"},
            {"symbol": "3313", "name": "斐成", "event_type": "price_move", "severity": "high", "observation": "單日漲幅異常", "metric_value": 10.0, "unit": "pct", "as_of": "2026-08-26"},
            {"symbol": "2603", "name": "長榮", "event_type": "volume_surge", "severity": "medium", "observation": "量能異常放大", "metric_value": 2.8, "unit": "ratio", "as_of": "2026-08-26"},
            {"symbol": "2330", "name": "台積電", "event_type": "institution_flow", "severity": "medium", "observation": "機構淨流入偏高", "metric_value": 3.1, "unit": "pct", "as_of": "2026-08-26"},
            {"symbol": "2454", "name": "聯發科", "event_type": "rsi_overbought", "severity": "medium", "observation": "RSI 進入過熱區", "metric_value": 74.0, "unit": "index", "as_of": "2026-08-26"},
            {"symbol": "0050", "name": "元大台灣50", "event_type": "data_warning", "severity": "high", "observation": "資料來源價差警示", "metric_value": 1, "unit": "flag", "as_of": "2026-08-26"},
        ]
        snapshot["trading_status_observations"] = [{
            "symbol": "1589", "name": "永冠-KY", "label": "停止買賣",
            "observation_as_of": "2026-08-26",
        }]
        load.return_value = snapshot

        html = stock_app.app.test_client().get("/stocks").get_data(as_text=True)

        self.assertIn("異常上漲", html)
        self.assertIn("異常下跌", html)
        for label in ("量能異常", "法人動向", "技術面", "官方事件", "資料警示"):
            self.assertIn(label, html)
        self.assertIn('data-event-group="up"', html)
        self.assertIn('data-event-group="down"', html)
        self.assertIn('data-event-group="volume"', html)
        self.assertIn('data-event-group="official"', html)
        self.assertIn("極端", html)
        self.assertIn("顯著", html)
        self.assertLess(html.index("斐成"), html.index("邦睿生技-創"))

    def test_shell_uses_collapsible_dashboard_sidebar_with_accessible_toggle(self):
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")

        for marker in (
            'class="dashboard-sidebar"',
            'data-sidebar-toggle',
            'aria-controls="dashboard-sidebar"',
            'aria-expanded="true"',
            'id="dashboard-sidebar"',
        ):
            self.assertIn(marker, html)
        self.assertIn("initSidebar", script)
        self.assertIn('event.key === "Escape"', script)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_page_does_not_train_or_infer_a_forecast_during_request(self, fetch):
        fetch.return_value = quant_snapshot()

        html = stock_app.app.test_client().get("/stock/2330").get_data(as_text=True)

        self.assertIn("AI 五日預測尚未發布", html)
        self.assertNotIn("五日上漲機率", html)

    def test_chart_renderer_draws_market_candles_and_prediction_marker(self):
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        for marker in (
            "initMarketIndexChart",
            'bySelector("#market-index-chart")',
            'bySelector("#market-index-chart-data")',
            "predictionSeries.setMarkers",
            'text: "AI 5日"',
            "LineStyle.Dashed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_data_freshness_classifier_preserves_verified_dates_and_states(self):
        classifier = getattr(web_routes.system, "classify_data_freshness", None)

        self.assertIsNotNone(classifier)
        self.assertIn("next_session", inspect.signature(classifier).parameters)
        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026, closed=("2026-07-20",))
        ])
        cases = (
            ("source date", "2026-07-17", "current"),
            ("weekend", "2026-07-18", "current"),
            ("holiday", "2026-07-20", "current"),
            ("applicable session", "2026-07-21", "current"),
            ("next session", "2026-07-22", "updating"),
            ("later missed session", "2026-07-23", "stale"),
        )
        for label, reference_date, expected in cases:
            with self.subTest(label=label):
                actual = classifier(
                    source_market_date="2026-07-17",
                    applicable_trading_date="2026-07-21",
                    reference_date=reference_date,
                    next_session=calendars.next_session,
                )

                self.assertEqual(actual["status"], expected)
                self.assertEqual(actual["source_market_date"], "2026-07-17")
                self.assertEqual(
                    actual["applicable_trading_date"], "2026-07-21"
                )

        unavailable = classifier(
            source_market_date=None,
            applicable_trading_date=None,
            reference_date="2026-07-21",
            next_session=calendars.next_session,
        )
        self.assertEqual(unavailable["status"], "unavailable")
        missing_calendar = classifier(
            source_market_date="2026-07-17",
            applicable_trading_date="2026-07-17",
            reference_date="2026-07-21",
            next_session=None,
        )
        self.assertEqual(missing_calendar["status"], "unavailable")
        self.assertNotEqual(missing_calendar["status"], "current")

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_tw_health_freshness_uses_production_calendar_for_holidays_and_staleness(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-09-24",
        }
        load_index.side_effect = lambda market="TW": [{
            "market": market,
            "report_type": "post_close",
            "source_market_date": "2026-09-24" if market == "TW" else "2026-09-24",
            "applicable_trading_date": "2026-09-24",
        }]
        cases = (
            ("session", dt.datetime(2026, 9, 24, 3, tzinfo=dt.timezone.utc), "current"),
            ("holiday", dt.datetime(2026, 9, 25, 3, tzinfo=dt.timezone.utc), "current"),
            ("holiday eve", dt.datetime(2026, 9, 28, 3, tzinfo=dt.timezone.utc), "current"),
            ("next session", dt.datetime(2026, 9, 29, 3, tzinfo=dt.timezone.utc), "updating"),
            ("missed session", dt.datetime(2026, 9, 30, 3, tzinfo=dt.timezone.utc), "stale"),
        )
        for label, instant, expected in cases:
            with self.subTest(label=label), patch.object(
                web_routes.system, "_utc_now", return_value=instant
            ):
                response = stock_app.app.test_client().get("/health/data")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["markets"]["TW"]["status"], expected)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_tw_health_fails_unavailable_outside_calendar_evidence(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2027-01-04",
        }
        load_index.side_effect = lambda market="TW": [{
            "market": market,
            "report_type": "post_close",
            "source_market_date": "2027-01-04",
            "applicable_trading_date": "2027-01-04",
        }]
        with patch.object(
            web_routes.system,
            "_utc_now",
            return_value=dt.datetime(2027, 1, 5, 3, tzinfo=dt.timezone.utc),
        ):
            response = stock_app.app.test_client().get("/health/data")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["markets"]["TW"]["status"], "unavailable"
        )

    def test_market_local_date_uses_aware_tw_and_us_timezones(self):
        market_local_date = getattr(web_routes.system, "market_local_date", None)

        self.assertIsNotNone(market_local_date)
        early_utc = dt.datetime(2026, 8, 24, 3, 30, tzinfo=dt.timezone.utc)
        late_utc = dt.datetime(2026, 8, 24, 16, 30, tzinfo=dt.timezone.utc)

        self.assertEqual(
            market_local_date("TW", now=early_utc), dt.date(2026, 8, 24)
        )
        self.assertEqual(
            market_local_date("US", now=early_utc), dt.date(2026, 8, 23)
        )
        self.assertEqual(
            market_local_date("TW", now=late_utc), dt.date(2026, 8, 25)
        )
        self.assertEqual(
            market_local_date("US", now=late_utc), dt.date(2026, 8, 24)
        )
        with self.assertRaises(ValueError):
            market_local_date("TW", now=dt.datetime(2026, 8, 24, 3, 30))

    def test_invalid_freshness_dates_normalize_to_json_safe_none(self):
        classifier = web_routes.system.classify_data_freshness
        self.assertIn("next_session", inspect.signature(classifier).parameters)

        actual = classifier(
            source_market_date={"not-json-safe"},
            applicable_trading_date="2026-8-24",
            reference_date=dt.date(2026, 8, 24),
            next_session=lambda value: value + dt.timedelta(days=1),
        )

        self.assertEqual(actual["status"], "unavailable")
        self.assertIsNone(actual["source_market_date"])
        self.assertIsNone(actual["applicable_trading_date"])
        json.dumps(actual)

        with stock_app.app.test_request_context("/dashboard"):
            html = render_template(
                "dashboard.html",
                observation={},
                daily_cards={},
                data_freshness={"TW": actual},
            )
        self.assertIn("尚無已驗證日期", html)
        self.assertNotIn("not-json-safe", html)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_internal_us_type_error_is_isolated_and_dashboards_remain_renderable(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-08-24",
        }
        calls = []

        def reports_for(*, market="TW"):
            calls.append(market)
            if market == "US":
                raise TypeError("reader implementation failed")
            return [{
                "market": "TW",
                "report_type": "post_close",
                "source_market_date": "2026-08-24",
                "applicable_trading_date": "2026-08-24",
            }]

        load_index.side_effect = reports_for
        fixed_now = dt.datetime(2026, 8, 24, 12, tzinfo=dt.timezone.utc)
        with patch.object(
            web_routes.system, "_utc_now", return_value=fixed_now, create=True
        ):
            health = stock_app.app.test_client().get("/health/data")

        self.assertEqual(health.status_code, 200)
        payload = health.get_json()
        self.assertEqual(payload["markets"]["TW"]["status"], "current")
        self.assertEqual(payload["markets"]["US"]["status"], "unavailable")
        self.assertIsNone(payload["markets"]["US"]["source_market_date"])
        self.assertEqual(calls, ["TW", "US"])

        calls.clear()
        dashboard = stock_app.app.test_client().get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(calls, ["TW"])

        calls.clear()
        us_dashboard = stock_app.app.test_client().get("/us")
        self.assertEqual(us_dashboard.status_code, 503)
        self.assertEqual(calls, ["US"])

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_invalid_index_dates_are_json_safe_and_do_not_fall_back(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-08-24",
        }

        def reports_for(*, market="TW"):
            if market == "TW":
                return [{
                    "market": "TW",
                    "report_type": "post_close",
                    "source_market_date": "2026-08-24",
                    "applicable_trading_date": "2026-08-24",
                }]
            return [{
                "market": "US",
                "report_type": "post_close",
                "source_market_date": {"not-json-safe"},
                "applicable_trading_date": "2026-8-24",
            }]

        load_index.side_effect = reports_for
        fixed_now = dt.datetime(2026, 8, 24, 12, tzinfo=dt.timezone.utc)
        with patch.object(
            web_routes.system, "_utc_now", return_value=fixed_now
        ):
            response = stock_app.app.test_client().get("/health/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["markets"]["TW"]["status"], "current")
        self.assertEqual(payload["markets"]["US"]["status"], "unavailable")
        self.assertIsNone(payload["markets"]["US"]["source_market_date"])
        self.assertIsNone(
            payload["markets"]["US"]["applicable_trading_date"]
        )
        json.dumps(payload)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_report_item_market_mismatch_fails_closed_for_us_only(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-08-24",
        }
        load_index.side_effect = lambda market="TW": [{
            "market": "TW",
            "report_type": "post_close",
            "source_market_date": "2026-08-24",
            "applicable_trading_date": "2026-08-24",
        }]

        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026)
        ])
        fixed_now = dt.datetime(2026, 8, 24, 12, tzinfo=dt.timezone.utc)
        with patch.object(
            web_routes.system,
            "_next_session_for_market",
            side_effect=lambda _market, value: calendars.next_session(value),
        ), patch.object(
            web_routes.system, "_utc_now", return_value=fixed_now
        ):
            response = stock_app.app.test_client().get("/health/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["markets"]["TW"]["status"], "current")
        self.assertEqual(payload["markets"]["US"]["status"], "unavailable")
        self.assertIsNone(payload["markets"]["US"]["source_market_date"])

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_non_dashboard_page_does_not_load_freshness_data(
        self, load_index, load_dashboard
    ):
        response = stock_app.app.test_client().get("/learn")

        self.assertEqual(response.status_code, 200)
        load_index.assert_not_called()
        load_dashboard.assert_not_called()

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_tw_dashboard_omits_explicitly_mismatched_daily_card(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = observation_dashboard()
        load_index.return_value = [{
            "market": "US",
            "report_type": "post_close",
            "source_market_date": "2026-08-19",
            "applicable_trading_date": "2026-08-20",
            "title": "MISMATCHED US DAILY CARD",
            "summary": ["MISMATCHED US SUMMARY"],
        }]

        response = stock_app.app.test_client().get("/dashboard")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("MISMATCHED US DAILY CARD", html)
        self.assertNotIn("MISMATCHED US SUMMARY", html)
        self.assertNotIn("/reports/2026-08-19/post-close", html)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_data_health_uses_one_utc_instant_for_both_markets(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-08-24",
        }

        def reports_for(market="TW"):
            date = "2026-08-24" if market == "TW" else "2026-08-23"
            return [{
                "market": market,
                "report_type": "post_close",
                "source_market_date": date,
                "applicable_trading_date": date,
            }]

        load_index.side_effect = reports_for
        instants = (
            dt.datetime(2026, 8, 24, 3, 30, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 8, 24, 16, 30, tzinfo=dt.timezone.utc),
        )
        with patch.object(
            web_routes.system, "_utc_now", side_effect=instants
        ) as clock:
            response = stock_app.app.test_client().get("/health/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["markets"]["TW"]["status"], "current")
        self.assertEqual(payload["markets"]["US"]["status"], "current")
        self.assertEqual(clock.call_count, 1)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_data_health_keeps_service_ok_separate_from_stale_market_data(
        self, load_index, load_dashboard
    ):
        load_dashboard.return_value = {
            "market": "TW",
            "observation_as_of": "2026-08-20",
        }
        load_index.side_effect = lambda market="TW": [
            {
                "market": market,
                "report_type": "post_close",
                "source_market_date": "2026-08-20",
                "applicable_trading_date": "2026-08-20",
            }
        ]

        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026)
        ])
        fixed_now = dt.datetime(2026, 8, 24, 12, tzinfo=dt.timezone.utc)
        with patch.object(
            web_routes.system,
            "_next_session_for_market",
            side_effect=lambda _market, value: calendars.next_session(value),
        ), patch.object(
            web_routes.system, "_utc_now", return_value=fixed_now
        ):
            response = stock_app.app.test_client().get("/health/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["service"]["status"], "ok")
        self.assertEqual(payload["markets"]["TW"]["status"], "stale")
        self.assertNotEqual(payload["markets"]["TW"]["status"], "current")
        self.assertEqual(
            payload["markets"]["TW"]["source_market_date"], "2026-08-20"
        )
        self.assertEqual(
            payload["markets"]["TW"]["applicable_trading_date"], "2026-08-20"
        )

    @patch.object(stock_app, "_published_dashboard_snapshot")
    @patch.object(stock_app, "_published_report_index_v2")
    def test_dashboards_render_verified_freshness_with_exact_dates(
        self, load_index, load_dashboard
    ):
        snapshot = observation_dashboard()
        snapshot["observation_as_of"] = "2026-08-20"
        load_dashboard.return_value = snapshot
        load_index.side_effect = lambda market="TW": [
            {
                "market": market,
                "report_type": "post_close",
                "source_market_date": "2026-08-20",
                "applicable_trading_date": "2026-08-20",
            }
        ]

        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026)
        ])
        fixed_now = dt.datetime(2026, 8, 24, 12, tzinfo=dt.timezone.utc)
        with patch.object(
            web_routes.system,
            "_next_session_for_market",
            side_effect=lambda _market, value: calendars.next_session(value),
        ), patch.object(
            web_routes.system, "_utc_now", return_value=fixed_now
        ):
            dashboard = stock_app.app.test_client().get("/dashboard")
        with stock_app.app.test_request_context("/us"):
            us_html = render_template(
                "us_dashboard.html",
                market="US",
                summary={
                    "source_market_date": "2026-08-20",
                    "applicable_trading_date": "2026-08-20",
                    "executive_summary": {
                        "one_line_conclusion": "已驗證摘要",
                        "largest_risk": "測試風險",
                    },
                    "key_events": [],
                    "validation": {"status": "unavailable", "reason": "測試"},
                },
                data_freshness={
                    "US": {
                        "status": "stale",
                        "source_market_date": "2026-08-20",
                        "applicable_trading_date": "2026-08-20",
                    }
                },
            )

        self.assertEqual(dashboard.status_code, 200)
        for html in (dashboard.get_data(as_text=True), us_html):
            self.assertIn('data-freshness-status="stale"', html)
            self.assertIn("資料狀態：資料過期", html)
            self.assertIn("來源交易日", html)
            self.assertIn("適用交易日", html)
            self.assertIn("2026-08-20", html)

    def test_base_shell_renders_with_dashboard_endpoint_without_us_endpoints(self):
        partial_app = Flask("partial-absorb", root_path=stock_app.app.root_path)
        partial_app.jinja_env.globals["STATIC_ASSET_VERSION"] = "test"

        @partial_app.get("/")
        def dashboard_page():
            return render_template("base.html")

        response = partial_app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/us"', html)
        self.assertIn('href="/market"', html)
        self.assertIn('href="/reports"', html)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_information_architecture_has_distinct_server_rendered_pages(self, load):
        load.return_value = observation_dashboard()
        client = stock_app.app.test_client()
        expectations = {
            # ORDER 4（A-2）：「今日」第 1 段標題。原為「台股市場研究摘要」，
            # 與第 2 段的「市場指揮台」語意重疊，依 §5.2 合併為一段白話標題。
            "/": "台股今天怎麼了",
            "/market": "市場實況",
            "/industries": "產業觀察",
            "/stocks": "個股與 ETF",
            "/ask": "ASK ABSORB",
            "/learn": "市場觀察小辭典",
        }

        for path, heading in expectations.items():
            with self.subTest(path=path):
                response = client.get(path)
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(html.count("<h1"), 1)
                self.assertIn(heading, html)

        home = client.get("/").get_data(as_text=True)
        self.assertNotIn('id="industry-observations"', home)
        self.assertNotIn('id="stock-events"', home)
        self.assertIn('href="/industries"', home)
        self.assertIn('href="/stocks"', home)
        self.assertIn('href="/ask"', home)
        self.assertIn('href="/learn"', home)

    def test_legacy_market_map_redirects_to_industries(self):
        response = stock_app.app.test_client().get("/market-map")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/industries"))

    def test_dashboard_update_stream_carries_both_report_tracks(self):
        """ORDER 4（A-2）：「今日市場準備」與「今日焦點」合併為「最新更新」。

        守的性質不變 —— 主版面必須在第一屏之後就給出兩條報告軌道的入口 ——
        只是區塊名稱與結構改了。額外加上排序聲明與「不是時間倒序」的斷言，
        避免這一段被實作成單純的時間動態牆（純時間倒序會把「新」誤當「重要」）。
        """
        response = stock_app.app.test_client().get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("最新更新", html)
        self.assertIn("盤後觀察", html)
        self.assertIn("盤前風險更新", html)
        self.assertIn("依重要性排序，不是發布時間倒序", html)
        self.assertIn('class="update-type update-type-report"', html)
        self.assertIn('class="update-type update-type-observation"', html)
        # 兩條報告軌道必須排在觀察條目之前（重要性優先）
        self.assertLess(
            html.index("update-type-report"), html.index("update-type-observation")
        )
        # 舊的兩個重疊區塊不得同時殘留
        self.assertNotIn("今日市場準備", html)
        self.assertNotIn("今日焦點", html)

    def test_every_papi_theme_has_at_least_five_companies(self):
        self.assertTrue(
            all(
                len(names) >= 5
                for names in stock_app.PAPI_THEME_SECTORS.values()
            )
        )

    def test_build_market_heatmap_orders_strongest_first_for_preview(self):
        cards = [
            {
                "name": "弱勢",
                "count": 1,
                "score": 42,
                "leader": {"code": "1101", "prob": 42},
            },
            {
                "name": "強勢",
                "count": 2,
                "score": 68,
                "leader": {"code": "2330", "prob": 68},
            },
        ]

        result = stock_app.build_market_heatmap(cards)

        self.assertEqual([item["name"] for item in result], ["強勢", "弱勢"])
        self.assertEqual(result[0]["tone"], "hot")
        self.assertEqual(result[1]["tone"], "cold")

    def test_find_industry_peers_excludes_current_stock(self):
        market_map = {
            "全市場": ["2330", "2454", "2303"],
            "半導體": ["2330", "2454", "2303"],
        }

        peers = stock_app.find_industry_peers("2330", market_map, limit=2)

        self.assertEqual(
            peers, {"category": "半導體", "codes": ["2454", "2303"]}
        )

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_industries_page_renders_verified_actual_observations(self, load):
        load.return_value = observation_dashboard()

        response = stock_app.app.test_client().get("/industries")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        for label in (
            "產業強弱與關注清單",
            "近 5 日相對大盤報酬",
            "關注公司",
        ):
            self.assertIn(label, html)
        for forbidden in (
            "五日上漲機率",
            "推薦",
            "回測",
            "勝率",
        ):
            self.assertNotIn(forbidden, html)

    def test_root_renders_dashboard_and_search_redirects_known_stock(self):
        client = stock_app.app.test_client()

        root = client.get("/")
        with patch.object(
            stock_app,
            "search_stock_code",
            side_effect=[("2330", "台積電"), (None, None)],
        ):
            found = client.get("/search?q=台積電")
            missing = client.get(
                "/search?q=不存在股票", follow_redirects=True
            )

        self.assertEqual(root.status_code, 200)
        self.assertIn("ABSORB", root.get_data(as_text=True))
        self.assertEqual(found.status_code, 302)
        self.assertTrue(found.headers["Location"].endswith("/stock/2330"))
        self.assertIn("找不到", missing.get_data(as_text=True))

    def test_empty_search_stays_on_dashboard_with_clear_error(self):
        response = stock_app.app.test_client().get(
            "/search?q=", follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("找不到", response.get_data(as_text=True))

    def test_base_shell_uses_absorb_brand_and_light_theme(self):
        response = stock_app.app.test_client().get("/dashboard")
        html = response.get_data(as_text=True)
        css = css_compact()

        self.assertIn("ABSORB", html)
        self.assertIn('class="brand-wordmark"', html)
        self.assertIn('data-brand-wordmark', html)
        self.assertIn(
            'aria-label="回到 ABSORB 主畫面">Absorb</a>', html
        )
        self.assertIn('aria-label="回到 ABSORB 主畫面"', html)
        self.assertNotIn('class="brand-mark"', html)
        self.assertIn("今天市場", html)
        self.assertIn("使用 LINE 登入", html)
        self.assertIn("已驗證市場觀察", html)
        self.assertIn('data-market-switch', html)
        self.assertIn('href="/us"', html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertIn("--absorb-navy:#183147", css)
        self.assertIn("--absorb-canvas:#f1f4f4", css)
        self.assertIn('"AvenirNext",Avenir,"NotoSansTC"', css)
        self.assertIn(".research-command", css)
        self.assertIn(".market-switcha{display:grid;min-height:44px", css)
        self.assertIn(".quick-ask-backdrop[hidden]{display:none;}", css)
        self.assertIn(".quick-ask-headerbutton{display:grid;width:44px;height:44px", css)
        self.assertIn("--absorb-content-max:3200px", css)
        self.assertIn("--absorb-muted:#536575", css)
        self.assertIn(".evidence-canvas{", css)
        self.assertIn("background:var(--absorb-accent-surface)", css)
        self.assertIn(".brand-wordmark:hover{", css)
        self.assertIn("rotate(-1.5deg)", css)
        self.assertIn("@view-transition{navigation:auto;}", css)
        self.assertIn("button,input,select,textarea{font:inherit", css)
        self.assertIn(".button{display:inline-flex", css)
        self.assertIn(".command-metrics{grid-column:1/-1;grid-template-columns:repeat(4,minmax(0,1fr))", css)
        self.assertNotIn("border-left:4px", css)
        self.assertNotIn("border-top:3px", css)
        version = re.search(r'/static/app\.css\?v=([0-9a-f]{12})', html)
        self.assertIsNotNone(version)
        self.assertIn(f'/static/app.js?v={version.group(1)}', html)
        asset = stock_app.app.test_client().get(
            f'/static/app.js?v={version.group(1)}'
        )
        self.assertIn("immutable", asset.headers["Cache-Control"])
        asset.close()

    def test_us_product_navigation_and_stock_detail_keep_us_context(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app, "_published_us_securities_observation",
            return_value={"stock_events": [], "etf_observations": []},
        ):
            us_stocks = client.get("/us/stocks")

        self.assertEqual(us_stocks.status_code, 200)
        html = us_stocks.get_data(as_text=True)
        self.assertIn('data-market="US"', html)
        for href in (
            'href="/us"',
            'href="/us/market"',
            'href="/us/industries"',
            'href="/us/stocks"',
            'href="/reports/us"',
        ):
            with self.subTest(href=href):
                self.assertIn(href, html)

        with patch.object(stock_app, "build_stock_observation", return_value={
            "code": "AAPL", "name": "Apple Inc.", "market": "US",
            "observation_kind": "status", "status_label": "資料不足",
            "observation_as_of": "2026-07-15", "evidence_sha256": "a" * 64,
        }):
            detail = client.get("/stock/AAPL")

        self.assertEqual(detail.status_code, 200)
        detail_html = detail.get_data(as_text=True)
        self.assertIn('data-market="US"', detail_html)
        # ORDER 4（§5.1）：上一層必須具名，而且維持在同一個市場。
        # 個股明細的上一層是「個股與 ETF」，不是市場總覽。
        self.assertIn('class="back-link" href="/us/stocks">返回個股與 ETF', detail_html)

    def test_us_dashboard_renders_three_index_forecasts_and_actual_charts(self):
        summary = {
            "source_market_date": "2026-08-26",
            "applicable_trading_date": "2026-08-27",
            "executive_summary": {
                "one_line_conclusion": "美股市場摘要",
                "largest_risk": "波動仍需觀察",
            },
            "key_events": [],
            "validation": {"status": "unavailable", "reason": ""},
            "market": {"status": "available"},
            "industries": {"status": "available"},
        }
        forecasts = []
        for symbol, name, price in (
            ("^GSPC", "S&P 500", 6500.0),
            ("^IXIC", "Nasdaq Composite", 22000.0),
            ("^DJI", "道瓊工業指數", 46000.0),
        ):
            forecasts.append({
                "symbol": symbol, "name": name, "status": "current",
                "as_of": "2026-08-26", "target_session": "2026-09-02",
                "current_price": price, "probability_pct": 61.0,
                "probability_label": "五日上漲機率",
                "predicted_price": price * 1.02, "predicted_change_pct": 2.0,
                "line": [
                    {"time": "2026-08-26", "value": price},
                    {"time": "2026-09-02", "value": price * 1.02},
                ],
                "candles": [
                    {"time": "2026-08-25", "open": price - 20, "high": price + 10, "low": price - 30, "close": price - 10},
                    {"time": "2026-08-26", "open": price - 10, "high": price + 20, "low": price - 15, "close": price},
                ],
            })

        with stock_app.app.test_request_context("/us"):
            html = render_template(
                "us_dashboard.html", summary=summary, market="US",
                index_predictions=forecasts, data_freshness={},
            )

        for marker in (
            "S&amp;P 500", "Nasdaq Composite", "道瓊工業指數",
            "五日上漲機率", "61.0%", "2026-09-02",
            'id="us-index-chart"', 'id="us-index-chart-data"',
        ):
            self.assertIn(marker, html)

    def test_us_index_switch_does_not_depend_on_chart_library(self):
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )
        start = script.index("function initUsIndexChart")
        end = script.index("\n}", start)
        body = script[start:end]

        # The three verified index forecasts are server-rendered with `hidden`
        # on all but the first panel, so only this initializer can reveal them.
        # Gating it on the third-party chart library would make the Nasdaq and
        # Dow forecasts unreachable whenever that CDN script fails to load.
        guard = body[: body.index("const select")]
        self.assertNotIn("window.LightweightCharts", guard)

        select_body = body[body.index("const select") :]
        pressed = select_body.index('setAttribute("aria-pressed"')
        panel = select_body.index("dataset.usIndexPanel")
        chart = select_body.index("window.LightweightCharts")
        self.assertLess(pressed, chart)
        self.assertLess(panel, chart)

    def test_us_stocks_disables_tw_dashboard_hydration(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app, "_published_us_securities_observation",
            return_value={"stock_events": [], "etf_observations": []},
        ):
            response = client.get("/us/stocks")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-market="US"', html)
        self.assertNotIn('data-dashboard-endpoint', html)
        self.assertNotIn("TAIEX", html)
        # ORDER 4（B-3）：0 件不再各佔一張卡片，改為摘要列裡的一個 0 件項目。
        # 守的性質不變 —— 每一類的件數都必須說出來，不能靜靜消失 —— 而且
        # 現在額外要求 0 件的類別不得展開為區塊（那正是 1,000px 空白的來源）。
        self.assertIn('<ul class="event-summary">', html)
        for label in ("異常上漲", "異常下跌", "量能異常", "法人動向", "技術面", "官方事件", "資料警示"):
            with self.subTest(label=label):
                self.assertIn(
                    f'<span class="event-summary-label">{label}</span>'
                    '<span class="event-summary-count">0 件</span>',
                    html,
                )
        self.assertEqual(html.count('class="event-summary-item is-empty"'), 7)
        self.assertNotIn('class="event-group"', html)
        self.assertIn("今天七類事件都沒有觸發。", html)
        self.assertIn('action="/search"', html)
        self.assertIn('name="market" value="US"', html)

        with patch.object(
            stock_app, "_published_us_securities_observation",
            side_effect=ValueError("unavailable"),
        ):
            unavailable = client.get("/us/stocks")
        self.assertEqual(unavailable.status_code, 503)
        self.assertIn("暫時無法取得", unavailable.get_data(as_text=True))

        with patch.object(
            stock_app, "_published_us_securities_observation", return_value={}
        ):
            malformed = client.get("/us/stocks")
        self.assertEqual(malformed.status_code, 503)
        self.assertNotIn(
            "目前沒有通過條件的異常事件。",
            malformed.get_data(as_text=True),
        )

        with patch.object(
            stock_app, "search_stock_code", return_value=("AAPL", "Apple Inc.")
        ):
            search = client.get("/search?q=AAPL&market=US")

        self.assertEqual(search.status_code, 302)
        self.assertTrue(search.headers["Location"].endswith("/stock/AAPL"))

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_market_page_accepts_production_data_quality_fields(self, load):
        snapshot = observation_dashboard()
        snapshot["data_quality"] = {
            "coverage": 0.998,
            "available_count": 2072,
            "failure_count": 4,
            "universe_count": 2076,
        }
        load.return_value = snapshot

        response = stock_app.app.test_client().get("/market")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("有效標的</dt><dd>2072</dd>", html)
        self.assertNotIn("有效標的</dt><dd>資料不足</dd>", html)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_web_security_headers_and_pinned_chart_supply_chain(
        self, fetch
    ):
        response = stock_app.app.test_client().get("/dashboard")
        csp = response.headers["Content-Security-Policy"]
        fetch.return_value = quant_snapshot()
        stock_html = stock_app.app.test_client().get(
            "/stock/2330"
        ).get_data(as_text=True)

        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertNotIn("'unsafe-inline'", csp)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("lightweight-charts@4.2.2", stock_html)
        self.assertIn('integrity="sha384-', stock_html)
        self.assertNotIn("style=", stock_html)

    def test_dashboard_page_is_the_observation_dashboard(self):
        with patch.object(stock_app, "analyze") as analyze, patch.object(
            stock_app,
            "_published_dashboard_snapshot",
            return_value=observation_dashboard(),
        ):
            response = stock_app.app.test_client().get("/dashboard")

        self.assertEqual(response.status_code, 200)
        analyze.assert_not_called()
        html = response.get_data(as_text=True)
        for label in (
            "台股今天怎麼了",
            "為什麼會這樣",
            "市場廣度",
            "期間報酬",
            "波動與風險",
            "產業相對強度",
            "資料覆蓋",
            "資料基準日 2026-07-15",
            "最新更新",
            "資料品質與限制",
            "產業觀察",
            "市場實況",
            "個股與 ETF",
            "ASK ABSORB",
            "AI 五日情境",
        ):
            self.assertIn(label, html)
        for forbidden in (
            "五日上漲機率",
            "精選標的",
            "產業預測",
            "data-top-picks",
        ):
            self.assertNotIn(forbidden, html)

    @patch.object(
        stock_app, "_published_dashboard_snapshot", return_value=observation_dashboard()
    )
    def test_dashboard_research_command_uses_verified_data_without_inline_styles(
        self, _load
    ):
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)

        for marker in (
            'data-research-summary',
            'data-market-command',
            'data-breadth-visual',
            'data-sector-flow',
            '<progress',
            'value="61.2"',
            '1200',
            '700',
            '17.5%',
            '半導體',
            '+1.85%',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        self.assertNotIn("23,742.18", html)
        self.assertNotIn("style=", html)

    def test_quick_ask_reuses_conversation_contract_and_has_dialog_controls(self):
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        for marker in (
            'data-quick-ask-open',
            'data-quick-ask-dialog',
            'role="dialog"',
            'aria-modal="true"',
            'data-conversation-endpoint="/api/conversation"',
            'data-market-context="TW"',
            'data-page-context="home"',
            'maxlength="1200"',
            'aria-live="polite"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        for marker in (
            "dataQuickAskOpen",
            'event.key === "Escape"',
            'event.key === "Tab"',
            'event.key.toLowerCase() === "k"',
            "querySelectorAll(\"[data-conversation-form]\")",
            "market: panel.dataset.marketContext",
            "page: panel.dataset.pageContext",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        self.assertNotIn(".innerHTML", script)

    def test_public_pages_only_request_private_account_state_when_session_cookie_exists(self):
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-account-session="anonymous"', html)
        self.assertIn('document.body.dataset.accountSession !== "present"', script)

    def test_report_filters_and_retry_control_have_progressive_enhancement(self):
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )
        unavailable = Path("templates/report_unavailable.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("[data-report-filter]", script)
        self.assertIn("[data-report-type]", script)
        self.assertIn("data-report-retry", unavailable)
        self.assertIn("window.location.reload()", script)

    def test_dashboard_has_route_based_section_navigation(self):
        html = stock_app.app.test_client().get(
            "/dashboard"
        ).get_data(as_text=True)

        for marker in (
            'href="/market"',
            'href="/industries"',
            'href="/stocks"',
            'href="/ask"',
            'href="/learn"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    @patch.object(stock_app, "_published_prediction_snapshot")
    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_chart_renders_only_verified_prediction_product(
        self, fetch, load_prediction
    ):
        fetch.return_value = quant_snapshot()
        load_prediction.return_value = prediction_product()

        response = stock_app.app.test_client().get("/stock/2330")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        for marker in (
            "五日上漲機率", "68.0%", "171.00", "+4.27%", "2026-07-22",
            '"time": "2026-07-22"', '"value": 171.0028',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("買進", html)
        self.assertNotIn("賣出", html)

    def test_dashboard_destinations_live_in_sidebar_navigation(self):
        """ORDER 4（A-4）：主導覽收為五個核心入口，ASK ABSORB 與學習降為輔助。

        §17 本來就寫「保留五個核心入口」，但側欄放了七項且無分組。
        兩個輔助入口仍在側欄內、仍可直達，只是不與每日決策路徑競爭。
        """
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
        primary_nav = html.split('<nav class="sidebar-nav" aria-label="主要功能"', 1)[1].split("</nav>", 1)[0]
        aux_nav = html.split('<nav class="sidebar-nav sidebar-aux"', 1)[1].split("</nav>", 1)[0]

        self.assertEqual(primary_nav.count('class="nav-link'), 5)
        for label in ("今天市場", "市場實況", "產業觀察", "個股與 ETF", "每日報告"):
            self.assertIn(f'<span class="nav-label">{label}</span>', primary_nav)
        self.assertNotIn('href="/ask"', primary_nav)
        self.assertNotIn('href="/learn"', primary_nav)

        self.assertIn('href="/ask"', aux_nav)
        self.assertIn('href="/learn"', aux_nav)
        self.assertNotIn('class="dashboard-destinations"', html)

    def test_order4_missing_value_style_wins_over_blanket_span_rules(self):
        """缺值格的字級不得被容器的 `.某容器 span` 規則蓋掉。

        這是 ORDER 4 白話標題被靜靜蓋掉的根因：版面各處有
        `.command-metrics span { font-size:11px }`、
        `.pulse-card span { font-size:13px }` 這類以元素選取的規則，
        特異性 (0,1,1) 高於單一 class 的 .value-unavailable (0,1,0)。
        type scale 測試看不出來 —— 11px 本來就在白名單內，
        宣告值全部合法，錯的是誰贏。

        這裡直接算級聯：找出所有會設 font-size 的 `.x span` 規則，
        要求 .value-unavailable 的規則同樣是元素限定（特異性打平），
        而且排在它們全部之後（來源順序取勝）。

        這條測試失敗時，正確的修法通常不是把 .value-unavailable 往後搬，
        而是把新寫的 `.某容器 span { font-size }` 改成 class 選取 ——
        以元素選取字級會攔截所有後來放進該容器的元件，不只是缺值格。
        """
        # 註解會黏在下一條選擇器前面，先移除（長度以空白補回，維持位移可比）
        css = re.sub(
            r"/\*.*?\*/", lambda m: " " * len(m.group(0)), css_bundle(), flags=re.S
        )
        rules = []
        offset = 0
        for chunk in css.split("}"):
            if "{" not in chunk:
                offset += len(chunk) + 1
                continue
            selector, body = chunk.split("{", 1)
            rules.append((offset, re.sub(r"\s+", " ", selector.strip()), body))
            offset += len(chunk) + 1

        blanket = [
            (pos, sel)
            for pos, sel, body in rules
            if "font-size" in body
            and any(
                re.fullmatch(r"\.[a-z0-9-]+ (?:span|small)", part.strip())
                for part in sel.split(",")
            )
        ]
        self.assertTrue(blanket, "測試前提消失：已無容器層級的 span 字級規則")

        winners = [
            pos
            for pos, sel, body in rules
            if "font-size" in body
            and any(
                part.strip() == "span.value-unavailable" for part in sel.split(",")
            )
        ]
        self.assertEqual(len(winners), 1, "span.value-unavailable 應只有一條字級規則")
        for pos, sel in blanket:
            with self.subTest(selector=sel):
                self.assertLess(pos, winners[0])

    def test_order4_direction_elements_always_carry_a_sign_or_word(self):
        """M-5／§12.1 第 02 項：灰階下漲跌仍可辨識。

        顏色是唯一線索時，色覺障礙與灰階列印都會失去方向資訊。
        這裡把實際繪出的 HTML 裡所有帶方向 class 的元素抓出來，
        要求文字本身含正負號或方向字詞 —— 或者，對 <dd> 而言，
        由緊鄰的 <dt> 標籤承擔（「上漲 / 1200」這一組整體是有文字的）。
        """
        snapshot = observation_dashboard()
        snapshot["market_index"] = {
            "name": "加權指數", "as_of": "2026-07-15", "price": 23450.12,
            "open": 23300.0, "high": 23500.0, "low": 23280.0,
            "change": 150.12, "change_pct": 0.64,
            "candles": [
                {"time": "2026-07-1%d" % i, "open": 1, "high": 2, "low": 0.5, "close": 1.5}
                for i in range(1, 6)
            ],
            "ma20": [],
        }
        client = stock_app.app.test_client()
        unsigned = []
        with patch.object(
            stock_app, "_published_dashboard_snapshot", return_value=snapshot
        ):
            for path in ("/", "/market", "/industries", "/stocks"):
                html = client.get(path).get_data(as_text=True)
                # <dt>上漲</dt><dd class="positive">1200</dd>：方向由 dt 承擔，
                # 這一組整體在灰階下仍然讀得出來，標記後放行。
                html = re.sub(
                    r"<dt>[^<]*(?:上漲|下跌|新高|新低|轉強|轉弱)[^<]*</dt>\s*<dd([^>]*)>",
                    r"<dd\1>DT_LABELLED ",
                    html,
                )
                for match in re.finditer(
                    r'<(?:dd|strong|span|p|b)[^>]*class="[^"]*\b(?:positive|negative|up|down)\b'
                    r'[^"]*"[^>]*>(.*?)</(?:dd|strong|span|p|b)>',
                    html,
                    re.S,
                ):
                    text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
                    if not text:
                        continue
                    if not re.search(
                        r"[+\-−▲▼]|上漲|下跌|轉強|轉弱|新高|新低|DT_LABELLED", text
                    ):
                        unsigned.append((path, text[:40]))
        self.assertEqual(unsigned, [])

    def test_order5_report_tracks_degrade_without_javascript(self):
        """§6.2：三個分頁在 HTML 裡必須預設全部可見，由 JS 才收起兩個。

        如果模板直接輸出 hidden，JS 失效（載入失敗、CSP 擋下、舊瀏覽器）
        時就會有三分之二的已發布內容看不到。列印時同理必須全開。
        """
        template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "reports"
            / "post_close_professional.html"
        ).read_text(encoding="utf-8")
        panels = re.findall(r"<div class=\"report-track\"[^>]*>", template)
        self.assertEqual(len(panels), 3)
        for panel in panels:
            with self.subTest(panel=panel[:60]):
                self.assertNotIn("hidden", panel)

        css = css_bundle()
        self.assertRegex(
            css, r"@media print\s*\{[^}]*\.report-track\[hidden\]\s*\{[^}]*display:block"
        )

        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")
        block = script[script.index("function initReportTracks"):]
        block = block[: block.index("\nfunction ")]
        self.assertIn("panel.hidden = panelKey !== key", block)
        # 跨分頁的錨點必須先切分頁再捲，否則章節索引會靜靜失效
        self.assertIn("revealHash", block)
        self.assertIn('window.addEventListener("hashchange"', block)

    def test_order5_anomaly_table_never_sorts_missing_values_as_zero(self):
        """F-7：缺值不是 0。

        Number("") 是 0 —— 直接把 dataset 轉數字，「尚未驗證」會排到 0 的
        位置，等於在排序結果裡宣稱它有值。缺值必須永遠墊底，而且不隨
        升冪／降冪翻面：缺值不是「最小」，是「沒有」。
        """
        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")
        block = script[script.index("function initAnomalyTable"):]
        block = block[: block.index("\nfunction ") if "\nfunction " in block else len(block)]

        self.assertNotIn("Number.NEGATIVE_INFINITY", block)
        self.assertIn('if (raw === undefined || raw.trim() === "") return null;', block)
        self.assertIn("return left === null ? 1 : -1;", block)
        # 篩選只改 row.hidden，不重建 DOM（重建會丟掉捲動位置）
        self.assertIn("row.hidden = !show;", block)
        self.assertNotIn("innerHTML", block)
        # 剪貼簿失敗時不得假裝成功
        self.assertIn("複製失敗", block)

    def test_order5_every_term_tag_resolves_to_a_matching_learn_entry(self):
        """§2.4／§12.1 第 05 項：每個術語標籤必須連到「它自己」的條目。

        ORDER 4 加術語標籤時，「風險狀態」指到已實現波動、「法人淨流」指到
        相對大盤報酬 —— 錨點都存在，頁面也不會壞，所以沒有任何測試會紅，
        但點下去看到的是另一個指標的解釋。這裡除了檢查錨點存在，
        還要求標籤文字與該條目的標題或別名對得上。
        """
        client = stock_app.app.test_client()
        learn = client.get("/learn").get_data(as_text=True)

        entries = {}
        for match in re.finditer(
            r'<article class="learn-term" id="([a-z-]+)"[^>]*>(.*?)</article>',
            learn,
            re.S,
        ):
            entries[match.group(1)] = re.sub(r"<[^>]+>", " ", match.group(2))
        self.assertTrue(entries, "學習頁沒有任何詞條")

        tags = []
        for path in ("/", "/market", "/industries", "/stocks"):
            html = client.get(path).get_data(as_text=True)
            tags += re.findall(
                r'<a class="term-tag" href="/learn#([a-z-]+)">([^<]+)</a>', html
            )
        self.assertTrue(tags, "主版面沒有任何術語標籤")

        for target, label in tags:
            with self.subTest(label=label):
                self.assertIn(target, entries, f"{label} 指向不存在的條目 {target}")
                body = entries[target]
                # 標籤文字必須出現在該條目裡（標題、別名或說明），
                # 否則就是連到另一個指標的解釋
                self.assertIn(label.replace(" ", ""), body.replace(" ", ""))

    def test_order5_learn_page_answers_four_questions_per_term(self):
        """§2.4：辭典只回答「這是什麼」，四欄才回答得完讀者真正卡住的地方。"""
        learn = stock_app.app.test_client().get("/learn").get_data(as_text=True)

        for column in ("白話定義", "如何閱讀", "常見誤解", "在 ABSORB 哪裡出現"):
            with self.subTest(column=column):
                # 每個詞條都要有這四欄
                self.assertEqual(
                    learn.count(f"<dt>{column}</dt>"), learn.count('class="learn-term"')
                )

        # D-5：方法限制是全站合規上最重要的一段，不得用最小字級
        css = css_bundle()
        rule = css[css.index(".risk-panel>p"):]
        rule = rule[: rule.index("}")]
        self.assertIn("font-size:15px", rule)
        self.assertNotIn("font-size:11px", rule)

    @patch.object(stock_app, "find_industry_peers")
    @patch.object(stock_app, "get_stock_name")
    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_order5_stock_page_separates_facts_from_model_estimate(
        self, fetch, name, peers
    ):
        """§7-3：「已發生事件」與「五日模型情境」必須視覺分區。

        預測摘要原本就放在價格面板裡，跟實際 K 線共用同一張卡 ——
        讀者沒有任何線索可以判斷哪些數字是已經發生的、哪些是估計出來的。
        """
        fetch.return_value = quant_snapshot()
        name.return_value = "聯發科"
        peers.return_value = {"category": "半導體", "codes": ["2454"]}

        html = stock_app.app.test_client().get("/stock/2330").get_data(as_text=True)

        # 預測摘要不得再出現在價格面板內
        chart = html[html.index('class="panel chart-shell"'):]
        chart = chart[: chart.index("</section>")]
        self.assertNotIn("stock-forecast-strip", chart)
        # 而是自成一個明說「這是估計」的區塊
        self.assertIn('id="forecast"', html)
        self.assertIn("五日模型情境", html)
        self.assertIn("以下數字全部是模型估計，不是已經發生的資料", html)
        # 圖例必須分辨已發生與估計
        self.assertIn("已發生：近 20 個交易日收盤平均", html)

        # 三維速讀卡
        self.assertEqual(html.count('class="quick-read-card"'), 3)
        # 風險內容只出現一次 —— 速讀卡接手後，舊的風險面板必須移除
        self.assertEqual(html.count('id="risk"'), 1)
        self.assertEqual(html.count("風險事件"), 1)

        # 欄位解釋不得自建第二套，必須連回學習頁
        self.assertNotIn("MA20 與 MA60 是過去收盤價平均", html)
        self.assertIn('href="/learn#term-institution-flow"', html)

    def test_order6_empty_state_spans_its_grid_container(self):
        """D-1：空狀態文字逐字換行。

        .empty-state 經常被放進 grid 容器（事件清單、卡片格、更新流）。
        沒有 grid-column 時它會掉進第一個欄軌 —— 原本 .verified-focus li
        的 30px 編號欄就把「今日焦點資料暫時無法取得。」渲染成每行一個字。
        """
        css = css_bundle()
        rule = css[css.index(".empty-state {"):]
        rule = rule[: rule.index("}")]
        self.assertIn("grid-column:1 / -1", rule)

    def test_order6_design_doc_glossary_matches_the_live_term_tags(self):
        """§30：術語對照表是唯一事實來源，就必須跟畫面一致。

        DESIGN.md 寫了一套、模板連另一套，是本次改版最根本的診斷（C-1）
        「既有設計規範沒有被遵守」的同一種病。
        """
        design = (Path(__file__).resolve().parents[1] / "DESIGN.md").read_text(
            encoding="utf-8"
        )
        table = design[design.index("## 30. 術語對照表"):]
        documented = set(re.findall(r"`#(term-[a-z-]+)`", table))
        self.assertTrue(documented, "對照表沒有任何錨點")

        client = stock_app.app.test_client()
        used = set()
        for path in ("/", "/market", "/industries", "/stocks", "/stock/2330"):
            used |= set(
                re.findall(
                    r'class="term-tag" href="/learn#(term-[a-z-]+)"',
                    client.get(path).get_data(as_text=True),
                )
            )
        self.assertTrue(used, "畫面上沒有任何術語標籤")
        self.assertEqual(used - documented, set(), "有術語標籤沒有寫進對照表")

        learn = client.get("/learn").get_data(as_text=True)
        for anchor_id in documented:
            with self.subTest(anchor=anchor_id):
                self.assertIn(f'id="{anchor_id}"', learn)

    def test_order6_main_surface_terms_always_carry_a_plain_language_title(self):
        """§12.2 第 8 項：主版面不得出現未配對白話標題的術語字串。

        A-6 的原始診斷是「主版面是散戶入口卻直接用研究者術語」。術語不刪除，
        降級為標籤並連到學習頁 —— 但那只有在術語**只**出現在標籤裡才成立。
        術語若同時以主標題出現，白話化就被抵銷了。

        兩個合法位置：`.term-tag` 標籤，或預設收合的「資料品質與限制 /
        進階數據」區塊（§5.5 明文允許在那裡用原始欄位名稱）。
        """
        root = Path(__file__).resolve().parents[1] / "templates"
        terms = ("MA20", "MA60", "已實現波動", "淨流中位", "量比", "RSI", "Brier")
        offenders = []
        for name in ("dashboard.html", "market.html", "industries.html", "stocks.html"):
            text = (root / name).read_text(encoding="utf-8")
            text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)          # Jinja 註解
            text = re.sub(r'<a class="term-tag".*?</a>', "", text, re.S)  # 合法：術語標籤
            text = re.sub(r"<details class=\"data-limits\">.*?</details>", "", text, flags=re.S)
            for term in terms:
                for match in re.finditer(re.escape(term), text):
                    start = max(0, match.start() - 60)
                    offenders.append((name, term, text[start:match.end() + 20].strip()[-70:]))
        self.assertEqual(offenders, [])

    def test_order5_chapter_nav_tracks_position_without_scroll_handlers(self):
        """A-7：章節索引必須給位置回饋，而且不得用 scroll 事件做版面量測。

        十章、超過 700 行的報告捲動時，讀者無從判斷自己在哪一章。
        用 IntersectionObserver 而非 scroll listener —— 後者每次捲動都會
        觸發 getBoundingClientRect，在長報告上是實際可感的卡頓來源。
        """
        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")
        block = script[script.index("function initReportChapterNav"):]
        block = block[: block.index("\nfunction ")]

        self.assertIn("IntersectionObserver", block)
        self.assertNotIn('addEventListener("scroll"', block)
        self.assertNotIn("getBoundingClientRect", block)
        # 位置回饋不只靠顏色（M-5 的同一條原則）
        css = css_bundle()
        rule = css[css.index(".report-chapter-nav a.is-current"):]
        rule = rule[: rule.index("}")]
        self.assertIn("font-weight", rule)
        self.assertIn("box-shadow", rule)

    def test_order4_back_links_name_their_destination(self):
        """§5.1：明細頁的上一層必須具名（「返回個股與 ETF」而非泛用返回）。

        泛用的「返回」在多入口的頁面上沒有意義 —— 讀者可能從個股清單、
        產業觀察或搜尋結果進來，看到「返回」也不知道會去哪裡。
        這裡掃模板原始碼，因為有些明細頁在測試環境取不到資料。
        """
        root = Path(__file__).resolve().parents[1] / "templates"
        generic = []
        for path in sorted(root.rglob("*.html")):
            for match in re.finditer(
                r'class="back-link"[^>]*>([^<]+)</a>',
                path.read_text(encoding="utf-8"),
            ):
                label = match.group(1).strip()
                if label in ("返回", "回上一頁", "上一頁", "Back", "返回上一層"):
                    generic.append((path.name, label))
                # 具名＝「返回」後面還有目的地名稱
                self.assertTrue(
                    label.startswith("返回") and len(label) > len("返回"),
                    f"{path.name}: {label}",
                )
        self.assertEqual(generic, [])

    def test_order4_units_never_render_without_their_value(self):
        """B-2：缺值時數值與單位必須一起消失。

        原本寫成 {{ 值 if 值 is not none else '—' }}%，百分號在條件式外面，
        缺值時輸出裸的「—%」；家數用 `or` 判斷，0 這個真實數值也會被
        當成缺值。這裡直接掃模板原始碼 —— 只驗算繪出的 HTML 會漏掉
        目前恰好有資料的欄位。
        """
        root = Path(__file__).resolve().parents[1] / "templates"
        offenders = []
        for name in ("dashboard.html", "market.html", "industries.html", "stocks.html"):
            text = (root / name).read_text(encoding="utf-8")
            # Jinja 註解裡會引用反例說明，不列入掃描
            text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
            # 條件式結束後緊接單位字元
            for match in re.finditer(r"\{\{[^{}]*is not none else[^{}]*\}\}\s*([%倍點])", text):
                offenders.append((name, match.group(0)[:60]))
            # `or '—'`：把 0 當成缺值
            for match in re.finditer(r"\bor\s*'—'", text):
                offenders.append((name, match.group(0)))
        self.assertEqual(offenders, [])

    def test_order4_market_chart_declares_its_own_legend_and_limits(self):
        """§5.5：每張圖必須自己說清楚資料日、單位、圖例與界線。"""
        snapshot = observation_dashboard()
        snapshot["market_index"] = {
            "name": "加權指數", "as_of": "2026-07-15", "price": 23450.12,
            "open": 23300.0, "high": 23500.0, "low": 23280.0,
            "change": 150.12, "change_pct": 0.64,
            "candles": [
                {"time": "2026-07-1%d" % i, "open": 1, "high": 2, "low": 0.5, "close": 1.5}
                for i in range(1, 6)
            ],
            "ma20": [{"time": "2026-07-1%d" % i, "value": 1.2} for i in range(1, 6)],
        }
        with patch.object(
            stock_app, "_published_dashboard_snapshot", return_value=snapshot
        ):
            html = stock_app.app.test_client().get("/market").get_data(as_text=True)

        self.assertEqual(html.count("legend-swatch"), 3)
        self.assertIn("資料日 2026-07-15", html)
        self.assertIn("單位</dt><dd>指數點數</dd>", html)
        self.assertIn("這不代表什麼：", html)

    def test_order4_chart_ma_line_reads_a_token_with_sufficient_contrast(self):
        """M-4／WCAG 1.4.11：均價線不得寫死顏色，且對底色至少 3:1。

        原本 app.js 寫死 #7aa6b3，對 --absorb-surface 只有 2.45:1。
        ORDER 1 的反向白名單只檢查 K 線與預測線，看不到這一條。
        """
        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")
        self.assertNotIn("#7aa6b3", script)
        self.assertIn('getPropertyValue("--chart-ma")', script)

        css = css_bundle()
        alias = re.search(r"--chart-ma:var\((--[a-z-]+)\)", css).group(1)
        value = re.search(re.escape(alias) + r":(#[0-9a-f]{6})", css).group(1)
        surface = re.search(r"--absorb-surface:(#[0-9a-f]{6})", css).group(1)

        def relative_luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [
                c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                for c in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        lighter, darker = sorted(
            (relative_luminance(value), relative_luminance(surface)), reverse=True
        )
        self.assertGreaterEqual((lighter + 0.05) / (darker + 0.05), 3.0)

    def test_order4_ask_examples_are_page_specific_and_never_auto_submit(self):
        """A-8：浮動面板的問題範例必須隨頁面改變，且只填入不送出。

        「不自動送出」是這一條的重點：自動送出會替使用者做決定，而且送出的
        問題不見得是他想問的。這裡守的是 JS 端沒有 submit()／requestSubmit()
        ——  範例按鈕本身是 type="button"，不會誤觸表單送出。
        """
        client = stock_app.app.test_client()
        seen = {}
        for path in ("/", "/market", "/industries", "/stocks", "/reports", "/learn"):
            with self.subTest(path=path):
                html = client.get(path).get_data(as_text=True)
                examples = re.findall(
                    r'<button class="quick-ask-example" type="button" '
                    r'data-quick-ask-example>([^<]+)</button>',
                    html,
                )
                self.assertEqual(len(examples), 3, examples)
                seen[path] = tuple(examples)
        # 每一頁的範例都不同 —— 否則「與目前頁面相關」只是說說而已
        self.assertEqual(len(set(seen.values())), len(seen), seen)

        script = Path(stock_app.app.static_folder, "app.js").read_text(encoding="utf-8")
        block = script[script.index("function initAskExamples"):]
        block = block[: block.index("\nfunction ")]
        self.assertIn("input.value = button.textContent.trim();", block)
        for forbidden in ("submit()", "requestSubmit()", "dispatchEvent"):
            self.assertNotIn(forbidden, block)

    def test_order4_ask_surfaces_state_distinct_purposes(self):
        """A-8：浮動面板與完整頁必須各自說清楚定位，否則兩者功能重疊。"""
        client = stock_app.app.test_client()
        home = client.get("/").get_data(as_text=True)
        ask = client.get("/ask").get_data(as_text=True)

        # 浮動面板：針對目前頁面，且指得出完整頁在哪
        self.assertIn("針對你正在看的這一頁追問", home)
        self.assertIn('href="/ask">完整頁', home)
        # 完整頁：跨市場、跨報告，且不再重複掛浮動鈕
        self.assertIn("跨市場、跨報告的研究對話", ask)
        self.assertNotIn("quick-ask-trigger", ask)
        # 兩個介面都必須帶同一條限制聲明
        for html in (home, ask):
            self.assertIn("依已發布資料與模型結果回答，不提供買賣指令。", html)

    def test_order4_footer_reserves_space_for_the_floating_trigger(self):
        """D-2：浮動鈕是 fixed，捲到底也躲不掉，底部必須留出大於它的距離。"""
        css = css_bundle()
        trigger = css[css.index(".quick-ask-trigger {"):]
        trigger = trigger[: trigger.index("}")]
        min_height = int(re.search(r"min-height:(\d+)px", trigger).group(1))
        bottom = int(re.search(r"bottom:(\d+)px", trigger).group(1))
        footer = css[css.rindex(".site-footer { padding-bottom:"):]
        reserved = int(re.search(r"padding-bottom:(\d+)px", footer).group(1))
        self.assertGreater(reserved, min_height + bottom)

    def test_market_switch_sits_above_the_navigation_it_governs(self):
        """ORDER 4（A-4）：市場切換器決定側欄所有項目的內容，必須在它們之上。"""
        html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
        sidebar = html.split('<aside class="dashboard-sidebar"', 1)[1].split("</aside>", 1)[0]
        self.assertIn("data-market-switch", sidebar)
        self.assertLess(
            sidebar.index("data-market-switch"),
            sidebar.index('<nav class="sidebar-nav" aria-label="主要功能"'),
        )
        topbar = html.split('<div class="topbar"', 1)[1].split("</div>", 1)[0]
        self.assertNotIn("data-market-switch", topbar)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_industries_merge_strength_and_attention_companies(self, load_snapshot):
        snapshot = observation_dashboard()
        snapshot["industry_observations"][0].update(
            {
                "relative_return_5d_pct": 2.85,
                "ranking_basis": "actual_momentum",
                "attention_companies": [
                    {
                        "symbol": "2330",
                        "name": "台積電",
                        "price": 1245.0,
                        "return_5d_pct": 8.2,
                        "above_ma20": True,
                        "volume_ratio": 1.8,
                        "as_of": "2026-07-15",
                    }
                ],
            }
        )
        load_snapshot.return_value = snapshot

        html = stock_app.app.test_client().get("/industries").get_data(as_text=True)

        self.assertNotIn("產業實際強弱", html)
        self.assertEqual(html.count('data-industry-disclosure'), 1)
        # ORDER 4（§5.5）：強弱改由分組承擔，不再是每張卡片的 hot/cold 色條
        # （§0.4 禁止「左側彩色 accent 邊條 + 圓角卡」，M-5 禁止只靠顏色）。
        # 守的性質不變：+2.85% 必須被歸成「強」。現在還額外要求它落在
        # 具名的分組裡，而不是只有一個顏色。
        self.assertNotIn('industry-disclosure hot', html)
        self.assertNotIn('industry-disclosure cold', html)
        self.assertIn('id="industry-group-hot">值得注意</h3>', html)
        self.assertLess(
            html.index('id="industry-group-hot"'), html.index('data-industry-disclosure')
        )
        self.assertIn("實際動能排序", html)
        self.assertIn('href="/stock/2330"', html)
        self.assertIn("台積電 · 2330", html)
        self.assertIn("5 日 +8.20%", html)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_industries_render_verified_ai_fields_when_published(self, load_snapshot):
        snapshot = observation_dashboard()
        snapshot["industry_observations"][0].update(
            {
                "ranking_basis": "verified_ai_forecast",
                "attention_companies": [
                    {
                        "symbol": "2330",
                        "name": "台積電",
                        "price": 1245.0,
                        "return_5d_pct": 8.2,
                        "above_ma20": True,
                        "volume_ratio": 1.8,
                        "as_of": "2026-07-15",
                        "probability_up_pct": 68.4,
                        "target_price": 1272.5,
                    }
                ],
            }
        )
        load_snapshot.return_value = snapshot

        html = stock_app.app.test_client().get("/industries").get_data(as_text=True)

        self.assertIn("AI 五日模型排序", html)
        self.assertIn("68.4%", html)
        self.assertIn("第 5 日 1,272.50", html)

    @patch.object(
        stock_app, "_published_dashboard_snapshot", return_value=observation_dashboard()
    )
    def test_navigation_has_route_active_state_and_no_primary_hash_links(self, _load):
        client = stock_app.app.test_client()
        for path, label in (
            ("/dashboard", "今天市場"),
            ("/market", "市場實況"),
            ("/industries", "產業觀察"),
            ("/stocks", "個股與 ETF"),
            ("/reports", "每日報告"),
        ):
            with self.subTest(path=path):
                html = client.get(path).get_data(as_text=True)
                self.assertIn(
                    f'class="nav-link active" href="{path if path != "/dashboard" else "/"}" aria-label="{label}" aria-current="page"',
                    html,
                )
        home = client.get("/dashboard").get_data(as_text=True)
        primary_nav = home.split('<nav class="sidebar-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn('href="#', primary_nav)
        self.assertNotIn('class="mobile-nav"', home)
        self.assertIn('aria-current="page"><span class="nav-short"', primary_nav)
        ask = client.get("/ask").get_data(as_text=True)
        self.assertIn('<h1>ASK ABSORB</h1>', ask)

    def test_legacy_hash_migrator_uses_only_fixed_canonical_routes(self):
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        expected = {
            '"#market-pulse": "/market"',
            '"#market-heatmap": "/industries"',
            '"#industry-observations": "/industries"',
            '"#stock-search": "/stocks"',
            '"#stock-events": "/stocks"',
            '"#etf-observations": "/stocks?tab=etf"',
            '"#learn": "/learn"',
            '"#daily-focus": "/"',
        }
        for mapping in expected:
            self.assertIn(mapping, script)
        self.assertIn(
            "if(!['/','/dashboard'].includes",
            script.replace('"', "'").replace(" ", ""),
        )
        self.assertNotIn("window.location.hash.slice", script)

    @patch.object(stock_app, "analyze")
    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_dashboard_api_returns_verified_observation_without_analysis(
        self, load_snapshot, analyze
    ):
        load_snapshot.return_value = observation_dashboard()

        response = stock_app.app.test_client().get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        analyze.assert_not_called()
        self.assertEqual(payload["product_mode"], "observation")
        self.assertEqual(payload["observation_as_of"], "2026-07-15")
        self.assertEqual(
            payload["market_observation"]["advancing_count"], 1200
        )
        self.assertEqual(
            payload["industry_observations"][0]["name"], "半導體"
        )
        self.assertEqual(payload["prediction_status"], "AI 預測研究中")
        self.assertNotIn("top_picks", payload)
        self.assertNotIn("opportunities", payload)

    @patch.object(stock_app, "analyze")
    @patch.object(
        stock_app, "_published_dashboard_snapshot", return_value=None
    )
    def test_dashboard_api_fails_closed_without_snapshot(
        self, _load_snapshot, analyze
    ):
        response = stock_app.app.test_client().get("/api/dashboard")

        self.assertEqual(response.status_code, 503)
        analyze.assert_not_called()
        self.assertEqual(
            response.get_json()["status"], "observation_unavailable"
        )

    def test_preview_report_is_not_public_without_preview_prefix(self):
        response = stock_app.app.test_client().get("/preview/report")

        self.assertEqual(response.status_code, 404)

    @patch.object(stock_app, "analyze")
    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_preview_dashboard_keeps_isolated_candidate_api(
        self, load_snapshot, analyze
    ):
        analyze.return_value = {
            "price": 23150.0,
            "prob": 58,
            "trend": "多頭",
            "as_of": "2026-07-15",
            "recommendation": {},
        }
        load_snapshot.return_value = {
            "baseline_status": "initial_backtest_bootstrap",
            "inference_as_of": "2026-07-15",
            "backtest_as_of": None,
            "model_version": "lgbm-5d-v1",
            "backtest_version": None,
            "feature_schema_version": 1,
            "recommendation_policy_version": "recommendation-v1",
            "presentation": {
                "model_output_label": "模型方向分數",
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "sector_snapshot": {
                "sectors": {
                    "網通設備": [
                        {
                            "code": "4906",
                            "name": "正文",
                            "prob": 73.7,
                            "trend": "跌破 MA20",
                            "as_of": "2026-07-15",
                        }
                    ]
                }
            },
            "heatmap": [{"name": "網通設備", "tone": "steady"}],
            "daily_focus": ["candidate focus"],
            "top_picks": [{"code": "4906", "name": "正文"}],
        }
        with patch.object(
            stock_app, "PREVIEW_CANDIDATE_PREFIX", "previews/demo"
        ), patch.object(stock_app, "cached_opportunities", return_value=[]):
            response = stock_app.app.test_client().get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["inference_as_of"], "2026-07-15")
        self.assertEqual(payload["sector_cards"][0]["leader"]["code"], "4906")
        self.assertEqual(payload["daily_focus"], ["candidate focus"])

    @patch.object(
        stock_app,
        "find_industry_peers",
        return_value={"category": "半導體", "codes": ["2454"]},
    )
    @patch.object(stock_app, "get_stock_name", return_value="聯發科")
    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_page_is_the_observation_workspace(
        self, fetch, _name, _peers
    ):
        fetch.return_value = quant_snapshot()

        response = stock_app.app.test_client().get("/stock/2330")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        for label in (
            "個股觀察摘要",
            "價格與均線",
            "籌碼觀察",
            "技術指標",
            "風險事件",
            "欄位怎麼看",
            "產業同儕",
            "聯發科",
        ):
            self.assertIn(label, html)
        for forbidden in (
            "五日上漲機率",
            "投資金額試算",
            "支持這項建議",
            "回測",
            "勝率",
        ):
            self.assertNotIn(forbidden, html)
        self.assertIn("data-watchlist-toggle", html)
        self.assertIn("data-chart-range", html)
        self.assertIn('aria-label="個股觀察導覽"', html)
        self.assertIn('class="back-link" href="/stocks">返回個股與 ETF', html)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_page_does_not_render_untrusted_snapshot_news(self, fetch):
        snapshot = quant_snapshot()
        snapshot["news"] = [
            {
                "title": "不安全來源",
                "link": "javascript:alert(1)",
            }
        ]
        fetch.return_value = snapshot

        html = stock_app.app.test_client().get(
            "/stock/2330"
        ).get_data(as_text=True)

        self.assertNotIn("不安全來源", html)
        self.assertNotIn('href="javascript:', html)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_page_accepts_standard_us_ticker(self, fetch):
        fetch.return_value = quant_snapshot("AAPL", market="US")

        response = stock_app.app.test_client().get("/stock/AAPL")

        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with("AAPL")
        self.assertIn(
            'class="back-link" href="/us/stocks">返回個股與 ETF',
            response.get_data(as_text=True),
        )

    def test_dashboard_script_does_not_insert_api_text_with_inner_html(self):
        script = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(".innerHTML", script)
        self.assertIn("AbortController", script)
        self.assertNotIn('title: "五日預測"', script)

    def test_web_is_observation_only_and_old_watchlist_redirects(self):
        response = stock_app.app.test_client().get("/watchlist")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))

    @patch.object(stock_app, "analyze")
    def test_stock_summary_api_removed_with_browser_watchlist(self, analyze):
        response = stock_app.app.test_client().get(
            "/api/stock/2330/summary"
        )

        self.assertEqual(response.status_code, 404)
        analyze.assert_not_called()

    def test_line_navigation_maps_six_observation_entries(self):
        navigation = stock_app.build_line_navigation_flex(
            "https://example.com/"
        )

        self.assertEqual(navigation["type"], "carousel")
        self.assertEqual(len(navigation["contents"]), 6)
        actual_uri = {}
        actual_message = {}
        for card in navigation["contents"]:
            action = card["footer"]["contents"][0]["action"]
            title = card["body"]["contents"][0]["text"]
            if action["type"] == "uri":
                actual_uri[title] = action["uri"]
            else:
                actual_message[title] = action["text"]
        self.assertEqual(
            actual_uri,
            {
                "看大盤": "https://example.com/market",
                "看產業": "https://example.com/industries",
                "市場觀察": "https://example.com/dashboard",
            },
        )
        self.assertEqual(
            actual_message,
            {
                "查自選": "我的關注",
                "設提醒": "提醒管理",
                "查股票": "2330",
            },
        )

    def test_rich_menu_source_matches_observation_navigation(self):
        svg = Path("assets/rich-menu.svg").read_text(encoding="utf-8")

        for label in (
            "看大盤",
            "看產業",
            "查自選",
            "設提醒",
            "查股票",
            "市場觀察",
        ):
            self.assertIn(label, svg)
        for removed in (
            "找機會",
            "算報酬",
            "深度分析",
            "熱門題材與排行",
            "投入金額快速試算",
            "圖表、回測、新聞",
        ):
            self.assertNotIn(removed, svg)
        for marker in ("ABSORB", "#122643", "#ffffff", "#eaf0f7"):
            self.assertIn(marker, svg)

    def test_line_summary_card_has_one_clear_cta(self):
        card = stock_app.build_line_summary_card(
            "市場觀察",
            ["2330 台積電", "最新收盤 1000.00"],
            "查看完整觀察",
            "https://example.com/stock/2330",
        )

        self.assertEqual(len(card["footer"]["contents"]), 1)
        self.assertEqual(
            card["footer"]["contents"][0]["action"]["uri"],
            "https://example.com/stock/2330",
        )

    def test_web_shell_supports_keyboard_and_mobile_interactions(self):
        response = stock_app.app.test_client().get("/dashboard")
        html = response.get_data(as_text=True)
        css = css_bundle()

        for marker in (
            'class="skip-link"',
            'id="main-content"',
            'aria-live="polite"',
        ):
            self.assertIn(marker, html)
        for rule in (
            ":focus-visible",
            "prefers-reduced-motion",
            "min-height:44px",
        ):
            self.assertIn(rule, css)
        self.assertIn(".dashboard-sidebar", css)
        self.assertIn('aria-controls="dashboard-sidebar"', html)
        self.assertIn('<span class="nav-label">每日報告</span>', html)

    def test_web_shell_serves_one_wordmark_font_across_devices(self):
        client = stock_app.app.test_client()
        response = client.get("/static/fonts/absorb-wordmark-allura.woff2")
        font_payload = response.get_data()
        response.close()
        css = css_bundle()

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(font_payload), 1_000)
        self.assertIn('font-family:"ABSORB Wordmark"', css)
        self.assertIn(
            'url("fonts/absorb-wordmark-allura.woff2") format("woff2")', css
        )
        self.assertIn(
            'font-family:"ABSORB Wordmark","Segoe Script","Brush Script MT",cursive',
            css,
        )
        self.assertIn("-webkit-text-stroke:.024em currentColor", css)
        # ORDER 2 之後 app.css 是展開的六檔串接，不再是單行壓縮檔，
        # 逐字比對規則內容要用 compact 形式。
        compact = css_compact()
        self.assertIn(".brand-wordmark{", compact)
        # 30px 不在 type scale 八級內（M-3 封閉集合），改用 32px；
        # Allura 字面比 Caveat 小，取較大的一級補回等視覺大小。
        self.assertIn("font-size:32px;font-weight:400;letter-spacing:0", compact)

    def test_web_shell_uses_softened_neutral_paper_surfaces(self):
        css = css_bundle()
        manifest = json.loads(
            Path(stock_app.app.static_folder, "manifest.webmanifest").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("--absorb-surface:#f7f6f2", css)
        self.assertIn("background:var(--absorb-surface)", css)
        self.assertNotIn("gradient", css)
        self.assertNotIn("backdrop-filter", css)
        self.assertEqual(manifest["background_color"], "#f7f6f2")

    def test_research_layout_supports_4k_and_tall_ask_workspace(self):
        css = css_compact()

        self.assertIn("--absorb-content-max:3200px", css)
        self.assertIn("@media(min-width:1800px)", css)
        # ORDER 3：18px／17px 不在 type scale 八級內，依 §9.4 收斂至 subtitle 19px（C-2）
        self.assertIn("body{font-size:19px;}", css)
        self.assertIn(".nav-link{font-size:19px;}", css)
        self.assertIn("height:60vh", css)
        self.assertIn(".quick-ask-log{flex:1", css)
        self.assertIn(".industry-disclosure-list{", css)
        # ORDER 4（§5.5 / §0.4 / M-5）：產業強弱改由分組承擔，
        # hot/cold 的左側彩色邊條 + 底色是 §0.4 明令禁止的手法，
        # 而且灰階下 hot 與 cold 長得一樣。守的性質不變（強弱必須有
        # 視覺處理），但改為具名分組，且明確擋住色條回來。
        self.assertIn(".industry-group-heading{", css)
        self.assertNotIn(".industry-disclosure.hot{", css)
        self.assertNotIn(".industry-disclosure.cold{", css)
        self.assertNotIn(".industry-disclosure.steady{", css)

    def test_browser_bundle_has_no_local_watchlist_storage(self):
        source = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        for removed in (
            "localStorage",
            "quant-watchlist",
            "data-alert-open",
            "data-alert-form",
        ):
            self.assertNotIn(removed, source)
        self.assertIn("if (!entries.length) return", source)

    def test_health_check_is_separate_from_dashboard(self):
        client = stock_app.app.test_client()

        for path in ("/health", "/healthz"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_data(as_text=True), "ok")

    def test_stock_chart_is_clipped_and_resizes_with_its_panel(self):
        css = css_compact()
        js = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn(".chart-shell{overflow:hidden", css)
        self.assertIn(".stock-chart{", css)
        self.assertIn("min-height:320px", css)
        self.assertIn("function measureChartHeight", js)
        self.assertIn("Math.min(460", js)
        self.assertIn("ResizeObserver", js)

    def test_order1_price_direction_tokens_are_market_contextual(self):
        css = css_compact()
        js = Path(stock_app.app.static_folder, "app.js").read_text(
            encoding="utf-8"
        )

        # E-1: 全域 !important 覆蓋已移除
        self.assertNotIn("absorb-sage)!important", css)
        self.assertNotIn("absorb-coral)!important", css)

        # E-2: 市場語境方向色 token（台股紅漲綠跌、美股綠漲紅跌）
        self.assertIn(
            'body[data-market="TW"]{--price-up:var(--absorb-danger);'
            '--price-down:var(--absorb-success);}',
            css,
        )
        self.assertIn(
            'body[data-market="US"]{--price-up:var(--absorb-success);'
            '--price-down:var(--absorb-danger);}',
            css,
        )
        self.assertIn(".positive,.up{color:var(--price-up);}", css)
        self.assertIn(".negative,.down{color:var(--price-down);}", css)

        # 方向 class 各只宣告一次，且無 !important
        for selector in (".positive,", ".negative,", ".up{", ".down{"):
            with self.subTest(selector=selector):
                self.assertLessEqual(css.count(selector), 1)
        self.assertNotIn("var(--price-up)!important", css)
        self.assertNotIn("var(--price-down)!important", css)

        # E-1: 深色面板不再用範圍覆寫硬編碼方向色（on-dark token 定義除外）
        self.assertNotIn(".forecast-panel.positive{", css)
        self.assertNotIn(".us-index-forecast-list.positive{", css)

        # E-1/E-3: K 線與預測線改讀 CSS 變數，無硬編碼色
        self.assertNotIn('upColor: "#', js)
        self.assertNotIn('downColor: "#', js)
        self.assertNotIn('wickUpColor: "#', js)
        self.assertNotIn('wickDownColor: "#', js)
        self.assertIn('getPropertyValue("--price-up")', js)
        self.assertIn('getPropertyValue("--price-down")', js)
        self.assertIn('getPropertyValue("--absorb-info")', js)
        self.assertNotIn("#2563eb", js)

    def test_order1_direction_source_colors_reverse_whitelist(self):
        """反向白名單：四個方向來源色（--absorb-coral / --absorb-sage /
        --absorb-danger / --absorb-success）除了 token 定義與 --price-*
        映射定義外，只允許出現在已逐條核對的非方向用途清單中；
        清單外任何規則即失敗（E-1 Blocker 3 覆核第二輪）。"""
        # 註解會黏在下一條選擇器前面，會讓「規則名稱」對不上白名單
        css = re.sub(r"/\*.*?\*/", " ", css_bundle(), flags=re.S)
        source_tokens = (
            "--absorb-coral",
            "--absorb-sage",
            "--absorb-danger",
            "--absorb-success",
        )
        allowed_rules = {
            ".error-banner",
            ".event-item.severity-high",
            ".risk-panel>p",
            ".research-status span",
            '.freshness-status[data-freshness-status="current"]',
            ".confidence-card strong",
        }
        # ORDER 5（E-1）：ORDER 1 的白名單只認這四個 token，
        # 報告層用的是 --absorb-green-ok / --absorb-red-strong，
        # 所以「強勢跑贏」的綠與同一列 +4.31% 的紅並存了整整四個 ORDER。
        # 把這兩個 token 一併納入來源色，缺口才補起來。
        source_tokens = source_tokens + (
            "--absorb-green-ok",
            "--absorb-red-strong",
        )
        # 非方向用途才留在名單裡：模型 Gate 通過／失敗、規則式風險狀態。
        # 這些不是漲跌，綠＝通過在這裡是對的。
        allowed_rules |= {
            ".market-state-badge.state-improving",
            ".badge-success",
            ".badge-danger",
        }
        # 名單裡不得有不存在的規則，否則只是把洞挖大
        for rule_name in allowed_rules:
            with self.subTest(allowed=rule_name):
                self.assertIn(rule_name.split(">")[0].strip(), css)
        violations = []
        for rule in css.split("}"):
            if "{" not in rule:
                continue
            selector, body = rule.split("{", 1)
            matched = [
                tok
                for tok in source_tokens
                if re.search(re.escape(tok) + r"(?![a-z0-9-])", body)
            ]
            if not matched:
                continue
            if any(re.search(re.escape(tok) + r"\s*:", body) for tok in matched):
                # token 定義（:root）本身
                continue
            if re.search(r"--price-(?:up|down)(?:-on-dark)?\s*:", body):
                # --price-* 映射定義（:root / body[data-market]）
                continue
            normalized = re.sub(r"\s+", " ", selector.strip())
            if normalized in allowed_rules:
                continue
            violations.append(normalized)
        self.assertEqual(violations, [])

    def test_order2_css_bundle_is_in_sync_with_sources(self):
        """app.css 由 scripts/build_css.py 串接產生，必須與六個原始檔同步。

        改為建置時串接而非 @import：@import 會讓 STATIC_ASSET_VERSION 只覆蓋
        app.css 那幾行匯入語句（部署後版本號不變、真正的樣式檔無版本參數），
        並且多一層 render-blocking 的串行請求。
        """
        import subprocess

        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "build_css.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        app_css = Path(stock_app.app.static_folder, "app.css").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("@import", app_css)
        for name in _CSS_FILES:
            self.assertTrue(
                (Path(stock_app.app.static_folder) / name).is_file(),
                name,
            )

    def test_order3_font_sizes_are_confined_to_the_type_scale(self):
        """所有字級都必須屬於 type scale 八級（C-2）。

        寫成不變量而非指標：ORDER 2 的教訓是「hex 字面值數量下降」這種指標
        可以被優化（把字面值換成未定義的 token），不變量不行。
        """
        allowed = {"11", "13", "15", "19", "24", "28", "32"}
        svg_user_units = {"7", "3.2"}  # .breadth-chart 內為 SVG viewBox 座標，非 CSS px
        css = css_bundle()
        found = set(re.findall(r"font-size:\s*([0-9.]+)px", css))
        self.assertEqual(sorted(found - allowed - svg_user_units), [])
        self.assertNotIn("font-size:10px", css_compact())

    def test_order3_border_radius_is_confined_to_four_values(self):
        """圓角只允許 6／8／10／999px（C-3）。"""
        allowed = {"6", "8", "10", "999"}
        css = css_bundle()
        found = set(re.findall(r"border-radius:\s*([0-9]+)px", css))
        self.assertEqual(sorted(found - allowed), [])

    def test_order3_line_height_never_below_chinese_floor(self):
        """中文行高不得低於 1.3，否則字的上緣會被裁切（D-4）。"""
        css = css_bundle()
        bare = [v for v in re.findall(r"line-height:\s*([0-9.]+)(?![0-9a-z%])", css)]
        # font 簡寫裡的行高：字級可能是 clamp()、var() 或帶單位的任意值，
        # 原本的 `[0-9.]+px/` 只認得字面 px，clamp(28px,3.2vw,42px)/1.16
        # 就這樣溜過去了（D-4 的那一條規則正是這個形式）。
        shorthand = re.findall(r"font:[^;{}]*?/([0-9.]+)\s", css)
        too_tight = [v for v in bare + shorthand if float(v) < 1.3]
        self.assertEqual(too_tight, [])

    def test_order2_every_referenced_custom_property_is_defined(self):
        """每個 var(--x) 引用的 --x 都必須有定義。

        未定義的自訂屬性會造成 invalid at computed-value time：可繼承屬性
        （如 color）回退為繼承值，非繼承屬性回退為初始值。這種失效不會有
        任何錯誤訊息，也不會被「hex 字面值數量」這類指標抓到 —— 把字面值
        換成沒定義的 token 反而會讓該指標變好看。
        """
        css = css_bundle()
        defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", css))
        referenced = set(re.findall(r"var\(\s*(--[A-Za-z0-9-]+)", css))
        self.assertEqual(sorted(referenced - defined), [])

    def test_order2_css_sources_are_individually_parseable(self):
        """每個原始檔的註解必須自成對，拆檔點不得落在註解中間。

        若拆檔點切開註解，該檔單獨解析時開頭會是註解內文，CSS 解析器會把它
        當成無效的選擇器前導，連同後面第一個規則區塊一起丟棄。
        """
        static_root = Path(stock_app.app.static_folder)
        for name in _CSS_FILES:
            source = (static_root / name).read_text(encoding="utf-8")
            self.assertEqual(
                source.count("/*"), source.count("*/"), f"{name} 註解不成對"
            )
        css = css_compact()
        self.assertNotIn("--command-", css)
        self.assertNotIn("var(--command-", css)
        self.assertNotIn("--up:", css)
        self.assertNotIn("--down:", css)
        self.assertNotIn("var(--up)", css)
        self.assertNotIn("var(--down)", css)

    def test_order2_hex_literals_do_not_exceed_token_count(self):
        css = css_bundle()
        hex_count = len(re.findall(r"#[0-9a-fA-F]{3,8}\b", css))
        token_count = len(
            set(re.findall(r"--(?:absorb-[a-z0-9-]+|price-[a-z0-9-]+)", css))
        )
        self.assertLessEqual(hex_count, token_count, (hex_count, token_count))


if __name__ == "__main__":
    unittest.main()
