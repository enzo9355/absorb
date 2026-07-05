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
    publish_market_snapshot,
    write_stock_artifact,
)


class LocalQuantPublishTests(unittest.TestCase):
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
                {"as_of": "2026-07-02", "model_version": "lgbm-5d-v1"},
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
