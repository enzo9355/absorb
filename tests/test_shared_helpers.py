import math
import unittest

import app as stock_app
from stock_papi.shared.formatting import clamp, safe_float
from stock_papi.shared.validation import is_crypto_query, is_us_ticker


class SharedHelperTests(unittest.TestCase):
    def test_float_and_clamp_compatibility(self):
        for value, default in ((None, 3), ("bad", 4), (math.nan, 5), (math.inf, 6), ("2.5", 0)):
            with self.subTest(value=value):
                self.assertEqual(safe_float(value, default), stock_app._safe_float(value, default))
        self.assertEqual(clamp(12, 0, 10), stock_app._clamp(12, 0, 10))

    def test_query_validation_compatibility(self):
        for value in ("AAPL", "BRK-B", "TAIEX", "2330", "", None, "TOO-LONG-11"):
            with self.subTest(value=value):
                self.assertEqual(is_us_ticker(value), stock_app.is_us_ticker(value))
        for text in ("BTC 怎麼看", "以太幣", "2330", "最近市場"):
            with self.subTest(text=text):
                self.assertEqual(is_crypto_query(text), stock_app._is_crypto_query(text))


if __name__ == "__main__":
    unittest.main()
