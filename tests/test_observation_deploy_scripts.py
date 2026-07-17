"""Observation Production 部署、驗證與回滾腳本的安全結構測試。"""

from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = REPOSITORY_ROOT / "scripts" / "deploy_observation_production.ps1"
VERIFY = REPOSITORY_ROOT / "scripts" / "verify_cutover.ps1"
ROLLBACK = REPOSITORY_ROOT / "scripts" / "manual_rollback.ps1"
CHECKLIST = REPOSITORY_ROOT / "docs" / "absorb-cutover-checklist.md"


class ObservationDeployScriptTests(unittest.TestCase):
    def test_deploy_is_no_traffic_first_and_explicitly_fail_closed(self) -> None:
        source = DEPLOY.read_text(encoding="utf-8")

        for required in (
            "SupportsShouldProcess",
            "ABSORB_PREDICTION_MODE=research",
            "ABSORB_OBSERVATION_ENABLED=true",
            "ABSORB_PREDICTION_PROBABILITY_ENABLED=false",
            "ABSORB_PREDICTION_RANKING_ENABLED=false",
            "ABSORB_PREDICTION_STRONG_ACTIONS_ENABLED=false",
            "ABSORB_PREDICTION_PERFORMANCE_ENDORSEMENT_ENABLED=false",
            "ABSORB_PREVIEW_CANDIDATE_PREFIX",
            "PREVIEW_CANDIDATE_PREFIX",
            "--no-traffic",
            "Invoke-ObservationSmoke",
            "Invoke-ObservationCutoverVerification",
            "update-traffic",
        ):
            self.assertIn(required, source)

        smoke_call = "$CandidateSmoke = Invoke-ObservationSmoke"
        verify_call = "$Receipt.cutover_verification = Invoke-ObservationCutoverVerification"
        traffic_call = '"--to-revisions=$CandidateRevision=100"'
        self.assertLess(source.index("--no-traffic"), source.index(smoke_call))
        self.assertLess(source.index(smoke_call), source.index(verify_call))
        self.assertLess(source.index(verify_call), source.index(traffic_call))
        self.assertNotIn("--set-env-vars", source)
        self.assertNotIn("--set-secrets", source)

    def test_whatif_does_not_disable_read_only_gcloud_preflight(self) -> None:
        source = DEPLOY.read_text(encoding="utf-8")
        invoke_gcloud = source[
            source.index("function Invoke-Gcloud"):source.index(
                "function Get-Service"
            )
        ]

        self.assertIn("$PreviousWhatIfPreference = $WhatIfPreference", invoke_gcloud)
        self.assertIn("$WhatIfPreference = $false", invoke_gcloud)
        self.assertIn("$WhatIfPreference = $PreviousWhatIfPreference", invoke_gcloud)

    def test_traffic_preflight_sums_ordered_receipt_entries_explicitly(self) -> None:
        source = DEPLOY.read_text(encoding="utf-8")

        self.assertIn("$PreviousTrafficPercent = (", source)
        self.assertIn("ForEach-Object { [int]$_['percent'] }", source)
        self.assertIn("$PreviousTrafficPercent -ne 100", source)
        self.assertIn(
            'ForEach-Object { "$($_[\'revision\'])=$($_[\'percent\'])" }',
            source,
        )
        self.assertNotIn("Measure-Object -Property percent -Sum", source)

    def test_deploy_receipt_captures_previous_state_and_endpoint_evidence(self) -> None:
        source = DEPLOY.read_text(encoding="utf-8")

        for required in (
            "absorb-observation-deployment",
            "previous_service",
            "previous_revision",
            "previous_traffic",
            "previous_environment",
            "observation_lkg_receipt",
            "candidate_revision",
            "candidate_url",
            "traffic_applied",
            "'/health'",
            "'/'",
            "'/api/dashboard'",
            "'/reports'",
            "'/market-map'",
            "'/stock/2330'",
        ):
            self.assertIn(required, source)

    def test_smoke_and_cutover_verification_forbid_prediction_payloads(self) -> None:
        deploy = DEPLOY.read_text(encoding="utf-8")
        verify = VERIFY.read_text(encoding="utf-8")

        forbidden = (
            "forecast_probability",
            "probability",
            "ranking_score",
            "model_version",
            "backtest_version",
            "recommendation",
        )
        for key in forbidden:
            self.assertIn(key, deploy)
            self.assertIn(key, verify)

        for required in (
            "ObservationOnly",
            "product_mode",
            "observation",
            "ABSORB_PREDICTION_MODE",
            "ABSORB_PREVIEW_CANDIDATE_PREFIX",
            "dashboard/v1/latest-TW.json",
            "reports/v2/index-TW.json",
            "/api/dashboard",
        ):
            self.assertIn(required, verify)

        self.assertNotIn("run', 'deploy'", verify)
        self.assertNotIn("storage', 'rm'", verify)

    def test_manual_rollback_can_restore_cloud_run_and_observation_pointers(self) -> None:
        source = ROLLBACK.read_text(encoding="utf-8")

        for required in (
            "ObservationDeploymentReceipt",
            "absorb-observation-deployment",
            "previous_traffic",
            "update-traffic",
            "rollback_observation.ps1",
            "observation_lkg_receipt",
        ):
            self.assertIn(required, source)
        self.assertNotIn("--recursive", source)

    def test_manual_rollback_preflight_handles_whatif_and_ordered_traffic(self) -> None:
        source = ROLLBACK.read_text(encoding="utf-8")
        observation = source[:source.index("if ($LkgManifest")]
        invoke_gcloud = observation[
            observation.index("function Invoke-ObservationGcloud"):
            observation.index("$ReceiptRoot")
        ]

        self.assertIn("$PreviousWhatIfPreference = $WhatIfPreference", invoke_gcloud)
        self.assertIn("$WhatIfPreference = $false", invoke_gcloud)
        self.assertIn("$WhatIfPreference = $PreviousWhatIfPreference", invoke_gcloud)
        self.assertIn("$PreviousTrafficPercent = (", observation)
        self.assertIn("ForEach-Object { [int]$_['percent'] }", observation)
        self.assertIn("$PreviousTrafficPercent -ne 100", observation)
        self.assertIn(
            'ForEach-Object { "$($_[\'revision\'])=$($_[\'percent\'])" }',
            observation,
        )
        self.assertIn(
            "$_.revisionName -eq [string]$Expected['revision']",
            observation,
        )
        self.assertIn(
            "[int]$_.percent -eq [int]$Expected['percent']",
            observation,
        )
        self.assertNotIn("Measure-Object -Property percent -Sum", observation)

    def test_cutover_checklist_documents_order_and_stop_conditions(self) -> None:
        source = CHECKLIST.read_text(encoding="utf-8")

        for required in (
            "Observation Production",
            "capture_observation_lkg.ps1",
            "deploy_observation_production.ps1",
            "no-traffic",
            "verify_cutover.ps1",
            "manual_rollback.ps1",
            "prediction fields",
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
