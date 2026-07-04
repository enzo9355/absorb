import gzip
import json
import math
import tempfile
import unittest
from pathlib import Path

from local_quant import ensure_layout, write_stock_artifact


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


if __name__ == "__main__":
    unittest.main()
