import unittest
from stock_papi.shared.symbol import normalize_symbol, get_instrument_type

class SymbolNormalizationTests(unittest.TestCase):
    def test_normalize_symbol(self):
        # TW symbols
        self.assertEqual(normalize_symbol("TW:2330"), "TW:2330")
        self.assertEqual(normalize_symbol("2330.TW"), "TW:2330")
        self.assertEqual(normalize_symbol("2330.TWO"), "TW:2330")
        self.assertEqual(normalize_symbol("2330"), "TW:2330")
        self.assertEqual(normalize_symbol("  2330.tw  "), "TW:2330")

        # US symbols
        self.assertEqual(normalize_symbol("US:AAPL"), "US:AAPL")
        self.assertEqual(normalize_symbol("AAPL"), "US:AAPL")
        self.assertEqual(normalize_symbol("BRK.B"), "US:BRK.B")
        self.assertEqual(normalize_symbol("US:BRK.B"), "US:BRK.B")
        self.assertEqual(normalize_symbol("BRK-B"), "US:BRK.B")
        self.assertEqual(normalize_symbol("  aapl  "), "US:AAPL")

        # Empty/None
        self.assertEqual(normalize_symbol(None), "")
        self.assertEqual(normalize_symbol(""), "")

    def test_get_instrument_type(self):
        # Known ETFs
        self.assertEqual(get_instrument_type("0050"), "ETF")
        self.assertEqual(get_instrument_type("0050.TW"), "ETF")
        self.assertEqual(get_instrument_type("TW:0050"), "ETF")
        self.assertEqual(get_instrument_type("SPY"), "ETF")
        self.assertEqual(get_instrument_type("US:SPY"), "ETF")

        # Stocks / Unknowns
        self.assertEqual(get_instrument_type("2330"), "STOCK")  # Verified via twstock codes mock or fallback
        self.assertEqual(get_instrument_type("AAPL"), "unknown")
