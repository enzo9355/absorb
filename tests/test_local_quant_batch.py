import gzip
import datetime
import json
import math
import tempfile
import unittest
from pathlib import Path

from local_quant import (
    TAIPEI,
    ensure_layout,
    load_checkpoint,
    run_market_batch,
    write_stock_artifact,
)


class LocalQuantBatchTests(unittest.TestCase):
    def test_stock_artifact_is_atomic_gzip_json_with_fixed_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)

            target = write_stock_artifact(
                root,
                "TW",
                "2330",
                {"as_of": "2026-07-03", "rows": 500, "latest": {"prob": 61.2}},
            )

            with gzip.open(target, "rt", encoding="utf-8") as stream:
                document = json.load(stream)
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(document["market"], "TW")
            self.assertEqual(document["symbol"], "2330")
            self.assertFalse(target.with_suffix(target.suffix + ".tmp").exists())

    def test_stock_artifact_rejects_invalid_symbols_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            for symbol in ("../2330", "AAPL", "2330/evil"):
                with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                    write_stock_artifact(root, "TW", symbol, {"value": 1.0})
            with self.assertRaises(ValueError):
                write_stock_artifact(root, "TW", "2330", {"value": math.nan})

    def test_market_batch_isolates_failure_and_saves_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)

            def analyze(symbol):
                if symbol == "2317":
                    raise TimeoutError("secret upstream response")
                return {"as_of": "2026-07-03"}

            summary = run_market_batch(
                root,
                "TW",
                ["2330", "2317", "2454"],
                analyze,
                limit=2,
                now_fn=lambda: datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
                delay=0,
            )

            self.assertEqual(summary["attempted"], 2)
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(summary["failed"], [{"symbol": "2317", "error": "TimeoutError"}])
            checkpoint = load_checkpoint(root)
            self.assertEqual(checkpoint["next_index"], 2)
            self.assertNotIn("secret upstream response", json.dumps(checkpoint))

    def test_market_batch_resumes_and_stops_before_drain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            calls = []
            times = iter(
                [
                    datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
                    datetime.datetime(2026, 7, 5, 9, 20, tzinfo=TAIPEI),
                ]
            )

            first = run_market_batch(
                root,
                "TW",
                ["2330", "2317"],
                lambda symbol: calls.append(symbol) or {"as_of": "2026-07-03"},
                now_fn=lambda: next(times),
                delay=0,
            )
            self.assertEqual(calls, ["2330"])
            self.assertEqual(first["next_index"], 1)

            second = run_market_batch(
                root,
                "TW",
                ["2330", "2317"],
                lambda symbol: calls.append(symbol) or {"as_of": "2026-07-03"},
                now_fn=lambda: datetime.datetime(2026, 7, 6, 6, tzinfo=TAIPEI),
                delay=0,
            )
            self.assertEqual(calls, ["2330", "2317"])
            self.assertEqual(second["next_index"], 2)


if __name__ == "__main__":
    unittest.main()
