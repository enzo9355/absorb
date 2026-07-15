from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AbsorbMigrationContractTests(unittest.TestCase):
    def test_data_migration_is_allowlisted_verified_and_non_destructive(self):
        source = (ROOT / "scripts" / "migrate_stock_papi_data_to_absorb.ps1").read_text(encoding="utf-8")
        for required in (
            "SupportsShouldProcess",
            r"D:\StockPapiData",
            r"D:\AbsorbData",
            "Get-FileHash",
            "Compare-Inventory",
            "Assert-NoReparsePoint",
            "source_deleted = $false",
            "ExcludeMigrationAudit",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Remove-Item", source)

    def test_task_migration_uses_disabled_shadow_and_fail_closed_preflight(self):
        source = (ROOT / "scripts" / "migrate_stock_papi_tasks_to_absorb.ps1").read_text(encoding="utf-8")
        for required in (
            "SupportsShouldProcess",
            "ABSORB-LocalQuant",
            "ABSORB-TW-PostClose",
            "Disable-ScheduledTask -TaskName $newName",
            "Incomplete task pair",
            "-not $ConfirmCutover",
            "RunLevel -ne 'Limited'",
            "MultipleInstances -ne 'IgnoreNew'",
            "StartWhenAvailable",
            "WakeToRun",
            "Task principal changed",
            "working directory changed unexpectedly",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Unregister-ScheduledTask", source)


if __name__ == "__main__":
    unittest.main()
