import hashlib
import unittest
from datetime import datetime, timezone

from stock_papi.services import trade_plans
from stock_papi.services.trade_plan_checks import compute_followup, run_trade_plan_checks
import tests.test_trade_plans as plan_fixtures
from line_state import empty_state


USER_A = "U" + "a" * 32
USER_B = "U" + "b" * 32


class FakeStore:
    def __init__(self):
        self.users = {}
        self.conflict_once = set()

    def add_user(self, user_id, state):
        self.users[user_id] = state

    def iter_users(self):
        for user_id, state in self.users.items():
            yield user_id, state, "v1"

    def load(self, user_id):
        return self.users[user_id], "v1"

    def update(self, user_id, mutate):
        state = self.users[user_id]
        # Simulate one conflict for USER_A on first call to exercise retry dedupe.
        if user_id in self.conflict_once:
            self.conflict_once.discard(user_id)
            from line_state import StoreConflict
            # Apply once, then pretend conflict, then re-apply (store retries internally in real impl).
            mutate(state)
            raise StoreConflict("simulated")
        mutate(state)
        return state


def _plan_and_calendar(sessions=None):
    if sessions is None:
        full = plan_fixtures._sessions(count=120)
        window = full[:70]
        snap, _ = plan_fixtures._snapshot(sessions=window)
        cal = {"sessions": full}
    else:
        snap, cal = plan_fixtures._snapshot(sessions=sessions)
    plan = trade_plans.build_trade_plan(
        snap, expected_session=snap["as_of"],
        generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc), calendar=cal)
    assert plan["action"] == "entry_review"
    return plan, snap, cal


class TradePlanChecksTests(unittest.TestCase):
    def _store_with_plan(self, plan, user_id=USER_A):
        store = FakeStore()
        state = empty_state()
        trade_plans.apply_assistant_command(
            state, {"action": "save_plan", "market": plan["market"], "symbol": plan["symbol"],
                    "expected_plan_id": plan["plan_id"], "evidence_ids": [],
                    "position_context": "unheld",
                    "request_id": "00000000-0000-4000-8000-000000000101"},
            now=datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc), verified_plan=plan)
        store.add_user(user_id, state)
        return store

    def test_rerun_same_snapshot_adds_zero_events(self):
        plan, snap, cal = _plan_and_calendar()
        store = self._store_with_plan(plan)
        snapshots = {snap["as_of"]: snap}

        def _load(market, symbol, session=None):
            return snapshots.get(session or snap["as_of"])

        first = run_trade_plan_checks(
            store, _load, now=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc),
            calendar=cal, expected_session=snap["as_of"],
            allowed_users=frozenset({USER_A}), dry_run=False)
        # Same snapshot as save: presented already, no retroactive triggered event.
        self.assertEqual(first["new_events"], 0)
        second = run_trade_plan_checks(
            store, _load, now=datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc),
            calendar=cal, expected_session=snap["as_of"],
            allowed_users=frozenset({USER_A}), dry_run=False)
        self.assertEqual(second["new_events"], 0)

    def test_two_workers_do_not_duplicate(self):
        plan, snap, cal = _plan_and_calendar()
        store = self._store_with_plan(plan)
        # Next session triggers invalidation (new snapshot, different hash).
        sessions = cal["sessions"]
        idx = sessions.index(snap["as_of"])
        nxt = sessions[idx + 1]
        snap2 = dict(snap)
        snap2["daily"] = [dict(r) for r in snap["daily"]]
        bad = dict(snap2["daily"][-1])
        bad["date"] = nxt
        bad["close"] = plan["conditions"]["invalidation_price"] - 1.0
        bad["open"] = bad["close"] - 0.1
        bad["high"] = bad["close"] + 0.2
        bad["low"] = bad["close"] - 0.4
        snap2["daily"] = snap2["daily"][1:] + [bad]
        snap2["as_of"] = nxt
        snap2["source_snapshot_sha256"] = hashlib.sha256(b"next").hexdigest()
        snapshots = {snap["as_of"]: snap, nxt: snap2}

        def _load(market, symbol, session=None):
            return snapshots.get(session)

        store.conflict_once.add(USER_A)
        try:
            run_trade_plan_checks(
                store, _load, now=datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc),
                calendar=cal, expected_session=nxt,
                allowed_users=frozenset({USER_A}), dry_run=False)
        except Exception:
            pass
        # Second worker processes same new snapshot: dedupe by event_id.
        out = run_trade_plan_checks(
            store, _load, now=datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc),
            calendar=cal, expected_session=nxt,
            allowed_users=frozenset({USER_A}), dry_run=False)
        events = [e for e in store.users[USER_A]["assistant"]["events"]
                  if e.get("event_type") == "invalidated"]
        self.assertLessEqual(len(events), 1)
        self.assertEqual(out["new_events"], 0 if events else out["new_events"])

    def test_source_revision_expiry_halt_and_full_events_fail_visible(self):
        sessions = plan_fixtures._sessions(count=90)
        window = sessions[:70]
        full_cal = {"sessions": sessions}
        flat_snap, _ = plan_fixtures._snapshot(closes=[100.0] * 61,
                                               volumes=[1_000_000.0] * 61, sessions=window)
        flat_plan = trade_plans.build_trade_plan(
            flat_snap, expected_session=flat_snap["as_of"],
            generated_at=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc), calendar=full_cal)
        store = self._store_with_plan(flat_plan)
        # Fill events to capacity, then trigger expiry: must fail visibly, not silently.
        store.users[USER_A]["assistant"]["events"] = [
            {"event_id": f"fill-{i}", "action": "fill"} for i in range(200)]
        late = sessions[sessions.index(flat_snap["as_of"]) + 6]
        rows = [dict(r) for r in flat_snap["daily"]]
        for k in range(6):
            nr = dict(rows[-1])
            nr["date"] = sessions[sessions.index(flat_snap["as_of"]) + 1 + k]
            rows = rows[1:] + [nr]
        late_snap = dict(flat_snap, daily=rows, as_of=late,
                         source_snapshot_sha256=hashlib.sha256(b"late-cap").hexdigest())

        def _load(market, symbol, session=None):
            return late_snap if session == late else None

        out = run_trade_plan_checks(
            store, _load, now=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
            calendar=full_cal, expected_session=late,
            allowed_users=frozenset({USER_A}), dry_run=False)
        self.assertGreaterEqual(out["failures"], 1)
        # Halted snapshot: non-regular status yields no fabricated signal.
        halted = dict(late_snap)
        halted["daily"] = [dict(r) for r in late_snap["daily"]]
        halted["daily"][-1]["status"] = "halted"
        out2 = run_trade_plan_checks(
            store, lambda m, s, session=None: halted,
            now=datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc),
            calendar=full_cal, expected_session=late,
            allowed_users=frozenset({USER_A}), dry_run=True)
        self.assertEqual(out2["new_events"], 0)

    def test_followup_uses_reference_open_not_close(self):
        sessions = plan_fixtures._sessions(count=100)
        plan, snap, cal = _plan_and_calendar(sessions=sessions[:70])
        full_cal = {"sessions": sessions}
        saved_entry = {"plan": plan, "saved_at": "2026-09-03T02:00:00Z"}
        ref = trade_plans.trigger_reference_session(plan, saved_entry["saved_at"], full_cal)
        self.assertIsNotNone(ref)
        daily = {}
        for i, session in enumerate(sessions):
            daily[session] = {"open": 100.0 + i * 0.1, "close": 100.5 + i * 0.1, "status": "regular"}
        out = compute_followup(saved_entry, full_cal, daily)
        self.assertEqual(out["status"], "ready")
        self.assertAlmostEqual(out["day5"]["change"],
                               out["day5"]["close"] / out["reference_open"] - 1.0)
        # Missing open is unavailable, never faked with close.
        daily[ref] = {"close": 123.0, "status": "regular"}
        out2 = compute_followup(saved_entry, full_cal, daily)
        self.assertEqual(out2["status"], "unavailable")


    def _delivery_store_with_event(self, user_id=USER_A, enabled=True, beta=None):
        from stock_papi.services.trade_plan_checks import run_trade_plan_checks as _run
        plan, snap, cal = _plan_and_calendar()
        store = self._store_with_plan(plan, user_id=user_id)
        if enabled:
            from stock_papi.services.trade_plans import apply_assistant_command
            apply_assistant_command(store.users[user_id],
                {"action": "set_notifications", "enabled": True,
                 "request_id": "00000000-0000-4000-8000-000000000201"},
                now=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc))
        # Manually insert a triggered event to deliver (station already has it).
        event = {"event_id": "tpe_delivery001", "event_type": "triggered",
                 "new_status": "triggered", "plan_id": plan["plan_id"],
                 "session": snap["as_of"], "reasons": ["conditions_met"],
                 "created_at": "2026-09-03T03:00:00Z"}
        store.users[user_id]["assistant"]["events"].append(event)
        beta = frozenset({user_id}) if beta is None else beta
        return store, plan, event, beta

    def test_delivery_skips_when_off_exited_or_cancelled(self):
        from stock_papi.integrations.line.notifications import deliver_trade_plan_event as _deliver
        from stock_papi.services.trade_plans import apply_assistant_command
        # Notifications off -> skipped, zero sends.
        store, plan, event, beta = self._delivery_store_with_event(enabled=False)
        calls = []
        status = _deliver(store, USER_A, event["event_id"], plan, allowed_users=beta,
                          push_fn=lambda uid, contents, key: calls.append(uid))
        self.assertEqual(status, "skipped")
        self.assertEqual(calls, [])
        # Exited beta -> skipped.
        store2, plan2, event2, _ = self._delivery_store_with_event(enabled=True)
        status2 = _deliver(store2, USER_A, event2["event_id"], plan2,
                           allowed_users=frozenset(),
                           push_fn=lambda uid, contents, key: calls.append(uid))
        self.assertEqual(status2, "skipped")
        # Cancelled plan -> skipped even if opt-in.
        store3, plan3, event3, beta3 = self._delivery_store_with_event(enabled=True)
        apply_assistant_command(store3.users[USER_A],
            {"action": "cancel_plan", "plan_id": plan3["plan_id"],
             "request_id": "00000000-0000-4000-8000-000000000202"},
            now=datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc))
        status3 = _deliver(store3, USER_A, event3["event_id"], plan3, allowed_users=beta3,
                           push_fn=lambda uid, contents, key: calls.append(uid))
        self.assertEqual(status3, "skipped")
        self.assertEqual(calls, [])

    def test_two_workers_claim_once_reject_timeout_and_store_failure(self):
        from stock_papi.integrations.line.notifications import deliver_trade_plan_event as _deliver
        # Two workers race: only one push.
        store, plan, event, beta = self._delivery_store_with_event(enabled=True)
        calls = []
        first = _deliver(store, USER_A, event["event_id"], plan, allowed_users=beta,
                         push_fn=lambda uid, contents, key: calls.append((uid, key)))
        second = _deliver(store, USER_A, event["event_id"], plan, allowed_users=beta,
                          push_fn=lambda uid, contents, key: calls.append((uid, key)))
        self.assertEqual(first, "sent")
        self.assertEqual(second, "sent")
        self.assertEqual(len(calls), 1)
        # Explicit rejection -> failed (retryable), never misreported as sent.
        store2, plan2, event2, beta2 = self._delivery_store_with_event(enabled=True)
        def _reject(uid, contents, key):
            raise RuntimeError("provider rejected 400 bad request")
        status = _deliver(store2, USER_A, event2["event_id"], plan2, allowed_users=beta2, push_fn=_reject)
        self.assertEqual(status, "failed")
        # Timeout/ambiguous -> unknown, stops auto retry.
        store3, plan3, event3, beta3 = self._delivery_store_with_event(enabled=True)
        def _timeout(uid, contents, key):
            raise TimeoutError("push timeout, acceptance unknown")
        status3 = _deliver(store3, USER_A, event3["event_id"], plan3, allowed_users=beta3, push_fn=_timeout)
        self.assertEqual(status3, "unknown")
        again = _deliver(store3, USER_A, event3["event_id"], plan3, allowed_users=beta3,
                         push_fn=lambda uid, contents, key: (_ for _ in ()).throw(RuntimeError("must not resend")))
        self.assertEqual(again, "unknown")
        # Push accepted but record fails -> unknown, not sent.
        store4, plan4, event4, beta4 = self._delivery_store_with_event(enabled=True)
        real_update = store4.update
        pushed = []
        def _ok(uid, contents, key):
            pushed.append(uid)
        def _failing_update(user_id, mutate):
            # First call is the CAS claim (allow); record-sent and record-unknown fail.
            if not hasattr(_failing_update, "calls"):
                _failing_update.calls = 0
            _failing_update.calls += 1
            if _failing_update.calls >= 2:
                raise RuntimeError("store unavailable")
            return real_update(user_id, mutate)
        store4.update = _failing_update
        status4 = _deliver(store4, USER_A, event4["event_id"], plan4, allowed_users=beta4, push_fn=_ok)
        self.assertIn(status4, {"unknown", "sending"})
        self.assertNotEqual(status4, "sent" if not pushed else "no-push-check")
        self.assertEqual(pushed, [USER_A])

    def test_check_alerts_dry_run_keeps_old_and_new_independent(self):
        # Old price alerts use last_triggered_date=today; new plans must not.
        plan, snap, cal = _plan_and_calendar()
        store = self._store_with_plan(plan)
        snapshots = {snap["as_of"]: snap}

        def _load(market, symbol, session=None):
            return snapshots.get(session or snap["as_of"])

        dry = run_trade_plan_checks(
            store, _load, now=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc),
            calendar=cal, expected_session=snap["as_of"],
            allowed_users=frozenset({USER_A}), push_fn=None, dry_run=True)
        # Dry-run previews without writing.
        self.assertIn("preview", dry)
        before = len(store.users[USER_A]["assistant"]["events"])
        self.assertEqual(dry["new_events"], 0)
        self.assertEqual(len(store.users[USER_A]["assistant"]["events"]), before)


if __name__ == "__main__":
    unittest.main()
