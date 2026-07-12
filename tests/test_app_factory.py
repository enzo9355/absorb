import importlib
import sys
import unittest
from unittest.mock import patch

import app as stock_app
from stock_papi.web.app_factory import create_app


class AppFactoryTests(unittest.TestCase):
    def test_factory_returns_configured_flask_app(self):
        flask_app = create_app({"TESTING": True})
        self.assertIs(flask_app, stock_app.app)
        self.assertTrue(flask_app.config["TESTING"])

    def test_import_does_not_refresh_credentials_or_store_token(self):
        with patch("stock_papi.application.line_store") as store:
            importlib.reload(sys.modules["stock_papi.web.app_factory"])
        store._access_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
