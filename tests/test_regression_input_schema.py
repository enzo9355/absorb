"""Contract tests for RegressionInputDataset parsing and semantic hashes."""

import copy
import math
import unittest

from reporting.regression_input_schema import RegressionInputDataset
from tests.regression_fixtures import (
    FACTORS,
    input_rows,
    make_input_document,
    rehash_input_document,
    trading_calendar,
)


class TestRegressionInputSchema(unittest.TestCase):
    def setUp(self):
        self.calendar = trading_calendar()
        self.document = make_input_document(calendar=self.calendar)

    def parse(self, document=None):
        return RegressionInputDataset.from_document(
            document or self.document,
            trading_calendar=self.calendar,
        )

    def test_valid_document_uses_injected_trading_calendar(self):
        dataset = self.parse()
        self.assertEqual(dataset.identity.row_count, len(dataset.rows))
        self.assertEqual(dataset.rows[0].feature_session, "2026-05-01")

    def test_unknown_top_level_key_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "top-level keys"):
            self.parse(document)

    def test_nested_objects_require_exact_keys(self):
        for path in ("identity", "rows", "factor_definitions", "preprocessing_policy"):
            with self.subTest(path=path):
                document = copy.deepcopy(self.document)
                target = document[path]
                (target[0] if isinstance(target, list) else target)["unexpected"] = True
                rehash_input_document(document)
                with self.assertRaisesRegex(ValueError, "keys"):
                    self.parse(document)

    def test_identity_formats_counts_and_boundaries_are_enforced(self):
        invalid_values = {
            "market": "US",
            "analysis_scope": "security_level",
            "source_market_date": "2026-07-32",
            "source_object_count": 2,
            "row_count": True,
            "aggregate_manifest_object": "../manifest.json",
            "aggregate_manifest_sha256": "A" * 64,
            "calendar_sha256": "not-a-sha",
            "code_commit_sha": "d" * 39,
            "first_feature_session": "2026-05-04",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["identity"][field] = value
                rehash_input_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

    def test_calendar_enforces_real_sessions_and_exact_plus_five_shift(self):
        calendar = trading_calendar(closed_2026=("2026-05-11",))
        rows = input_rows(calendar, start="2026-05-08", count=1)
        self.assertEqual(rows[0]["label_end_session"], "2026-05-18")

        document = make_input_document(
            calendar=calendar,
            rows=rows,
            source_market_date="2026-05-18",
        )
        RegressionInputDataset.from_document(document, trading_calendar=calendar)

        document["rows"][0]["label_end_session"] = "2026-05-15"
        document["identity"]["first_label_end_session"] = "2026-05-15"
        document["identity"]["last_label_end_session"] = "2026-05-15"
        rehash_input_document(document)
        with self.assertRaisesRegex(ValueError, "five trading sessions"):
            RegressionInputDataset.from_document(document, trading_calendar=calendar)

    def test_row_dates_must_be_sessions_sorted_unique_and_mature(self):
        cases = []

        weekend = copy.deepcopy(self.document)
        weekend["rows"][0]["feature_session"] = "2026-05-02"
        cases.append(("trading session", weekend))

        duplicate = copy.deepcopy(self.document)
        duplicate["rows"][1]["feature_session"] = duplicate["rows"][0]["feature_session"]
        cases.append(("strictly", duplicate))

        immature = copy.deepcopy(self.document)
        immature["identity"]["source_market_date"] = "2026-05-01"
        cases.append(("source_market_date", immature))

        for message, document in cases:
            with self.subTest(message=message):
                rehash_input_document(document)
                with self.assertRaisesRegex(ValueError, message):
                    self.parse(document)

    def test_prices_returns_and_factor_values_are_finite_non_bool_and_consistent(self):
        mutations = (
            ("taiex_close_t", 0.0),
            ("taiex_close_t_plus_5", -1.0),
            ("five_session_forward_return", True),
            ("five_session_forward_return", math.inf),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(self.document)
                document["rows"][0][field] = value
                if math.isfinite(value) if isinstance(value, float) else True:
                    rehash_input_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

        document = copy.deepcopy(self.document)
        document["rows"][0]["five_session_forward_return"] += 1.1e-6
        rehash_input_document(document)
        with self.assertRaisesRegex(ValueError, "forward return"):
            self.parse(document)

    def test_factor_contract_and_raw_preprocessing_are_exact(self):
        document = copy.deepcopy(self.document)
        document["rows"][0]["factor_values"].pop(FACTORS[-1])
        rehash_input_document(document)
        with self.assertRaisesRegex(ValueError, "factor"):
            self.parse(document)

        document = copy.deepcopy(self.document)
        document["factor_definitions"].pop()
        rehash_input_document(document)
        with self.assertRaisesRegex(ValueError, "factor definitions"):
            self.parse(document)

        document = copy.deepcopy(self.document)
        document["preprocessing_policy"]["factor_value_stage"] = "winsorized"
        rehash_input_document(document)
        with self.assertRaisesRegex(ValueError, "raw"):
            self.parse(document)

    def test_rows_and_content_hashes_are_recomputed(self):
        document = copy.deepcopy(self.document)
        document["rows"][0]["factor_values"][FACTORS[0]] += 0.01
        with self.assertRaisesRegex(ValueError, "canonical_rows_sha256"):
            self.parse(document)

        document = copy.deepcopy(self.document)
        document["identity"]["dataset_id"] += "-tampered"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            self.parse(document)


if __name__ == "__main__":
    unittest.main()
