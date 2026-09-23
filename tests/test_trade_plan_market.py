import gzip
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_papi.integrations.market_data.us_calendar import get_us_calendar_documents
from stock_papi.repositories import quant_snapshots
from stock_papi.services import trade_plan_market
from stock_papi.services.trade_plan_market import PlanUnavailable

INTC_DIGEST = "fcc39dcba62e3ea993a9bf8b3d33dd2cdedce69cb6c51e3b616468d73a0f66f7"
ARTIFACT_PATH = Path(__file__).parents[1] / "tmp_real_intc_artifact.json.gz"


def _load_intc_bytes():
    # Real artifact downloaded read-only from the quant bucket for schema tests.
    # Kept out of the repo; rebuilt by developers with GCS read access.
    local = Path(r"C:\Users\enzo\AppData\Local\Temp\opencode\intc.json.gz")
    if local.exists():
        return local.read_bytes()
    if ARTIFACT_PATH.exists():
        return ARTIFACT_PATH.read_bytes()
    raise unittest.SkipTest("real INTC artifact unavailable (needs GCS read)")


def _manifest_for(digest, size, uncompressed_size):
    return {
        "schema_version": 4,
        "market": "US",
        "target_market_date": "2026-09-21",
        "observation_as_of": "2026-09-21",
        "active_universe_count": 1,
        "observation_count": 1,
        "regular_price_symbol_count": 1,
        "verified_non_price_symbol_count": 0,
        "unavailable_count": 0,
        "unavailable_symbols": [],
        "operational_failure_count": 0,
        "operational_failed_symbols": [],
        "regular_price_denominator": 1,
        "regular_price_coverage": 1.0,
        "observation_coverage": 1.0,
        "expected_non_price_symbols": {},
        "symbols": {
            "INTC": {
                "path": f"objects/{digest}.json.gz",
                "sha256": digest,
                "size": size,
                "uncompressed_size": uncompressed_size,
                "as_of": "2026-09-21",
                "observation_as_of": "2026-09-21",
                "latest_regular_price_date": "2026-09-21",
                "observation_kind": "regular_price",
            }
        },
    }


class TradePlanMarketTests(unittest.TestCase):
    def _real_fetch(self):
        blob = _load_intc_bytes()
        manifest = _manifest_for(INTC_DIGEST, len(blob),
                                 len(gzip.decompress(blob)))

        def load_manifest(market, today=None):
            return manifest if market == "US" else None

        def load_object(path, size):
            if path == f"quant/v1/objects/{INTC_DIGEST}.json.gz":
                return blob
            return None

        def fetch_artifact(symbol):
            return quant_snapshots.fetch_quant_snapshot_with_digest(
                symbol, is_us_ticker_fn=lambda code: True,
                load_manifest=load_manifest, load_object=load_object)
        return fetch_artifact

    def test_real_intc_artifact_builds_plan_with_real_digest(self):
        plan = trade_plan_market.build_us_plan(
            "INTC", [], fetch_artifact=self._real_fetch(),
            calendar_documents=get_us_calendar_documents(),
            now=datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc))
        # The preserved hash is the reader's artifact digest, not a re-hash.
        self.assertEqual(plan["source_snapshot_sha256"], INTC_DIGEST)
        self.assertEqual(plan["market"], "US")
        self.assertEqual(plan["symbol"], "INTC")
        self.assertEqual(plan["policy_version"], "us_daily_breakout_v1")
        self.assertEqual(plan["data_as_of"], "2026-09-21")
        self.assertIn(plan["action"], {"wait", "entry_review", "avoid_chasing", "exit_review"})
        self.assertNotIn("objects/", plan.get("source_ref", {}).get("label", "") +
                         str(plan.get("source_snapshot_sha256") or ""))
        # Stable for identical inputs.
        again = trade_plan_market.build_us_plan(
            "INTC", [], fetch_artifact=self._real_fetch(),
            calendar_documents=get_us_calendar_documents(),
            now=datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(again["plan_id"], plan["plan_id"])

    def test_unavailable_paths_fail_closed(self):
        calendars = get_us_calendar_documents()
        now = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
        with self.assertRaises(PlanUnavailable):
            trade_plan_market.build_us_plan(
                "ZZZZ", [], fetch_artifact=lambda symbol: None,
                calendar_documents=calendars, now=now)
        with self.assertRaises(PlanUnavailable):
            trade_plan_market.build_us_plan(
                "INTC", [], fetch_artifact=lambda symbol: None,
                calendar_documents=calendars, now=now)

    def test_sessions_skip_holidays_without_weekday_fallback(self):
        sessions = trade_plan_market.us_sessions_from_documents(
            get_us_calendar_documents(), start="2025-12-29", end="2026-01-05")
        self.assertNotIn("2026-01-01", sessions)  # New Year's Day
        self.assertIn("2025-12-31", sessions)
        self.assertIn("2026-01-02", sessions)
        # Strictly ascending, no duplicates.
        self.assertEqual(sessions, sorted(set(sessions)))


if __name__ == "__main__":
    unittest.main()
