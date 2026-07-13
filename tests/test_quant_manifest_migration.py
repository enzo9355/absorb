import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.report_fixtures import stock_document, write_quant_publish


def make_legacy_publish(root: Path, documents: list[dict]) -> tuple[Path, Path, bytes]:
    publish = write_quant_publish(root, documents)
    latest_path = publish / "latest-TW.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    manifest_path = publish / latest["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["symbols"].values():
        del entry["uncompressed_size"]
    legacy_bytes = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_path.write_bytes(legacy_bytes)
    latest["manifest_sha256"] = hashlib.sha256(legacy_bytes).hexdigest()
    latest_path.write_text(
        json.dumps(latest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return latest_path, manifest_path, legacy_bytes


class QuantManifestMigrationTests(unittest.TestCase):
    def test_dry_run_validates_utf8_byte_sizes_without_writing(self):
        from reporting.migrate_quant_manifest import migrate_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest_path, manifest_path, legacy_bytes = make_legacy_publish(
                root, [stock_document("2330"), stock_document("2317")]
            )
            latest_before = latest_path.read_bytes()
            manifests_before = set(manifest_path.parent.iterdir())

            result = migrate_manifest(
                root, "TW", Path(r"quant\v1\latest-TW.json"), dry_run=True
            )

            self.assertEqual(result.validated_count, 2)
            self.assertEqual(result.failed_count, 0)
            self.assertGreater(result.max_compressed_size, 0)
            self.assertGreater(result.max_uncompressed_size, result.max_compressed_size)
            self.assertEqual(result.market_as_of, "2026-07-03")
            self.assertIsNone(result.new_manifest)
            self.assertEqual(manifest_path.read_bytes(), legacy_bytes)
            self.assertEqual(latest_path.read_bytes(), latest_before)
            self.assertEqual(set(manifest_path.parent.iterdir()), manifests_before)

    def test_migration_creates_new_manifest_and_keeps_legacy_immutable(self):
        from reporting.migrate_quant_manifest import migrate_manifest
        from reporting.source_loader import load_report_source

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest_path, legacy_path, legacy_bytes = make_legacy_publish(
                root, [stock_document("2330"), stock_document("2317")]
            )

            result = migrate_manifest(
                root, "TW", Path(r"quant\v1\latest-TW.json"), dry_run=False
            )

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            new_path = root / "publish" / "quant" / "v1" / latest["manifest"]
            new_bytes = new_path.read_bytes()
            new_manifest = json.loads(new_bytes)
            self.assertEqual(result.new_manifest, latest["manifest"])
            self.assertNotEqual(new_path, legacy_path)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)
            self.assertEqual(latest["manifest_sha256"], hashlib.sha256(new_bytes).hexdigest())
            self.assertTrue(
                all(
                    isinstance(entry["uncompressed_size"], int)
                    and entry["uncompressed_size"] > 0
                    for entry in new_manifest["symbols"].values()
                )
            )
            self.assertEqual(load_report_source(root).manifest.symbol_count, 2)

    def test_oversized_decode_fails_and_latest_is_unchanged(self):
        from reporting.migrate_quant_manifest import migrate_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest_path, legacy_path, legacy_bytes = make_legacy_publish(
                root, [stock_document("2330")]
            )
            latest_before = latest_path.read_bytes()

            with patch(
                "reporting.migrate_quant_manifest.MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES",
                100,
            ), self.assertRaisesRegex(RuntimeError, "expands beyond limit"):
                migrate_manifest(
                    root, "TW", Path(r"quant\v1\latest-TW.json"), dry_run=False
                )

            self.assertEqual(latest_path.read_bytes(), latest_before)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)

    def test_invalid_stock_schema_fails_and_latest_is_unchanged(self):
        from reporting.migrate_quant_manifest import migrate_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = stock_document("2330")
            invalid["market"] = "US"
            latest_path, legacy_path, legacy_bytes = make_legacy_publish(root, [invalid])
            latest_before = latest_path.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
                migrate_manifest(
                    root, "TW", Path(r"quant\v1\latest-TW.json"), dry_run=False
                )

            self.assertEqual(latest_path.read_bytes(), latest_before)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)

    def test_daily_as_of_mismatch_fails_and_latest_is_unchanged(self):
        from reporting.migrate_quant_manifest import migrate_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = stock_document("2330")
            stale["daily"][-1]["Date"] = "2026-07-02T00:00:00.000"
            latest_path, legacy_path, legacy_bytes = make_legacy_publish(root, [stale])
            latest_before = latest_path.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "daily as_of mismatch for 2330"):
                migrate_manifest(
                    root, "TW", Path(r"quant\v1\latest-TW.json"), dry_run=False
                )

            self.assertEqual(latest_path.read_bytes(), latest_before)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)


if __name__ == "__main__":
    unittest.main()
