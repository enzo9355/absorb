import unittest

import app as stock_app
from stock_papi.services import dashboard


class DashboardServiceTests(unittest.TestCase):
    def test_root_exports_use_canonical_payload_builders(self):
        self.assertIs(stock_app.dashboard_top_picks, dashboard.dashboard_top_picks)
        self.assertIs(stock_app.build_market_heatmap, dashboard.build_market_heatmap)


if __name__ == "__main__":
    unittest.main()
