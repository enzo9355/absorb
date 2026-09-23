import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import stock_papi.application as app_module


def _fake_plan(symbol="INTC"):
    return {
        "schema_version": 1,
        "plan_id": "tp_testplan0000000000000000000001",
        "policy_version": "us_daily_breakout_v1",
        "market": "US",
        "symbol": symbol,
        "instrument_type": "common_stock",
        "source_snapshot_sha256": "a" * 64,
        "source_ref": {"label": "verified_reader"},
        "data_as_of": "2026-09-02",
        "generated_at": "2026-09-03T01:00:00Z",
        "available_at": "2026-09-03T01:00:00Z",
        "eligible_session": "2026-09-03",
        "expires_session": "2026-09-10",
        "action": "entry_review",
        "conditions": {"trigger_price": 100.0, "entry_ceiling": 103.0,
                       "invalidation_price": 95.0, "close": 101.0,
                       "ma20": 99.0, "ma60": 97.0, "volume_ratio": 1.5, "rsi": 60.0},
        "supporting_evidence": ["trend ok"],
        "opposing_evidence": ["breakout may fail"],
        "limitations": ["trial"],
        "external_evidence_ids": [],
        "rsi_method": "rsi14_wilder_last61_v1",
        "volume_method": "volume_ratio_t_over_avg20_v1",
        "params": {},
        "unheld_guidance": "unheld",
        "held_guidance": "held",
    }


class TradePlanConversationTests(unittest.TestCase):
    def setUp(self):
        self.beta = frozenset({"U" + "a" * 32})
        self.principal = "line:U" + "a" * 32

    def _entities(self, symbol="INTC", market="US"):
        return [{"market": market, "symbol": symbol, "name": symbol}]

    def test_beta_gets_rule_advice_nonbeta_blocked_probability_blocked(self):
        with patch.object(app_module, "trading_beta_users", self.beta), \
             patch.object(app_module, "_TRADE_PLAN_BUILDER", lambda m, s, e: _fake_plan(s)), \
             patch.object(app_module, "resolve_entities", return_value=self._entities()), \
             patch.object(app_module, "_load_public_opinions",
                          return_value={"schema_version": 2, "subjects": [], "activities": []}):
            answer = app_module._observation_conversation(
                question="INTC 可以買嗎", access="authenticated",
                market_context="US", principal=self.principal)
            text = answer.text if hasattr(answer, "text") else str(answer)
            self.assertIn("entry_review", text)
            self.assertIn("tp_testplan", text)
            # Non-beta: no new advice, no private leak.
            answer2 = app_module._observation_conversation(
                question="INTC 可以買嗎", access="authenticated",
                market_context="US", principal="line:U" + "b" * 32)
            text2 = answer2.text if hasattr(answer2, "text") else str(answer2)
            self.assertNotIn("tp_testplan", text2)
            self.assertIn("尚未受邀", text2)
            # Probability stays blocked even for beta.
            answer3 = app_module._observation_conversation(
                question="INTC 上漲機率幾成", access="authenticated",
                market_context="US", principal=self.principal)
            text3 = answer3.text if hasattr(answer3, "text") else str(answer3)
            self.assertNotIn("entry_review", text3)
            self.assertIn("機率", text3)

    def test_pelosi_intc_unconfirmed_splits_source_and_plan(self):
        catalog = {"schema_version": 2, "catalog_version": "t",
                   "creators": [], "coverage": [], "opinions": [],
                   "subjects": [{"subject_id": "pelosi-household", "subject_kind": "household",
                                 "subject_name": "Pelosi Family", "aliases": ["Pelosi"],
                                 "identity_source_url": "https://ethics.house.gov",
                                 "identity_status": "pending"}],
                   "activities": []}
        with patch.object(app_module, "trading_beta_users", self.beta), \
             patch.object(app_module, "_TRADE_PLAN_BUILDER", lambda m, s, e: _fake_plan(s)), \
             patch.object(app_module, "resolve_entities", return_value=self._entities("INTC", "US")), \
             patch.object(app_module, "_load_public_opinions", return_value=catalog):
            answer = app_module._observation_conversation(
                question="Pelosi 買 Intel，我也能買嗎", access="authenticated",
                market_context="US", principal=self.principal)
            text = answer.text if hasattr(answer, "text") else str(answer)
            self.assertIn("未找到", text)
            self.assertIn("INTC", text)
            self.assertNotIn("她本人買普通股", text)
            # Must not claim Pelosi bought common stock.
            self.assertFalse("Pelosi Family" in text and "purchase" in text and "common_stock" in text
                             and "未找到" not in text)

    def test_llm_divergence_falls_back_to_template(self):
        plan = _fake_plan()
        self.assertFalse(app_module._trade_text_matches_plan("entry_review 99999 勝率90%", plan))
        self.assertTrue(app_module._trade_text_matches_plan(
            "entry_review tp_testplan 100.0 103.0 95.0", plan))

    def test_unknown_person_asks_single_clarification(self):
        catalog = {"schema_version": 2, "catalog_version": "t",
                   "creators": [], "coverage": [], "opinions": [],
                   "subjects": [{"subject_id": "s1", "subject_kind": "person",
                                 "subject_name": "Known Person", "aliases": []}],
                   "activities": []}
        with patch.object(app_module, "_load_public_opinions", return_value=catalog):
            answer = app_module._research_catalog_answer(
                question="@unknownperson 最近買什麼", access="public",
                principal="web:abc", entities=[], market_context="US")
            text = answer.text if hasattr(answer, "text") else str(answer)
            self.assertIn("哪一位", text)
            self.assertNotIn("共識", text)


if __name__ == "__main__":
    unittest.main()
