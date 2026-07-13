import unittest

import app as stock_app
from stock_papi.repositories import market_insights, quant_snapshots


class QuantSnapshotRepositoryTests(unittest.TestCase):
    def test_compatibility_caches_have_one_canonical_owner(self):
        self.assertIs(stock_app._QUANT_MANIFEST_CACHE, quant_snapshots.QUANT_MANIFEST_CACHE)
        self.assertIs(stock_app._MARKET_INSIGHTS_CACHE, market_insights.MARKET_INSIGHTS_CACHE)


if __name__ == "__main__":
    unittest.main()
