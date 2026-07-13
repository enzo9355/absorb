import datetime
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from local_quant import (
    TAIPEI,
    ensure_layout,
    publish_market_insights,
    publish_market_snapshot,
    write_stock_artifact,
)


class LocalQuantPublishTests(unittest.TestCase):
    def test_market_insights_publish_content_addressed_gzip_and_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            document = {
                "schema_version": 1,
                "as_of": "2026-07-06",
                "industries": [], "mops": [], "etfs": [], "supply_chains": [],
                "sources": ["TWSE"],
            }

            latest_path = publish_market_insights(
                root,
                document,
                generated_at=datetime.datetime(2026, 7, 7, 2, 30, tzinfo=TAIPEI),
            )

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            object_path = latest_path.parent / latest["path"]
            self.assertEqual(latest["schema_version"], 1)
            self.assertEqual(latest["kind"], "market-insights")
            self.assertEqual(hashlib.sha256(object_path.read_bytes()).hexdigest(), latest["sha256"])
            with gzip.open(object_path, "rt", encoding="utf-8") as stream:
                self.assertEqual(json.load(stream), document)

    def test_four_percent_failures_publish_with_coverage_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            symbols = [f"{number:04d}" for number in range(100)]
            failed = symbols[-4:]
            for symbol in symbols[:-4]:
                write_stock_artifact(
                    root,
                    "TW",
                    symbol,
                    {"as_of": "2026-07-03", "model_version": "lgbm-5d-v1"},
                )

            latest_path = publish_market_snapshot(
                root,
                "TW",
                symbols,
                failed_symbols=failed,
                generated_at=datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
            )

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            manifest = json.loads(
                (latest_path.parent / latest["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["universe_count"], 100)
            self.assertEqual(manifest["symbol_count"], 96)
            self.assertEqual(manifest["failure_count"], 4)
            self.assertEqual(manifest["failed_symbols"], failed)
            self.assertEqual(manifest["coverage"], 0.96)

    def test_five_percent_failures_preserve_previous_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            symbols = [f"{number:04d}" for number in range(100)]
            for symbol in symbols[:-5]:
                write_stock_artifact(root, "TW", symbol, {"as_of": "2026-07-03"})
            latest_path = root / "publish" / "quant" / "v1" / "latest-TW.json"
            latest_path.parent.mkdir(parents=True)
            latest_path.write_text('{"previous":true}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "failure rate"):
                publish_market_snapshot(
                    root,
                    "TW",
                    symbols,
                    failed_symbols=symbols[-5:],
                    generated_at=datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
                )

            self.assertEqual(latest_path.read_text(encoding="utf-8"), '{"previous":true}')

    def test_complete_market_publishes_content_addressed_manifest_and_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            write_stock_artifact(
                root,
                "TW",
                "2330",
                {"as_of": "2026-07-03", "model_version": "lgbm-5d-v1"},
            )
            write_stock_artifact(
                root,
                "TW",
                "2317",
                {"as_of": "2026-07-03", "model_version": "lgbm-5d-v1"},
            )

            latest_path = publish_market_snapshot(
                root,
                "TW",
                ["2330", "2317"],
                generated_at=datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
            )

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            manifest_path = latest_path.parent / latest["manifest"]
            manifest_bytes = manifest_path.read_bytes()
            self.assertEqual(
                latest["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest()
            )
            manifest = json.loads(manifest_bytes)
            self.assertEqual(manifest["symbol_count"], 2)
            self.assertEqual(manifest["market_as_of"], "2026-07-03")
            self.assertEqual(list(manifest["symbols"]), ["2317", "2330"])
            for entry in manifest["symbols"].values():
                object_path = latest_path.parent / entry["path"]
                self.assertTrue(object_path.is_file())
                self.assertEqual(
                    hashlib.sha256(object_path.read_bytes()).hexdigest(), entry["sha256"]
                )
                with gzip.open(object_path, "rb") as stream:
                    decoded = stream.read()
                self.assertEqual(entry["uncompressed_size"], len(decoded))
                with gzip.open(object_path, "rt", encoding="utf-8") as stream:
                    self.assertEqual(json.load(stream)["schema_version"], 1)

    def test_missing_artifact_does_not_replace_previous_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            publish_root = root / "publish" / "quant" / "v1"
            publish_root.mkdir(parents=True)
            latest_path = publish_root / "latest-TW.json"
            latest_path.write_text('{"previous":true}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "artifact is missing"):
                publish_market_snapshot(
                    root,
                    "TW",
                    ["2330"],
                    generated_at=datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
                )

            self.assertEqual(latest_path.read_text(encoding="utf-8"), '{"previous":true}')

    def test_corrupt_artifact_does_not_create_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            artifact = root / "artifacts" / "stocks" / "US" / "AAPL.json.gz"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"not-gzip")

            with self.assertRaisesRegex(RuntimeError, "artifact is invalid"):
                publish_market_snapshot(
                    root,
                    "US",
                    ["AAPL"],
                    generated_at=datetime.datetime(2026, 7, 5, 6, tzinfo=TAIPEI),
                )

            self.assertFalse(
                (root / "publish" / "quant" / "v1" / "latest-US.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
