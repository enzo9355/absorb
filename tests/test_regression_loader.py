# -*- coding: utf-8 -*-
"""Tests for application layer regression artifact loader."""

import unittest
from unittest.mock import patch


class TestRegressionLoader(unittest.TestCase):

    def test_loader_prepends_reports_v2_and_validates_path(self):
        from stock_papi.application import load_regression_artifact

        sha = "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890"
        rel_path = f"objects/regression/{sha}.json"
        mock_bytes = b'{"schema_version": 1}'

        with patch("stock_papi.application._gcs_get_report_v2_object") as mock_gcs:
            mock_gcs.return_value = mock_bytes
            res = load_regression_artifact(rel_path)
            self.assertEqual(res, mock_bytes)
            mock_gcs.assert_called_once_with(f"reports/v2/{rel_path}", 2_000_000)

    def test_invalid_path_rejected_without_gcs_call(self):
        from stock_papi.application import load_regression_artifact

        invalid_paths = [
            "reports/v2/objects/regression/a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890.json",
            "objects/a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890.json",
            "../objects/regression/a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890.json",
            "objects/regression/A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5F67890.json",
            "",
            None,
            123,
        ]
        with patch("stock_papi.application._gcs_get_report_v2_object") as mock_gcs:
            for p in invalid_paths:
                res = load_regression_artifact(p)
                self.assertIsNone(res, f"Path '{p}' should have been rejected")
            mock_gcs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
