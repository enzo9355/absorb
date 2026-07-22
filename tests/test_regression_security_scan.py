# -*- coding: utf-8 -*-
"""Security scan guard test for secret and API key isolation."""

import re
import unittest


class TestRegressionSecurityScan(unittest.TestCase):

    def test_no_hardcoded_secrets_or_tokens_in_regression_modules(self):
        secret_patterns = [
            re.compile(r"AIzaSy[0-9A-Za-z-_]{33}"),  # Google API key pattern
            re.compile(r"ya29\.[0-9A-Za-z-_]+"),      # GCP OAuth token pattern
            re.compile(r"-----BEGIN PRIVATE KEY-----"),
        ]

        target_files = [
            "reporting/regression_schema.py",
            "reporting/regression_input_schema.py",
            "reporting/regression_input_loader.py",
            "reporting/regression_input_builder.py",
            "reporting/regression_input_publisher.py",
            "reporting/regression_adapter.py",
            "reporting/regression_validation.py",
            "reporting/regression_builder.py",
            "stock_papi/research/regression_deps.py",
        ]

        for filepath in target_files:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                for pat in secret_patterns:
                    self.assertIsNone(pat.search(content), f"Secret pattern matched in {filepath}")


if __name__ == "__main__":
    unittest.main()
