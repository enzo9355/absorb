import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_local_quant_task.ps1"
WRAPPER = ROOT / "scripts" / "run_local_quant_task.ps1"


class LocalQuantTaskTests(unittest.TestCase):
    def test_installer_enforces_d_drive_schedule_and_resource_limits(self):
        source = INSTALLER.read_text(encoding="utf-8")

        for required in (
            r"D:\StockPapiData",
            "NTFS",
            "$MinimumFreeGB = 100",
            "$MinimumFreeGB * 1GB",
            "05:30",
            "ExecutionTimeLimit",
            "MultipleInstances IgnoreNew",
            "Priority 7",
            "StartWhenAvailable",
            "LogonType Interactive",
            "--init",
            "--dry-run",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_installer_contains_no_market_secret_or_service_account_file(self):
        source = INSTALLER.read_text(encoding="utf-8").lower()

        for forbidden in (
            "alpaca_api_secret_key",
            "finmind_password",
            "service-account.json",
            "0.26.0",
            "interactivetoken",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_installer_prefers_existing_bundled_python_over_windows_alias(self):
        source = INSTALLER.read_text(encoding="utf-8")

        self.assertIn(
            "$PythonExe = if (Test-Path $BundledPython) { $BundledPython } "
            "elseif ($PythonCommand)",
            source,
        )

    def test_installer_does_not_rewrite_an_already_private_acl(self):
        source = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("$AclIsPrivate", source)
        self.assertIn("if (-not $AclIsPrivate)", source)

    def test_wrapper_moves_runtime_caches_to_d_drive_and_runs_market_batch(self):
        source = WRAPPER.read_text(encoding="utf-8")

        for required in (
            r"D:\StockPapiData",
            "$env:TEMP",
            "$env:TMP",
            "$env:XDG_CACHE_HOME",
            "$env:HF_HOME",
            "$env:PYTHONPYCACHEPREFIX",
            "$env:PYTHONPATH",
            "--run",
            "--market",
            "ALL",
            "--limit",
            "5000",
            "--delay",
            "0.5",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

        self.assertNotIn("GEMINI_API_KEY", source)
        self.assertNotIn("FINMIND_PASSWORD", source)
        self.assertNotIn("--limit 200", source)
        self.assertNotIn("--market TW", source)

    def test_installer_schedules_wrapper_instead_of_embedding_market_arguments(self):
        source = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("$Wrapper", source)
        self.assertIn("-File", source)
        self.assertIn("run_local_quant_task.ps1", source)


if __name__ == "__main__":
    unittest.main()
