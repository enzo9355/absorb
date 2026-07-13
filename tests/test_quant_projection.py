import unittest

import app as stock_app
from stock_papi.quant.projection import calculate_investment_projection


class QuantProjectionTests(unittest.TestCase):
    def test_root_export_uses_canonical_projection(self):
        self.assertIs(stock_app.calculate_investment_projection, calculate_investment_projection)


if __name__ == "__main__":
    unittest.main()
