import hashlib
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from stock_papi.config.capabilities import PredictionCapabilityState, conditional_advice_allowed
from stock_papi.services import trade_plans


def _sessions(start="2026-06-01", count=100):
    from datetime import date, timedelta
    day = date.fromisoformat(start)
    out = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _snapshot(symbol="INTC", closes=None, volumes=None, sessions=None, **overrides):
    sessions = sessions or _sessions(count=70)
    if closes is None:
        # Gentle oscillation upward: net drift small to keep RSI below 70
        # while preserving Close >= MA20 >= MA60 at the breakout.
        closes = []
        price = 100.0
        pattern = [1.0, -0.8] * 31
        for i in range(60):
            price += pattern[i % len(pattern)]
            closes.append(round(price, 4))
        highs = [c + 0.4 for c in closes]
        trigger = max(highs[-20:])
        closes.append(round(trigger + 0.2, 4))
    if volumes is None:
        volumes = [1_000_000.0] * 60 + [1_500_000.0]
    daily = []
    # Align daily to last 61 sessions.
    window = sessions[-61:]
    for i, session in enumerate(window):
        close = float(closes[i])
        high = close + 0.4
        # Ensure breakout day high does not break trigger logic (trigger excludes T).
        low = close - 0.4
        open_ = close - 0.1
        daily.append({"date": session, "open": open_, "high": high, "low": low,
                      "close": close, "volume": float(volumes[i])})
    snap = {
        "market": "US",
        "symbol": symbol,
        "instrument_type": "common_stock",
        "observation_kind": "regular_price",
        "source_snapshot_sha256": hashlib.sha256(b"verified-reader").hexdigest(),
        "source_ref": {"label": "verified_reader", "version": "v1"},
        "as_of": window[-1],
        "daily": daily,
        "corporate_action_status": "ok",
    }
    snap.update(overrides)
    return snap, {"sessions": sessions}


class TradePlanRuleTests(unittest.TestCase):
    def _build(self, snap, cal, expected=None, evidence=()):
        expected = expected or snap["as_of"]
        return trade_plans.build_trade_plan(
            snap, expected_session=expected,
            generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc),
            calendar=cal, evidence_ids=evidence)

    def test_entry_review_happy_path(self):
        snap, cal = _snapshot()
        plan = self._build(snap, cal)
        self.assertEqual(plan["action"], "entry_review")
        self.assertEqual(plan["policy_version"], "us_daily_breakout_v1")
        self.assertEqual(plan["rsi_method"], "rsi14_wilder_last61_v1")
        self.assertLess(plan["conditions"]["rsi"], 70.0)
        self.assertGreater(plan["conditions"]["close"], plan["conditions"]["trigger_price"])
        self.assertLessEqual(plan["conditions"]["close"], plan["conditions"]["entry_ceiling"])

    def test_trigger_excludes_today_high(self):
        snap, cal = _snapshot()
        # Make T high the absolute max; trigger must ignore it.
        snap["daily"][-1]["high"] = snap["daily"][-1]["close"] + 50.0
        plan = self._build(snap, cal)
        self.assertEqual(plan["action"], "entry_review")

    def test_volume_boundary(self):
        snap, cal = _snapshot()
        avg20 = sum(r["volume"] for r in snap["daily"][-21:-1]) / 20.0
        snap["daily"][-1]["volume"] = avg20 * 1.2
        self.assertEqual(self._build(snap, cal)["action"], "entry_review")
        snap["daily"][-1]["volume"] = avg20 * 1.19
        self.assertEqual(self._build(snap, cal)["action"], "wait")

    def test_rsi_and_ceiling_boundaries(self):
        snap, cal = _snapshot()
        plan = self._build(snap, cal)
        trigger = plan["conditions"]["trigger_price"]
        ceiling = plan["conditions"]["entry_ceiling"]
        # Ceiling equality inclusive.
        snap2, _ = _snapshot()
        snap2["daily"][-1]["close"] = ceiling
        snap2["daily"][-1]["high"] = ceiling + 0.1
        snap2["daily"][-1]["low"] = ceiling - 1.0
        snap2["daily"][-1]["open"] = ceiling - 0.2
        plan2 = self._build(snap2, cal)
        self.assertIn(plan2["action"], {"entry_review", "avoid_chasing"})
        # Force overheated by pushing close up (still under ceiling if possible).
        snap3, _ = _snapshot()
        snap3["daily"][-1]["close"] = ceiling
        snap3["daily"][-1]["high"] = ceiling + 0.5
        plan3 = self._build(snap3, cal)
        # Either entry or avoid depending on RSI; must never be entry when RSI>=70.
        if plan3["conditions"]["rsi"] >= 70.0:
            self.assertEqual(plan3["action"], "avoid_chasing")

    def test_invalid_inputs_are_insufficient(self):
        base, cal = _snapshot()
        cases = [
            dict(daily=[]),
            dict(instrument_type="option"),
            dict(observation_kind="halted"),
            dict(source_snapshot_sha256="not-a-hash"),
            dict(corporate_action_status="split_uncomparable"),
            dict(market="TW"),
        ]
        for override in cases:
            snap = dict(base, **override)
            if "daily" in override and override["daily"] == []:
                snap["daily"] = []
            plan = self._build(snap, cal)
            self.assertEqual(plan["action"], "insufficient", override)
        # NaN / bool / negative volume
        import math
        snap = dict(base)
        snap["daily"] = [dict(r) for r in base["daily"]]
        snap["daily"][-1]["volume"] = float("nan")
        self.assertTrue(math.isnan(snap["daily"][-1]["volume"]))
        self.assertEqual(self._build(snap, cal)["action"], "insufficient")
        snap["daily"][-1]["volume"] = True
        self.assertEqual(self._build(snap, cal)["action"], "insufficient")
        snap["daily"][-1]["volume"] = -5.0
        self.assertEqual(self._build(snap, cal)["action"], "insufficient")

    def test_invalidation_not_below_trigger_blocks_entry(self):
        sessions = _sessions(count=70)
        closes = [100.0] * 61
        volumes = [1_000_000.0] * 61
        snap, cal = _snapshot(closes=closes, volumes=volumes, sessions=sessions)
        plan = self._build(snap, cal)
        self.assertNotEqual(plan["action"], "entry_review")
        self.assertIn(plan["action"], {"wait", "insufficient"})

    def test_held_unheld_text_mapping(self):
        snap, cal = _snapshot()
        plan = self._build(snap, cal)
        for action in ["wait", "entry_review", "avoid_chasing", "exit_review", "insufficient"]:
            unheld, held = trade_plans._held_unheld_guidance(action)
            with self.subTest(action=action):
                self.assertIn("未持有" if action != "insufficient" else "未持有", unheld)
                self.assertIn("持有", held)
                self.assertNotEqual(unheld, held)

    def test_lifecycle_transitions(self):
        sessions = _sessions(count=120)
        window_sessions = sessions[:70]
        snap, cal = _snapshot(sessions=window_sessions)
        cal = {"sessions": sessions}
        plan = trade_plans.build_trade_plan(
            snap, expected_session=snap["as_of"],
            generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc),
            calendar=cal)
        self.assertEqual(plan["action"], "entry_review")
        # Same snapshot re-eval: same event id.
        first = trade_plans.evaluate_trade_plan(
            plan, snap, expected_session=snap["as_of"],
            evaluated_at=datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc), calendar=cal)
        second = trade_plans.evaluate_trade_plan(
            plan, snap, expected_session=snap["as_of"],
            evaluated_at=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc), calendar=cal)
        self.assertEqual(first["status"], "triggered")
        self.assertEqual(first["event"]["event_id"], second["event"]["event_id"])
        # Invalidation: drop close below frozen invalidation.
        snap2 = dict(snap)
        snap2["daily"] = [dict(r) for r in snap["daily"]]
        idx = sessions.index(snap["as_of"])
        next_session = sessions[idx + 1]
        # Build next-day snapshot reusing history + one lower close day.
        new_row = dict(snap2["daily"][-1])
        new_row["date"] = next_session
        new_row["close"] = plan["conditions"]["invalidation_price"] - 1.0
        new_row["open"] = new_row["close"] - 0.2
        new_row["high"] = new_row["close"] + 0.3
        new_row["low"] = new_row["close"] - 0.5
        new_row["volume"] = 1_000_000.0
        snap2["daily"] = snap2["daily"][1:] + [new_row]
        snap2["as_of"] = next_session
        snap2["source_snapshot_sha256"] = hashlib.sha256(b"verified-reader-2").hexdigest()
        out = trade_plans.evaluate_trade_plan(
            plan, snap2, expected_session=next_session,
            evaluated_at=datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc), calendar=cal)
        self.assertEqual(out["status"], "invalidated")
        self.assertEqual(out["action"], "exit_review")
        # Expiry for waiting plans.
        flat_snap, _ = _snapshot(closes=[100.0] * 61, volumes=[1_000_000.0] * 61, sessions=window_sessions)
        flat_plan = trade_plans.build_trade_plan(
            flat_snap, expected_session=flat_snap["as_of"],
            generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc), calendar=cal)
        self.assertNotEqual(flat_plan["action"], "entry_review")
        late_session = sessions[sessions.index(flat_snap["as_of"]) + 6]
        late_rows = [dict(r) for r in flat_snap["daily"]]
        # Shift window forward 6 sessions with flat prices.
        for k in range(6):
            nr = dict(late_rows[-1])
            nr["date"] = sessions[sessions.index(flat_snap["as_of"]) + 1 + k]
            late_rows = late_rows[1:] + [nr]
        late_snap = dict(flat_snap, daily=late_rows, as_of=late_session,
                         source_snapshot_sha256=hashlib.sha256(b"late").hexdigest())
        expired = trade_plans.evaluate_trade_plan(
            flat_plan, late_snap, expected_session=late_session,
            evaluated_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc), calendar=cal)
        self.assertEqual(expired["status"], "expired")

    def test_plan_id_stable_and_revision_differs(self):
        snap, cal = _snapshot()
        first = self._build(snap, cal)
        second = self._build(snap, cal)
        self.assertEqual(first["plan_id"], second["plan_id"])
        revised = dict(snap, source_snapshot_sha256=hashlib.sha256(b"revised").hexdigest())
        third = self._build(revised, cal)
        self.assertNotEqual(first["plan_id"], third["plan_id"])

    def test_future_snapshot_is_unavailable(self):
        snap, cal = _snapshot()
        # expected behind snapshot last date -> future snapshot.
        early = sessions_early = snap["daily"][0]["date"]
        plan = trade_plans.build_trade_plan(
            snap, expected_session=early,
            generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc), calendar=cal)
        self.assertEqual(plan["action"], "insufficient")

    def test_beta_advice_does_not_enable_predictions(self):
        principal = "line:U" + "a" * 32
        self.assertTrue(conditional_advice_allowed(principal, frozenset({principal[5:]})))
        self.assertFalse(conditional_advice_allowed("public:test", frozenset()))
        with patch.dict(os.environ, {"ABSORB_PREDICTION_MODE": "research"}, clear=True):
            state = PredictionCapabilityState.from_environment()
        self.assertFalse(state.probability_allowed)
        self.assertFalse(state.strong_action_allowed)

    def test_allowlist_empty_and_non_self_closed(self):
        self.assertFalse(conditional_advice_allowed("line:U" + "b" * 32, frozenset()))
        self.assertFalse(conditional_advice_allowed("line:U" + "b" * 32, frozenset({"U" + "c" * 32})))
        self.assertFalse(conditional_advice_allowed("web:abc", frozenset({"abc"})))


if __name__ == "__main__":
    unittest.main()
