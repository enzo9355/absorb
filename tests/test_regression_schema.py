"""Strict RegressionResearchArtifact schema contract tests."""

import copy
import math
import unittest

from reporting.regression_schema import RegressionResearchArtifact
from tests.regression_fixtures import (
    DISCLOSURE,
    FACTORS,
    make_artifact_document,
    rehash_artifact_document,
)


class TestRegressionSchema(unittest.TestCase):
    def setUp(self):
        self.document = make_artifact_document()

    def parse(self, document=None):
        return RegressionResearchArtifact.from_document(document or self.document)

    def assert_invalid_diagnostics(self, mutate):
        document = copy.deepcopy(self.document)
        mutate(document["diagnostics"])
        try:
            rehash_artifact_document(document)
        except ValueError:
            pass
        with self.assertRaises((ValueError, TypeError)):
            self.parse(document)

    def test_valid_document_recomputes_content_hash(self):
        artifact = self.parse()
        self.assertEqual(artifact.regression_spec.independent_variables, list(FACTORS))
        self.assertEqual(len(artifact.results), 3)

    def test_top_level_and_identity_keys_are_exact(self):
        for path in (None, "identity", "regression_spec", "fit_statistics", "presentation"):
            with self.subTest(path=path):
                document = copy.deepcopy(self.document)
                target = document if path is None else document[path]
                target["unexpected"] = True
                rehash_artifact_document(document)
                with self.assertRaisesRegex(ValueError, "keys"):
                    self.parse(document)

    def test_identity_hash_paths_and_dates_are_strict(self):
        invalid_values = {
            "market": "US",
            "source_market_date": "2026-07-32",
            "applicable_trading_date": "2026-07-16",
            "generated_at": "2026-07-17 10:30:00",
            "source_manifest": "../manifest.json",
            "source_manifest_sha256": "A" * 64,
            "input_dataset_object": f"objects/regression-input/{'a' * 64}.json",
            "input_dataset_sha256": "b" * 63,
            "input_dataset_content_sha256": "not-a-sha",
            "input_dataset_rows_sha256": "C" * 64,
            "code_commit_sha": "d" * 39,
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["identity"][field] = value
                rehash_artifact_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

    def test_regression_spec_is_fixed_to_v1_contract(self):
        invalid_values = {
            "analysis_scope": "security_level",
            "entity_type": "security",
            "universe_definition": "TWSE_ALL",
            "observation_unit": "calendar_day",
            "model_family": "ridge",
            "dependent_variable": "one_day_return",
            "intercept": False,
            "frequency": "weekly",
            "label_horizon_sessions": 4,
            "covariance_estimator": "classic",
            "hac_max_lags": 3,
            "confidence_level": 0.9,
            "sample_count": 29,
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["regression_spec"][field] = value
                rehash_artifact_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

        document = copy.deepcopy(self.document)
        document["regression_spec"]["independent_variables"] = [FACTORS[0]] * 3
        rehash_artifact_document(document)
        with self.assertRaisesRegex(ValueError, "independent_variables"):
            self.parse(document)

    def test_results_are_complete_unique_finite_and_statistically_consistent(self):
        mutations = (
            ("standard_error", -0.1),
            ("coefficient", True),
            ("t_statistic", math.inf),
            ("p_value", 1.1),
            ("confidence_interval_low", 0.5),
            ("direction", "negative"),
            ("display_status", "statistically_insignificant"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["results"][0][field] = value
                if not (isinstance(value, float) and not math.isfinite(value)):
                    rehash_artifact_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

        document = copy.deepcopy(self.document)
        document["results"][1]["factor_name"] = FACTORS[0]
        rehash_artifact_document(document)
        with self.assertRaisesRegex(ValueError, "results factors"):
            self.parse(document)

    def test_fit_statistics_are_finite_and_bounded(self):
        invalid_values = {
            "r_squared": -0.1,
            "adjusted_r_squared": 1.1,
            "residual_standard_error": -0.1,
            "degrees_of_freedom": 0,
            "f_p_value": 1.1,
            "f_statistic": True,
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["fit_statistics"][field] = value
                rehash_artifact_document(document)
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(document)

    def test_diagnostic_nested_keys_are_exact(self):
        for name in (
            "multicollinearity",
            "heteroskedasticity",
            "autocorrelation",
            "residual_normality",
            "data_quality",
        ):
            with self.subTest(name=name, mutation="extra"):
                self.assert_invalid_diagnostics(
                    lambda diagnostics, name=name: diagnostics[name].__setitem__("unexpected", 1)
                )
            with self.subTest(name=name, mutation="missing"):
                first_key = next(iter(self.document["diagnostics"][name]))
                self.assert_invalid_diagnostics(
                    lambda diagnostics, name=name, key=first_key: diagnostics[name].pop(key)
                )

    def test_multicollinearity_contract_is_strict_and_consistent(self):
        mutations = (
            lambda value: value.__setitem__("status", "invalid"),
            lambda value: value.__setitem__("max_vif", None),
            lambda value: value.__setitem__("max_vif", "1.5"),
            lambda value: value.__setitem__("max_vif", math.nan),
            lambda value: value.__setitem__("max_vif", math.inf),
            lambda value: value.__setitem__("max_vif", True),
            lambda value: value.__setitem__("max_vif", 0.99),
            lambda value: value.__setitem__("note", ""),
            lambda value: value.__setitem__("note", "   "),
            lambda value: value.__setitem__("vif_details", {FACTORS[0]: 1.5}),
            lambda value: value["vif_details"].__setitem__(FACTORS[0], 0.99),
            lambda value: value["vif_details"].__setitem__(FACTORS[0], "1.5"),
            lambda value: value["vif_details"].__setitem__(FACTORS[0], True),
            lambda value: value.__setitem__("max_vif", 1.6),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_invalid_diagnostics(
                    lambda diagnostics, mutate=mutate: mutate(diagnostics["multicollinearity"])
                )

    def test_heteroskedasticity_contract_is_strict_and_consistent(self):
        mutations = (
            lambda value: value.__setitem__("status", "invalid"),
            lambda value: value.__setitem__("test_name", "white"),
            lambda value: value.__setitem__("test_statistic", -0.1),
            lambda value: value.__setitem__("test_statistic", "1.0"),
            lambda value: value.__setitem__("p_value", -0.1),
            lambda value: value.__setitem__("p_value", 1.1),
            lambda value: value.__setitem__("p_value", None),
            lambda value: value.__setitem__("threshold", 0.1),
            lambda value: value.__setitem__("threshold", True),
            lambda value: value.__setitem__("status", "warning"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_invalid_diagnostics(
                    lambda diagnostics, mutate=mutate: mutate(diagnostics["heteroskedasticity"])
                )

        self.assert_invalid_diagnostics(
            lambda diagnostics: diagnostics["heteroskedasticity"].update(
                status="passed",
                p_value=0.049,
            )
        )

    def test_autocorrelation_and_normality_statuses_match_statistics(self):
        mutations = (
            lambda diagnostics: diagnostics["autocorrelation"].update(status="invalid"),
            lambda diagnostics: diagnostics["autocorrelation"].update(durbin_watson=-0.1),
            lambda diagnostics: diagnostics["autocorrelation"].update(durbin_watson=4.1),
            lambda diagnostics: diagnostics["autocorrelation"].update(durbin_watson="2.0"),
            lambda diagnostics: diagnostics["autocorrelation"].update(status="warning"),
            lambda diagnostics: diagnostics["autocorrelation"].update(status="passed", durbin_watson=1.49),
            lambda diagnostics: diagnostics["residual_normality"].update(status="invalid"),
            lambda diagnostics: diagnostics["residual_normality"].update(jarque_bera_p_value=-0.1),
            lambda diagnostics: diagnostics["residual_normality"].update(jarque_bera_p_value=1.1),
            lambda diagnostics: diagnostics["residual_normality"].update(jarque_bera_p_value=True),
            lambda diagnostics: diagnostics["residual_normality"].update(status="warning"),
            lambda diagnostics: diagnostics["residual_normality"].update(
                status="passed",
                jarque_bera_p_value=0.049,
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_invalid_diagnostics(mutate)

    def test_data_quality_and_warnings_contracts_are_strict(self):
        mutations = (
            lambda diagnostics: diagnostics["data_quality"].update(missing_rate=-0.1),
            lambda diagnostics: diagnostics["data_quality"].update(missing_rate=1.1),
            lambda diagnostics: diagnostics["data_quality"].update(missing_rate="0.1"),
            lambda diagnostics: diagnostics["data_quality"].update(outlier_count=-1),
            lambda diagnostics: diagnostics["data_quality"].update(outlier_count=1.5),
            lambda diagnostics: diagnostics["data_quality"].update(outlier_count=True),
            lambda diagnostics: diagnostics.update(warnings=None),
            lambda diagnostics: diagnostics.update(warnings=[""]),
            lambda diagnostics: diagnostics.update(warnings=["   "]),
            lambda diagnostics: diagnostics.update(warnings=[1]),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_invalid_diagnostics(mutate)

    def test_disclosure_is_exact_and_all_other_visible_text_is_scanned(self):
        self.assertEqual(self.document["presentation"]["disclosure"], DISCLOSURE)
        document = copy.deepcopy(self.document)
        document["presentation"]["disclosure"] = "簡化揭露"
        rehash_artifact_document(document)
        with self.assertRaisesRegex(ValueError, "disclosure"):
            self.parse(document)

        document = copy.deepcopy(self.document)
        document["diagnostics"]["warnings"] = ["買進訊號"]
        rehash_artifact_document(document)
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            self.parse(document)

        document = copy.deepcopy(self.document)
        document["presentation"]["key_exposures"] = ["Probability output"]
        rehash_artifact_document(document)
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            self.parse(document)

    def test_content_sha256_tampering_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["presentation"]["headline"] += " tampered"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            self.parse(document)


if __name__ == "__main__":
    unittest.main()
