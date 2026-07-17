"""Phase 4C 至 Phase 5 腳本與文件的安全結構測試。"""

from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANUAL_ROLLBACK = REPOSITORY_ROOT / "scripts" / "manual_rollback.ps1"
CUTOVER = REPOSITORY_ROOT / "scripts" / "verify_cutover.ps1"


class ReleaseOperationsTests(unittest.TestCase):
    def test_manual_rollback_is_allowlisted_conditional_and_non_destructive(self) -> None:
        source = MANUAL_ROLLBACK.read_text(encoding="utf-8")

        self.assertIn("SupportsShouldProcess", source)
        self.assertIn("line-stock-bot-498908-quant-snapshots", source)
        self.assertIn("--if-generation-match=", source)
        self.assertIn("Get-FileHash", source)
        self.assertIn("latest-$Market.json", source)
        self.assertNotIn("storage', 'rm'", source)
        self.assertNotIn("--recursive", source)

    def test_cutover_is_read_only_and_fails_closed(self) -> None:
        source = CUTOVER.read_text(encoding="utf-8")

        for required in (
            "quality_gate -ne 'PASS'",
            "source_hashes",
            "uniformBucketLevelAccess",
            "publicAccessPrevention",
            "get-iam-policy",
            "stock-papi-line-channel-access-token",
            "'D:\\AbsorbData'",
            "'ABSORB-LocalQuant'",
            "latest-$Market.json",
            "overall = if ($Ready) { 'READY' } else { 'BLOCKED' }",
        ):
            self.assertIn(required, source)
        self.assertNotIn("storage', 'rm'", source)
        self.assertNotIn("run', 'deploy'", source)

    def test_cutover_supports_current_gcloud_bucket_security_schema(self) -> None:
        source = CUTOVER.read_text(encoding="utf-8")

        for required in (
            "uniform_bucket_level_access",
            "public_access_prevention",
            "lifecycle_config.rule",
            "uniformBucketLevelAccess",
            "publicAccessPrevention",
            "lifecycle.rule",
        ):
            self.assertIn(required, source)
        self.assertIn("$LifecycleRules = @(", source)
        self.assertNotIn("$LifecycleRules = if (", source)

    def test_cutover_handles_ps51_native_progress_but_checks_exit_code(self) -> None:
        source = CUTOVER.read_text(encoding="utf-8")
        invoke_gcloud = source[
            source.index("function Invoke-Gcloud"):
            source.index("function Invoke-Checked")
        ]

        self.assertIn(
            "$PreviousErrorActionPreference = $ErrorActionPreference",
            invoke_gcloud,
        )
        self.assertIn("$ErrorActionPreference = 'SilentlyContinue'", invoke_gcloud)
        self.assertIn(
            "$ErrorActionPreference = $PreviousErrorActionPreference",
            invoke_gcloud,
        )
        self.assertIn("if ($ExitCode -ne 0)", invoke_gcloud)

    def test_required_runbook_and_handover_documents_exist(self) -> None:
        documents = {
            "runbook_incident_response.md": "手動回滾",
            "architecture_overview.md": "回測六層",
            "deployment_guide.md": "Secret Manager",
            "release_blockers_and_risks.md": "Cutover 停止條件",
        }
        for name, expected_text in documents.items():
            content = (REPOSITORY_ROOT / "docs" / name).read_text(encoding="utf-8")
            self.assertIn(expected_text, content)


if __name__ == "__main__":
    unittest.main()
