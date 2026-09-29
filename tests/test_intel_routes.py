import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, render_template

from stock_papi.web.routes.intel import register_intel_routes
from stock_papi.web.routes.market import register_market_routes


class IntelRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_disabled_capability_fails_closed_without_calling_reader(self):
        calls = []
        register_intel_routes(
            self.app,
            load_snapshot=lambda *args, **kwargs: calls.append((args, kwargs)),
            enabled=False,
        )

        response = self.app.test_client().get(
            "/api/intel/stock/instrument-common/summary"
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["reason_codes"], ["feature_disabled"])
        self.assertEqual(calls, [])

    def test_summary_route_returns_allowlisted_metadata_and_no_raw_paths(self):
        def reader(instrument_id, release_id=None, page=1):
            return {
                "status": "partial",
                "reason_codes": ["source_unavailable"],
                "instrument_id": instrument_id,
                "release": {
                    "release_id": "release-1", "decision_cutoff_at": "2026-09-24T20:00:00Z",
                    "generated_at": "2026-09-24T20:30:00Z", "valid_until": "2026-09-25T20:00:00Z",
                    "manifest_hash": "a" * 64, "manifest_ref": "must-not-leak",
                },
                "summary": {
                    "schema_version": 1,
                    "instrument_id": instrument_id,
                    "decision_cutoff_at": "2026-09-24T20:00:00Z",
                    "rule_version": "rules-v1",
                    "template_version": "template-v1",
                    "summary_id": "b" * 64,
                    "disclaimer": "描述資料，不代表投資建議。",
                    "manifest_ref": "nested-path-must-not-leak",
                    "slots": {"purchase_activity": {
                        "text": "核對中的摘要", "fact_id": "c" * 64,
                        "raw_value": "must-not-leak",
                    }},
                },
                "fact_ids": ["fact-1"],
            }

        register_intel_routes(self.app, load_snapshot=reader, enabled=True)
        response = self.app.test_client().get(
            "/api/intel/stock/instrument-common/summary"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["status"], "partial")
        self.assertNotIn("manifest_ref", response.get_data(as_text=True))
        self.assertNotIn("raw_value", response.get_data(as_text=True))
        self.assertNotIn("fact-1", response.get_data(as_text=True))
        self.assertEqual(
            response.json["summary"]["slots"]["purchase_activity"],
            {"text": "核對中的摘要", "fact_id": "c" * 64},
        )
        self.assertIn("release_id=release-1", response.json["event_page"]["first_page_url"])

    def test_event_route_requires_release_pin_and_rejects_bad_page(self):
        calls = []
        register_intel_routes(
            self.app,
            load_snapshot=lambda instrument_id, release_id=None, page=1: calls.append(
                (instrument_id, release_id, page)
            ) or {"status": "available", "reason_codes": [], "events": [],
                  "event_page": {"page": page, "page_count": 2},
                  "release": {"release_id": release_id}},
            enabled=True,
        )
        client = self.app.test_client()

        missing_pin = client.get("/api/intel/stock/instrument-common/events?page=1")
        bad_page = client.get(
            "/api/intel/stock/instrument-common/events?release_id=release-1&page=0"
        )
        valid = client.get(
            "/api/intel/stock/instrument-common/events?release_id=release-1&page=2"
        )

        self.assertEqual(missing_pin.status_code, 400)
        self.assertEqual(bad_page.status_code, 400)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(calls, [("instrument-common", "release-1", 2)])
        self.assertEqual(valid.json["event_page"]["page"], 2)

    def test_expired_or_revoked_release_maps_to_gone(self):
        register_intel_routes(
            self.app,
            load_snapshot=lambda *args, **kwargs: {
                "status": "unavailable", "reason_codes": ["artifact_revoked"]
            },
            enabled=True,
        )

        response = self.app.test_client().get(
            "/api/intel/stock/instrument-common/summary?release_id=release-1"
        )
        event_response = self.app.test_client().get(
            "/api/intel/stock/instrument-common/events?release_id=release-1&page=1"
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json["reason_codes"], ["artifact_revoked"])
        self.assertEqual(event_response.status_code, 410)
        self.assertEqual(event_response.json["reason_codes"], ["artifact_revoked"])

    def test_event_route_strips_raw_fields_and_unallowlisted_source_urls(self):
        register_intel_routes(
            self.app,
            load_snapshot=lambda *args, **kwargs: {
                "status": "available", "reason_codes": [],
                "release": {"release_id": "release-1"},
                "events": [{
                    "event_id": "event-1", "event_date": "2026-09-23",
                    "transaction_classification": "purchase_disclosed",
                    "shares": {"raw_value": "must not leak"},
                    "raw_value": {"footnote": "do not expose"},
                    "source_url": "https://sec.gov.evil.example/Archives/edgar/data/x",
                }],
                "event_page": {"page": 1, "page_count": 1},
            },
            enabled=True,
        )

        response = self.app.test_client().get(
            "/api/intel/stock/instrument-common/events?release_id=release-1&page=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["events"][0]["event_id"], "event-1")
        self.assertNotIn("raw_value", response.get_data(as_text=True))
        self.assertNotIn("must not leak", response.get_data(as_text=True))
        self.assertNotIn("source_url", response.json["events"][0])

    def test_stock_intel_partial_escapes_summary_text(self):
        app = Flask(
            __name__,
            template_folder=str(Path(__file__).resolve().parents[1] / "templates"),
        )
        with app.test_request_context("/stock/AAPL"):
            html = render_template(
                "partials/stock_intel.html",
                d={"code": "AAPL"},
                intel_instrument_id="instrument-common",
                intel_snapshot={
                    "status": "partial",
                    "release": {"release_id": "release-1", "decision_cutoff_at": "2026-09-24T20:00:00Z"},
                    "summary": {"slots": {"purchase_activity": {"text": "<script>alert(1)</script>"}}},
                    "events": [],
                    "event_page": {"page": 1, "page_count": 1},
                },
            )

        self.assertIn("data-intel-status=\"partial\"", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_stock_page_uses_pinned_release_and_sanitizes_event_rows(self):
        self.app = Flask(__name__)
        calls = []
        register_market_routes(
            self.app,
            analyze=lambda _code: None,
            stock_observation=lambda _code: {
                "market": "US", "observation_kind": "official_suspended",
                "intel_mapping_status": "resolved", "intel_instrument_id": "instrument-common",
            },
            dashboard_sector_cards=lambda: [],
            cached_opportunities=lambda: [],
            build_market_heatmap=lambda _value: [],
            dashboard_top_picks=lambda _value: [],
            industry_map=lambda: {},
            market_insights_payload=lambda: {},
            twstock_codes=lambda: [],
            is_us_ticker=lambda code: code.upper() == "AAPL",
            find_industry_peers=lambda _code: {"codes": [], "category": ""},
            get_stock_name=lambda code: code,
            dashboard_snapshot=lambda: {},
            us_securities_observation=lambda: {},
            prediction_snapshot=lambda _market: None,
            load_report_index_v2=lambda **_kwargs: [],
            load_intel_snapshot=lambda instrument_id, release_id=None, page=1: calls.append(
                (instrument_id, release_id, page)
            ) or {
                "status": "partial", "release": {"release_id": release_id},
                "summary": {
                    "schema_version": 1, "instrument_id": instrument_id,
                    "decision_cutoff_at": "2026-09-24T20:00:00Z",
                    "rule_version": "rules-v1", "template_version": "template-v1",
                    "summary_id": "b" * 64, "disclaimer": "synthetic",
                    "slots": {"purchase_activity": {
                        "text": "verified summary", "fact_id": "c" * 64,
                        "manifest_ref": "must not leak",
                    }},
                    "manifest_ref": "must not leak",
                },
                "events": [{"event_id": "e1", "raw_value": "hidden"}],
                "event_page": {"page": page, "page_count": 2},
            },
            intel_enabled=True,
            resolve_intel_stock_instrument=lambda data, _code: data["intel_instrument_id"],
        )
        rendered = {}
        with patch(
            "stock_papi.web.routes.market.render_template",
            side_effect=lambda _name, **kwargs: rendered.update(kwargs) or "rendered",
        ):
            response = self.app.test_client().get(
                "/stock/AAPL?intel_release_id=release-1&intel_page=2"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [("instrument-common", "release-1", 2)])
        self.assertEqual(
            rendered["intel_snapshot"]["summary"]["slots"]["purchase_activity"],
            {"fact_id": "c" * 64, "text": "verified summary"},
        )
        self.assertNotIn("manifest_ref", str(rendered["intel_snapshot"]["summary"]))
        self.assertNotIn("raw_value", str(rendered["intel_snapshot"]["events"]))
        self.assertEqual(rendered["intel_snapshot"]["events"], [{"event_id": "e1"}])

    def test_invalid_instrument_id_is_rejected_before_reader(self):
        calls = []
        register_intel_routes(
            self.app,
            load_snapshot=lambda *args, **kwargs: calls.append(args),
            enabled=True,
        )

        response = self.app.test_client().get("/api/intel/stock/../../etc/summary")

        self.assertIn(response.status_code, {400, 404})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
