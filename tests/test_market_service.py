import unittest

import app as stock_app
from stock_papi.integrations.market_data import tw_exchange
from stock_papi.services import market


class MarketServiceTests(unittest.TestCase):
    def test_compatibility_exports_use_canonical_market_functions(self):
        self.assertIs(stock_app.fetch_market_activity, tw_exchange.fetch_market_activity)
        self.assertIs(stock_app.sector_candidates, market.sector_candidates)
        self.assertIs(stock_app.sector_signal_score, market.sector_signal_score)


if __name__ == "__main__":
    unittest.main()
