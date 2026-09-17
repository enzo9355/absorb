import unittest
from pathlib import Path

from flask import Flask

from stock_papi.services import public_opinions
from stock_papi.web.routes.research import register_research_routes


class ResearchRouteTests(unittest.TestCase):
    def test_creator_shows_pending_free_ingestion_without_promoting_it(self):
        self.opinion_catalog["ingestion"] = {"alpha": {
            "count": 7, "fetched_at": "2026-09-17T06:00:00Z", "has_more": True,
        }}
        response = self.client.get("/perspectives/alpha")
        self.assertEqual(200, response.status_code)
        text = response.get_data(as_text=True)
        self.assertIn("7 筆待審貼文", text)
        self.assertIn("尚未計入選股共識", text)
        self.assertIn("資料覆蓋不完整", text)

    def setUp(self):
        self.app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
        self.app.add_url_rule("/industries", "industries_page", lambda: "industries")
        self.app.add_url_rule("/stock/<code>", "stock_page", lambda code: code)
        self.opinion_catalog = self._opinion_catalog()
        register_research_routes(
            self.app,
            load_relationships=lambda: {
                "topic": "AI 伺服器",
                "stages": [{"id": "compute", "name": "運算"}],
                "relationships": [{
                    "id": "nvidia-foxconn",
                    "from": {"symbol": "NVDA", "name": "NVIDIA"},
                    "to": {"symbol": "2317", "name": "鴻海"},
                    "type": "合作關係",
                    "product_scope": "AI 伺服器系統",
                    "source": {"title": "官方合作公告", "url": "https://nvidianews.nvidia.com/news/example"},
                }],
                "research_leads": [{
                    "symbol": "NVDA",
                    "title": "KOL supply-chain claim",
                    "source_url": "https://x.com/alpha/status/900",
                    "status": "lead_only",
                }],
            },
            load_events=lambda: [{
                "id": "event-1", "symbol": "2317", "name": "鴻海",
                "event_type": "重大訊息", "title": "公司公告", "published_at": "2026-09-16T09:00:00+08:00",
                "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
            }],
            load_opinions=lambda: self.opinion_catalog,
            stock_observation=lambda code: {
                "code": code, "name": {"2317": "鴻海", "2330": "台積電"}.get(code, code),
                "price": 100.0, "as_of": "2026-09-16", "trend_observation": "above_ma20",
                "volume_ratio": 1.2,
            },
            get_stock_name=lambda code: {"2317": "鴻海", "2330": "台積電"}.get(code, code),
            allowed_symbols=lambda: {"2317", "2330"},
        )
        self.client = self.app.test_client()

    def _opinion_catalog(self):
        document = {
            "schema_version": 2,
            "catalog_version": "route-test",
            "creators": [
                {
                    "id": "alpha",
                    "name": "Alpha Research",
                    "platform": "X",
                    "handle": "alpha",
                    "canonical_profile_url": "https://x.com/alpha",
                    "identity_status": "verified",
                    "source_status": "partial",
                    "coverage_since": "2026-09-01",
                },
                {
                    "id": "serenity",
                    "name": "Serenity Candidate",
                    "platform": "X",
                    "handle": "serenity",
                    "canonical_profile_url": "https://x.com/serenity",
                    "identity_status": "pending_review",
                    "source_status": "pending_review",
                },
            ],
            "coverage": [
                {
                    "creator_id": "alpha",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T08:00:00+00:00",
                    "reviewed_through": "2026-09-17T08:00:00+00:00",
                    "catalog_version": "route-test",
                    "sample_start": "2026-09-01",
                    "sample_end": "2026-09-17",
                    "last_success_at": "2026-09-17T07:55:00+00:00",
                    "gaps": [],
                    "status": "partial",
                    "reviewer": "codex",
                },
                {
                    "creator_id": "serenity",
                    "source": "x_profile",
                    "checked_at": "2026-09-17T08:00:00+00:00",
                    "reviewed_through": "2026-09-17T08:00:00+00:00",
                    "catalog_version": "route-test",
                    "sample_start": "2026-09-01",
                    "sample_end": "2026-09-17",
                    "last_success_at": "2026-09-17T07:55:00+00:00",
                    "gaps": ["identity pending"],
                    "status": "pending_review",
                    "reviewer": "codex",
                },
            ],
            "opinions": [
                self._opinion("alpha", "100", "alpha-nvda", market="US", symbol="NVDA", text="公開觀點摘要"),
                self._opinion("alpha", "101", "alpha-tsm", market="US", symbol="TSM", text="TSM ADR view"),
                self._opinion("alpha", "102", "alpha-2330", market="TW", symbol="2330", text="台積電公開觀點"),
            ],
            "outcomes": [],
        }
        return public_opinions.build_catalog(document)

    def _opinion(self, creator_id, post_id, opinion_id, *, market, symbol, text):
        return {
            "id": opinion_id,
            "opinion_id": opinion_id,
            "creator_id": creator_id,
            "origin_group_id": opinion_id,
            "source_url": f"https://x.com/{creator_id}/status/{post_id}",
            "source_kind": "x_post",
            "source_platform": "x",
            "acquisition_method": "manual_permalink_check",
            "market": market,
            "symbol": symbol,
            "published_at": "2026-09-16T10:00:00+00:00",
            "first_seen_at": "2026-09-16T10:05:00+00:00",
            "reviewed_at": "2026-09-16T10:10:00+00:00",
            "review_status": "confirmed",
            "source_status": "available",
            "content_type": "original_opinion",
            "stance": "bullish",
            "recommendation_kind": "explicit",
            "direction": "buy",
            "horizon": "short",
            "conditions": [],
            "text": text,
        }

    def test_relationship_page_renders_source_and_relation(self):
        response = self.client.get("/industries/ai-server/relationships")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("合作關係", html)
        self.assertIn("nvidianews.nvidia.com/news/example", html)
        self.assertIn("relationship-graph", html)

    def test_relationship_focus_keeps_direct_edges_and_evidence_actions(self):
        response = self.client.get("/industries/ai-server/relationships?focus=NVDA")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("目前研究中心：NVDA", html)
        self.assertIn("查看證據與操作", html)
        self.assertIn("加入比較", html)
        self.assertIn("原始來源", html)

        response = self.client.get("/industries/ai-server/relationships?focus=BAD")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"field": "focus", "reason": "unknown_company"})

    def test_compare_rejects_more_than_four_symbols(self):
        response = self.client.get("/compare?symbols=2317,2330,1101,2454,2308")
        self.assertEqual(response.status_code, 400)

    def test_events_and_opinions_are_public(self):
        self.assertEqual(self.client.get("/events").status_code, 200)
        self.assertEqual(self.client.get("/perspectives").status_code, 200)
        self.assertEqual(self.client.get("/perspectives/alpha").status_code, 200)

    def test_opinions_support_symbol_and_stance_filters(self):
        response = self.client.get("/perspectives?market=TW&symbol=2330&stance=bullish&view=timeline&window=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("台積電公開觀點", html)
        self.assertIn("market=TW", html)
        self.assertIn("view=timeline", html)

    def test_perspectives_reject_invalid_query_with_field_reason_json(self):
        response = self.client.get("/perspectives?market=KR&symbol=005930")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"field": "market", "reason": "invalid"})

    def test_perspectives_reject_unknown_creator_with_field_reason_json(self):
        response = self.client.get("/perspectives?creator_id=unknown")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"field": "creator_id", "reason": "unknown"})

    def test_empty_query_keeps_filters_and_returns_200(self):
        response = self.client.get("/perspectives?market=US&symbol=AAPL&creator_id=alpha&view=latest")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("目前沒有符合篩選的已審核觀點", html)
        self.assertIn('value="AAPL"', html)
        self.assertIn('value="alpha"', html)

    def test_stock_perspectives_use_consensus_and_keep_markets_separate(self):
        response = self.client.get("/perspectives/stocks/US/TSM?window=7&cutoff_at=2026-09-17T08:00:00Z")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("US · TSM", html)
        self.assertIn("TSM ADR view", html)
        self.assertNotIn("台積電公開觀點", html)
        self.assertIn("帳號 × 立場", html)

    def test_unknown_stock_perspectives_symbol_returns_400_json(self):
        response = self.client.get("/perspectives/stocks/US/BAD%20TICKER")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"field": "symbol", "reason": "unknown_security"})

    def test_creator_page_renders_coverage_and_pending_identity(self):
        response = self.client.get("/perspectives/serenity")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("pending_review", html)
        self.assertIn("identity pending", html)
        self.assertIn("Coverage", html)

    def test_creator_page_uses_shared_query_parser_and_round_trips_cutoff(self):
        response = self.client.get(
            "/perspectives/alpha?window=28&view=timeline&cutoff_at=2026-09-17T08:00:00Z"
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("window=28", html)
        self.assertIn("view=timeline", html)
        self.assertIn("cutoff_at=2026-09-17T08%3A00%3A00Z", html)

    def test_source_cta_uses_canonical_url_over_raw_provenance(self):
        self.opinion_catalog["opinions"][0]["source_url"] = "https://x.com/alpha/status/100"
        self.opinion_catalog["opinions"][0]["original_source_url"] = "https://x.com/alpha/status/100?utm_source=untrusted"
        response = self.client.get("/perspectives?market=US&symbol=NVDA")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("https://x.com/alpha/status/100", html)
        self.assertNotIn("utm_source=untrusted", html)

    def test_unavailable_catalog_is_explicit_not_silent_empty(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
        register_research_routes(
            app,
            load_relationships=lambda: {},
            load_events=lambda: [],
            load_opinions=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            stock_observation=lambda code: {},
            get_stock_name=lambda code: code,
            allowed_symbols=lambda: set(),
        )
        response = app.test_client().get("/perspectives")
        self.assertEqual(response.status_code, 200)
        self.assertIn("unavailable", response.get_data(as_text=True))

    def test_events_page_distinguishes_reader_failure_from_valid_empty(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
        register_research_routes(
            app,
            load_relationships=lambda: {},
            load_events=lambda: [],
            load_events_status=lambda: ([], "unavailable"),
            load_opinions=lambda: self.opinion_catalog,
            stock_observation=lambda code: {},
            get_stock_name=lambda code: code,
            allowed_symbols=lambda: set(),
        )
        response = app.test_client().get("/events?symbol=2330")
        self.assertEqual(response.status_code, 200)
        self.assertIn("事件資料尚未更新", response.get_data(as_text=True))

    def test_empty_reader_result_is_unavailable_not_ordinary_empty_catalog(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
        register_research_routes(
            app,
            load_relationships=lambda: {},
            load_events=lambda: [],
            load_opinions=lambda: {},
            stock_observation=lambda code: {},
            get_stock_name=lambda code: code,
            allowed_symbols=lambda: set(),
        )
        response = app.test_client().get("/perspectives")
        self.assertEqual(response.status_code, 200)
        self.assertIn("unavailable", response.get_data(as_text=True))

    def test_relationship_page_keeps_kol_claims_as_research_leads(self):
        response = self.client.get("/industries/ai-server/relationships")
        html = response.get_data(as_text=True)
        self.assertIn("研究線索", html)
        self.assertIn("lead_only", html)
        self.assertIn("KOL supply-chain claim", html)


if __name__ == "__main__":
    unittest.main()
