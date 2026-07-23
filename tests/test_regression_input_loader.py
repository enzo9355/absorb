"""Offline input loader tests using exact stored bytes."""

import hashlib
import unittest
from unittest import mock

from reporting.regression_input_loader import load_regression_input_dataset
from reporting.regression_input_schema import serialize_regression_input_dataset
from tests.regression_fixtures import make_input_document, trading_calendar


class TestRegressionInputLoader(unittest.TestCase):
    def setUp(self):
        self.calendar = trading_calendar()
        self.document = make_input_document(calendar=self.calendar)
        self.payload = serialize_regression_input_dataset(self.document)
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.path = f"objects/regression-input/{self.sha}.json"

    def test_loads_only_exact_path_sha_and_schema_valid_bytes(self):
        with mock.patch(
            "reporting.regression_input_loader.get_raw_object_bytes",
            return_value=self.payload,
        ) as loader:
            dataset = load_regression_input_dataset(
                self.path,
                expected_sha256=self.sha,
                trading_calendar=self.calendar,
            )
        loader.assert_called_once()
        self.assertEqual(dataset.identity.content_sha256, self.document["identity"]["content_sha256"])

    def test_invalid_path_sha_or_payload_returns_none(self):
        cases = (
            ("../traversal.json", self.sha, self.payload),
            (self.path, "A" * 64, self.payload),
            (self.path, self.sha, self.payload + b"x"),
        )
        for path, sha, payload in cases:
            with self.subTest(path=path):
                with mock.patch(
                    "reporting.regression_input_loader.get_raw_object_bytes",
                    return_value=payload,
                ):
                    self.assertIsNone(
                        load_regression_input_dataset(
                            path,
                            expected_sha256=sha,
                            trading_calendar=self.calendar,
                        )
                    )


if __name__ == "__main__":
    unittest.main()
