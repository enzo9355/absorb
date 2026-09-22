import os
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app

from absorb.conversation.schemas import ConversationAnswer
from absorb.conversation.context import MemoryContextStore


class AbsorbConversationWebTests(unittest.TestCase):
    @staticmethod
    def _payload(question="台積電如何？", market="TW", page="home"):
        return {"question": question, "market": market, "page": page}

    def test_web_conversation_is_json_only_private_and_cookie_is_httponly(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer("結論：等待確認", data_quality="partial"),
        ) as converse:
            response = client.post("/api/conversation", json=self._payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "結論：等待確認")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        kwargs = converse.call_args.kwargs
        self.assertTrue(kwargs["principal"].startswith("web:"))
        self.assertEqual(kwargs["access"], "public")
        self.assertEqual(kwargs["market_context"], "TW")
        self.assertEqual(kwargs["page_context"], "home")

    def test_legacy_question_only_payload_defaults_to_tw_home(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer("ok"),
        ) as converse:
            response = client.post(
                "/api/conversation", json={"question": "今天市場如何？"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(converse.call_args.kwargs["market_context"], "TW")
        self.assertEqual(converse.call_args.kwargs["page_context"], "home")

    def test_authenticated_web_conversation_gets_server_side_action_executor(self):
        client = stock_app.app.test_client()
        with (
            patch.object(
                stock_app,
                "_web_conversation_identity",
                return_value=("line:U0123456789abcdef0123456789abcdef", "authenticated"),
            ),
            patch.object(stock_app, "_line_conversation_action_executor", return_value="executor") as factory,
            patch.object(stock_app, "run_absorb_conversation", return_value=ConversationAnswer("ok")) as converse,
        ):
            response = client.post("/api/conversation", json=self._payload("確認操作"))

        self.assertEqual(response.status_code, 200)
        factory.assert_called_once_with("U0123456789abcdef0123456789abcdef")
        self.assertEqual(converse.call_args.kwargs["action_executor"], "executor")

    def test_web_conversation_rejects_extra_fields_and_non_json(self):
        client = stock_app.app.test_client()
        self.assertEqual(client.post("/api/conversation", data="x").status_code, 415)
        self.assertEqual(
            client.post("/api/conversation", json={"question": "x", "user_id": "victim"}).status_code,
            400,
        )

    def test_web_conversation_rejects_non_string_fields_without_calling_converse(self):
        client = stock_app.app.test_client()
        invalid_values = ([], {}, True, None, 7)

        with patch.object(stock_app, "run_absorb_conversation") as converse:
            for field in ("question", "market", "page"):
                for invalid in invalid_values:
                    payload = self._payload()
                    payload[field] = invalid
                    with self.subTest(field=field, invalid=invalid):
                        response = client.post("/api/conversation", json=payload)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.get_json(), {"error": "invalid request"})

        converse.assert_not_called()

    def test_web_conversation_accepts_allowlisted_learn_context(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer("ok"),
        ) as converse:
            response = client.post(
                "/api/conversation", json=self._payload(page="learn")
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(converse.call_args.kwargs["page_context"], "learn")
        self.assertEqual(
            client.post("/api/conversation", json=self._payload(market="EU")).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                "/api/conversation", json=self._payload(page="admin")
            ).status_code,
            400,
        )

    def test_us_market_context_answers_generic_question_from_us_report(self):
        report = {
            "market": "US",
            "summary": ["S&P 500 收高，市場廣度改善"],
            "source_market_date": "2026-08-21",
            "data_quality": "available",
        }
        with patch.object(
            stock_app, "_conversation_search_stock", return_value=(None, None)
        ), patch.object(
            stock_app, "_conversation_report_lookup", return_value=report
        ) as lookup:
            answer = stock_app._observation_conversation(
                question="今天市場如何？",
                access="public",
                market_context="US",
                page_context="market",
            )

        lookup.assert_called_once_with("post_close", market="US")
        self.assertIn("美股市場實況", answer.text)
        self.assertEqual(answer.data_as_of, "2026-08-21")

    def test_observation_mode_uses_one_bounded_model_call_for_natural_question(self):
        class Model:
            def __init__(self):
                self.calls = []

            def generate_content(self, prompt, **kwargs):
                self.calls.append((prompt, kwargs))
                return SimpleNamespace(text="成交量中位比為 0.88，站上 MA20 比例為 35.6%。")

        model = Model()
        snapshot = {
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-09-08",
            "market_observation": {
                "median_volume_ratio": 0.88,
                "ma20_breadth_pct": 35.6,
            },
            "industry_observations": [],
            "daily_focus": [],
            "stock_events": [],
        }
        with (
            patch.object(stock_app, "asksorb_model", model, create=True),
            patch.object(stock_app, "_conversation_search_stock", return_value=(None, None)),
            patch.object(stock_app, "_published_dashboard_snapshot", return_value=snapshot),
        ):
            answer = stock_app._observation_conversation(
                question="量能跟廣度有沒有背離跡象？",
                access="public",
                market_context="TW",
                page_context="market",
            )

        self.assertIn("成交量中位比為 0.88", answer.text)
        self.assertIn("資料截至：2026-09-08", answer.text)
        self.assertEqual(answer.tools_used, ("verified_observation_dashboard",))
        self.assertEqual(len(model.calls), 1)
        prompt, kwargs = model.calls[0]
        self.assertIn('"中位量比":0.88', prompt)
        self.assertNotIn("median_volume_ratio", prompt)
        self.assertEqual(
            kwargs["generation_config"],
            {"max_output_tokens": 512, "temperature": 0.1},
        )

    def test_observation_mode_model_failure_falls_back_without_retry(self):
        class Model:
            def __init__(self):
                self.calls = 0

            def generate_content(self, *_args, **_kwargs):
                self.calls += 1
                raise RuntimeError("quota exhausted")

        model = Model()
        snapshot = {
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-09-08",
            "market_observation": {
                "return_1d_pct": -0.5,
                "advancing_count": 536,
                "declining_count": 1283,
                "ma20_breadth_pct": 35.6,
                "risk_state": "elevated",
            },
            "industry_observations": [],
        }
        with (
            patch.object(stock_app, "asksorb_model", model, create=True),
            patch.object(stock_app, "_conversation_search_stock", return_value=(None, None)),
            patch.object(stock_app, "_published_dashboard_snapshot", return_value=snapshot),
        ):
            answer = stock_app._observation_conversation(
                question="今天市場如何？",
                access="public",
                market_context="TW",
                page_context="market",
            )

        self.assertEqual(model.calls, 1)
        self.assertIn("市場實況", answer.text)

    def test_asksorb_surface_uses_consistent_name(self):
        html = stock_app.app.test_client().get("/ask").get_data(as_text=True)

        self.assertIn("ASKsorb", html)
        self.assertNotIn("ASK ABSORB", html)

    def test_explicit_tw_symbol_overrides_us_page_context(self):
        observation = {
            "code": "2330",
            "name": "台積電",
            "price": 1200.0,
            "trend_observation": "above_ma20_ma60",
            "rsi": 58.0,
            "volume_ratio": 1.2,
            "risk_events": [],
            "as_of": "2026-08-21",
        }
        with patch.object(
            stock_app, "_conversation_search_stock", return_value=("2330", "台積電")
        ), patch.object(
            stock_app, "fetch_published_quant_snapshot", return_value={"market": "TW"}
        ) as fetch, patch.object(
            stock_app, "build_stock_observation", return_value=observation
        ), patch.object(stock_app, "_conversation_report_lookup") as report_lookup:
            answer = stock_app._observation_conversation(
                question="2330 現在如何？",
                access="public",
                market_context="US",
                page_context="stock",
            )

        fetch.assert_called_once_with("2330")
        report_lookup.assert_not_called()
        self.assertIn("台積電（2330）", answer.text)

    def test_observation_mode_stock_page_pronoun_resolves_symbol_context(self):
        observation = {
            "name": "Apple",
            "code": "AAPL",
            "price": 220.0,
            "rsi": 55.0,
            "trend_observation": "above_ma20",
            "volume_ratio": 1.1,
            "risk_events": [],
            "as_of": "2026-08-21",
        }
        with patch.object(
            stock_app, "_conversation_search_stock", return_value=("AAPL", "Apple")
        ), patch.object(
            stock_app, "fetch_published_quant_snapshot", return_value={"market": "US"}
        ) as fetch, patch.object(
            stock_app, "build_stock_observation", return_value=observation
        ):
            answer = stock_app._observation_conversation(
                question="這檔現在如何？",
                access="public",
                market_context="US",
                page_context="stock",
                symbol_context="AAPL",
            )

        fetch.assert_called_once_with("AAPL")
        self.assertIn("Apple（AAPL）", answer.text)

    def test_same_cookie_us_page_clears_prior_tw_stock_context_in_production_mode(self):
        from tests.test_absorb_conversation import stock_data

        class Provider:
            def __init__(self):
                self.plans = []

            def plan(inner_self, prompt):
                payload = json.loads(prompt.split("規劃資料：\n", 1)[1])
                inner_self.plans.append(payload)
                if "台積電" in payload["question"]:
                    calls = [{
                        "name": "get_stock_analysis",
                        "arguments": {"market": "TW", "symbol": "2330"},
                    }]
                else:
                    calls = [{
                        "name": "get_latest_post_close_report",
                        "arguments": {"market": "US"},
                    }]
                return json.dumps({"tool_calls": calls}, ensure_ascii=False)

            def answer(inner_self, _prompt):
                return "已驗證資料已整理。"

        provider = Provider()
        client = stock_app.app.test_client()
        capability = SimpleNamespace(mode="production")
        report = {
            "market": "US",
            "report_type": "post_close",
            "data_quality": "available",
            "source_market_date": "2026-08-21",
            "summary": ["S&P 500 收高"],
        }
        with (
            patch.object(stock_app, "prediction_capability", capability),
            patch.object(stock_app, "conversation_context_store", MemoryContextStore()),
            patch.object(stock_app, "_conversation_provider", return_value=provider),
            patch.object(
                stock_app,
                "_conversation_search_stock",
                side_effect=lambda query: (
                    ("2330", "台積電") if "台積電" in query else (None, None)
                ),
            ),
            patch.object(stock_app, "analyze", return_value=stock_data()),
            patch.object(stock_app, "_conversation_report_lookup", return_value=report),
        ):
            first = client.post(
                "/api/conversation",
                json=self._payload("台積電現在如何？", market="TW", page="stock"),
            )
            second = client.post(
                "/api/conversation",
                json=self._payload("今天市場如何？", market="US", page="market"),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        second_context = provider.plans[1]["context"]
        self.assertEqual(second_context["market"], "US")
        self.assertIsNone(second_context["symbol"])
        self.assertEqual(second_context["comparison_symbols"], [])

    def test_same_cookie_us_page_retains_explicit_tw_symbol_for_follow_up(self):
        from tests.test_absorb_conversation import stock_data

        class Provider:
            def __init__(self):
                self.plans = []

            def plan(inner_self, prompt):
                payload = json.loads(prompt.split("規劃資料：\n", 1)[1])
                inner_self.plans.append(payload)
                return json.dumps({
                    "tool_calls": [{
                        "name": "get_stock_analysis",
                        "arguments": {"market": "TW", "symbol": "2330"},
                    }]
                }, ensure_ascii=False)

            def answer(inner_self, _prompt):
                return "已驗證資料已整理。"

        provider = Provider()
        client = stock_app.app.test_client()
        capability = SimpleNamespace(mode="production")
        context_store = MemoryContextStore()
        with (
            patch.object(stock_app, "prediction_capability", capability),
            patch.object(stock_app, "conversation_context_store", context_store),
            patch.object(stock_app, "_conversation_provider", return_value=provider),
            patch.object(
                stock_app,
                "_conversation_search_stock",
                side_effect=lambda query: (
                    ("2330", "台積電") if "2330" in query else (None, None)
                ),
            ),
            patch.object(stock_app, "analyze", return_value=stock_data()),
        ):
            first = client.post(
                "/api/conversation",
                json=self._payload("2330 現在如何？", market="US", page="stock"),
            )
            second = client.post(
                "/api/conversation",
                json=self._payload("這檔如何？", market="US", page="stock"),
            )
            third = client.post(
                "/api/conversation",
                json=self._payload("這檔如何？", market="TW", page="stock"),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)
        second_context = provider.plans[1]["context"]
        self.assertEqual(second_context["market"], "TW")
        self.assertEqual(second_context["symbol"], "2330")
        self.assertEqual(second_context["comparison_symbols"], ["2330"])
        self.assertEqual(len(provider.plans), 2)
        self.assertIn("哪一檔", third.get_json()["text"])
        saved = next(iter(context_store._items.values()))
        self.assertEqual(saved.current_market, "TW")
        self.assertIsNone(saved.current_symbol)
        self.assertEqual(saved.comparison_symbols, ())
        self.assertEqual(saved.last_page_market, "TW")

    def test_browser_clients_receive_isolated_principals(self):
        principals = []

        def converse(**kwargs):
            principals.append(kwargs["principal"])
            return ConversationAnswer("ok")

        with patch.object(stock_app, "run_absorb_conversation", side_effect=converse):
            stock_app.app.test_client().post("/api/conversation", json=self._payload("RSI 是什麼？"))
            stock_app.app.test_client().post("/api/conversation", json=self._payload("RSI 是什麼？"))
        self.assertNotEqual(principals[0], principals[1])

    def test_web_conversation_accepts_valid_symbol_on_stock_page(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer("ok"),
        ) as converse:
            response = client.post(
                "/api/conversation",
                json={"question": "這檔怎麼樣？", "market": "US", "page": "stock", "symbol": "AAPL"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(converse.call_args.kwargs["market_context"], "US")
        self.assertEqual(converse.call_args.kwargs["page_context"], "stock")
        self.assertEqual(converse.call_args.kwargs["symbol_context"], "AAPL")

    def test_web_conversation_rejects_malformed_symbols(self):
        client = stock_app.app.test_client()
        malformed_symbols = (
            "../etc/passwd",
            "<script>",
            "AAPL; DROP TABLE",
            "TOOLONGSYMBOLNAMETHATEXCEEDS12CHARS",
            " ",
            123,
            [],
            {},
        )
        with patch.object(stock_app, "run_absorb_conversation") as converse:
            for bad_symbol in malformed_symbols:
                with self.subTest(symbol=bad_symbol):
                    response = client.post(
                        "/api/conversation",
                        json={"question": "這檔如何？", "market": "US", "page": "stock", "symbol": bad_symbol},
                    )
                    self.assertEqual(response.status_code, 400)
        converse.assert_not_called()

    def test_web_conversation_ignores_symbol_on_non_stock_page(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer("ok"),
        ) as converse:
            response = client.post(
                "/api/conversation",
                json={"question": "市場如何？", "market": "TW", "page": "market", "symbol": "2330"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(converse.call_args.kwargs["page_context"], "market")
        self.assertIsNone(converse.call_args.kwargs["symbol_context"])


class Batch6AskCitationsRegressionTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-09-21",
            "market_observation": {
                "advancing_count": 977,
                "declining_count": 854,
                "unchanged_count": 202,
                "ma20_breadth_pct": 50.6,
                "return_1d_pct": 0.0,
                "risk_state": "normal",
            },
            "industry_observations": [],
            "daily_focus": [],
            "stock_events": [],
        }

    def test_breadth_answer_uses_chinese_fields_and_verified_citation(self):
        class Model:
            def __init__(self):
                self.calls = []

            def generate_content(self, prompt, **kwargs):
                self.calls.append(prompt)
                return SimpleNamespace(
                    text="上漲家數 977 檔、下跌 854 檔，站上 MA20 比例 50.6%。"
                )

        model = Model()
        with (
            patch.object(stock_app, "asksorb_model", model, create=True),
            patch.object(stock_app, "_conversation_search_stock", return_value=(None, None)),
            patch.object(stock_app, "_published_dashboard_snapshot", return_value=self._snapshot()),
        ):
            answer = stock_app._observation_conversation(
                question="最近一份盤後觀察裡，市場廣度那一段說了什麼？",
                access="public",
                market_context="TW",
                page_context="market",
            )

        prompt = model.calls[0]
        self.assertIn("上漲家數", prompt)
        self.assertNotIn("advancing_count", prompt)
        self.assertNotIn("market_observation", prompt)
        self.assertEqual(answer.data_as_of, "2026-09-21")
        self.assertEqual(len(answer.citations), 1)
        citation = answer.citations[0]
        self.assertEqual(citation["url"], "/reports/2026-09-21/post-close")
        self.assertEqual(citation["date"], "2026-09-21")
        self.assertIn("市場實況", citation["chapters"])

    def test_citation_url_never_comes_from_model_text(self):
        class Model:
            def generate_content(self, prompt, **kwargs):
                return SimpleNamespace(
                    text="詳見 https://evil.example/report，站上 MA20 比例 50.6%。"
                )

        with (
            patch.object(stock_app, "asksorb_model", Model(), create=True),
            patch.object(stock_app, "_conversation_search_stock", return_value=(None, None)),
            patch.object(stock_app, "_published_dashboard_snapshot", return_value=self._snapshot()),
        ):
            answer = stock_app._observation_conversation(
                question="市場廣度如何？",
                access="public",
                market_context="TW",
                page_context="market",
            )

        urls = [item["url"] for item in answer.citations]
        self.assertNotIn("https://evil.example/report", urls)
        self.assertTrue(all(url.startswith("/reports/") for url in urls))

    def test_model_failure_fallback_stays_chinese_with_citation(self):
        class Model:
            def generate_content(self, *_args, **_kwargs):
                raise RuntimeError("quota exhausted")

        with (
            patch.object(stock_app, "asksorb_model", Model(), create=True),
            patch.object(stock_app, "_conversation_search_stock", return_value=(None, None)),
            patch.object(stock_app, "_published_dashboard_snapshot", return_value=self._snapshot()),
        ):
            answer = stock_app._observation_conversation(
                question="今天市場如何？",
                access="public",
                market_context="TW",
                page_context="market",
            )

        self.assertIn("市場實況", answer.text)
        self.assertNotIn("advancing_count", answer.text)
        self.assertEqual(len(answer.citations), 1)

    def test_conversation_api_exposes_citations(self):
        client = stock_app.app.test_client()
        with patch.object(
            stock_app,
            "run_absorb_conversation",
            return_value=ConversationAnswer(
                "市場實況摘要",
                citations=({"label": "2026-09-21 盤後觀察", "url": "/reports/2026-09-21/post-close"},),
            ),
        ):
            response = client.post(
                "/api/conversation",
                json={"question": "今天市場如何？", "market": "TW", "page": "market"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["citations"],
            [{"label": "2026-09-21 盤後觀察", "url": "/reports/2026-09-21/post-close"}],
        )


if __name__ == "__main__":
    unittest.main()
