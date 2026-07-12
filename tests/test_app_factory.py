import importlib
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import app as stock_app
from stock_papi.web.app_factory import create_app


class AppFactoryTests(unittest.TestCase):
    def test_factory_returns_configured_flask_app(self):
        original = stock_app.app.config["TESTING"]
        try:
            flask_app = create_app({"TESTING": True})
            self.assertIs(flask_app, stock_app.app)
            self.assertTrue(flask_app.config["TESTING"])
        finally:
            stock_app.app.config["TESTING"] = original

    def test_root_facade_exports_factory(self):
        self.assertIs(stock_app.create_app, create_app)

    def test_script_entry_starts_development_server(self):
        with patch("flask.Flask.run") as run:
            runpy.run_path(
                str(Path(__file__).resolve().parents[1] / "app.py"),
                run_name="__main__",
            )
        run.assert_called_once()

    def test_import_does_not_refresh_credentials_or_store_token(self):
        with patch("stock_papi.application.line_store") as store:
            importlib.reload(sys.modules["stock_papi.web.app_factory"])
        store._access_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
