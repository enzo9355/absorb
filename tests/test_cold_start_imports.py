# -*- coding: utf-8 -*-
"""Cold-start import isolation guard test."""

import sys
import unittest


class TestColdStartImports(unittest.TestCase):

    def test_stock_papi_application_import_does_not_load_statsmodels(self):
        # Clean sys.modules if statsmodels was imported in other tests
        sm_modules = [m for m in sys.modules if m == "statsmodels" or m.startswith("statsmodels.")]
        for m in sm_modules:
            del sys.modules[m]

        import stock_papi.application
        import stock_papi.web.routes.reports

        loaded_sm = [m for m in sys.modules if m == "statsmodels" or m.startswith("statsmodels.")]
        self.assertEqual(len(loaded_sm), 0, f"statsmodels imported into sys.modules on cold start: {loaded_sm}")


if __name__ == "__main__":
    unittest.main()
