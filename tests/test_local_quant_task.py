import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_local_quant_task.ps1"
WRAPPER = ROOT / "scripts" / "run_local_quant_task.ps1"
UPLOADER = ROOT / "scripts" / "upload_local_quant.ps1"
LIFECYCLE = ROOT / "config" / "quant-snapshot-lifecycle.json"
DOCKERIGNORE = ROOT / ".dockerignore"
GCLOUDIGNORE = ROOT / ".gcloudignore"


class LocalQuantTaskTests(unittest.TestCase):
    def test_uploader_is_allowlisted_atomic_and_non_destructive(self):
        source = UPLOADER.read_text(encoding="utf-8")

        for required in (
            r"D:\StockPapiData",
            "line-stock-bot-498908-quant-snapshots",
            "Assert-AllowlistedPath",
            "Get-FileHash",
            "objects/[0-9a-f]{64}",
            "manifests/",
            '"latest-$Market.json"',
            'latest-insights.json',
            'market-insights',
            "gcloud",
            "storage",
            "cp",
            "--no-clobber",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        for forbidden in (
            "Remove-Item",
            "storage rsync",
            "--recursive",
            "service-account.json",
            "FINMIND_PASSWORD",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_uploader_batches_content_addressed_objects(self):
        source = UPLOADER.read_text(encoding="utf-8")

        self.assertIn("$ObjectBatchSize = 100", source)
        self.assertIn("Invoke-GcloudCopyBatch", source)
        self.assertIn("$ValidatedObjectPaths", source)
        self.assertNotIn(
            'Invoke-GcloudCopy $ObjectPath "gs://$Bucket/quant/v1/$ObjectRelative"',
            source,
        )
        self.assertLess(source.index("# Upload objects"), source.index("# Upload manifest"))
        self.assertLess(
            source.index("# Upload manifest"), source.index("# Upload latest pointer")
        )

    def test_uploader_sends_market_insights_before_large_market_snapshots(self):
        source = UPLOADER.read_text(encoding="utf-8")

        self.assertLess(source.index("$InsightsUploaded"), source.index("$UploadedMarkets"))

    def test_uploader_validates_and_uploads_report_latest_last_without_blocking_quant(self):
        source = UPLOADER.read_text(encoding="utf-8")

        for required in (
            r"publish\reports\v1",
            "ReportUploadError",
            "metadata/[0-9a-f]{64}",
            "objects/[0-9a-f]{64}",
            "index-TW.json",
            "reports/v1/",
            "日報上傳失敗",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertLess(
            source.index('"gs://$Bucket/reports/v1/$ReportPdfRelative"'),
            source.index('"gs://$Bucket/reports/v1/index-TW.json"'),
        )
        self.assertLess(
            source.index('"gs://$Bucket/reports/v1/index-TW.json"'),
            source.index('"gs://$Bucket/reports/v1/latest-TW.json"'),
        )

    def test_lifecycle_deletes_cloud_objects_after_thirty_days(self):
        source = LIFECYCLE.read_text(encoding="utf-8")

        self.assertIn('"type": "Delete"', source)
        self.assertIn('"age": 30', source)

    def test_installer_registers_separate_0935_upload_task(self):
        source = INSTALLER.read_text(encoding="utf-8")

        for required in (
            "StockPapi-QuantUpload",
            "upload_local_quant.ps1",
            "09:35",
            "New-TimeSpan -Hours 1",
            "RunLevel Limited",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_cloud_build_excludes_local_and_untracked_artifacts(self):
        for path in (DOCKERIGNORE, GCLOUDIGNORE):
            source = path.read_text(encoding="utf-8")
            for required in (
                "0.26.0",
                "deliverables/",
                "scripts/build_competition_doc.py",
                ".deps/",
                ".env",
            ):
                with self.subTest(path=path.name, required=required):
                    self.assertIn(required, source)

    def test_installer_enforces_d_drive_schedule_and_resource_limits(self):
        source = INSTALLER.read_text(encoding="utf-8")

        for required in (
            r"D:\StockPapiData",
            "NTFS",
            "$MinimumFreeGB = 100",
            "$MinimumFreeGB * 1GB",
            "02:30",
            "ExecutionTimeLimit",
            "New-TimeSpan -Hours 7",
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
            "--insights",
            "--market",
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
        self.assertNotIn("--market ALL", source)
        self.assertEqual(source.count("--limit 5000"), 2)
        self.assertLess(source.index("--insights"), source.index("--market TW"))
        self.assertLess(source.index("--market TW"), source.index("Start-Sleep"))
        self.assertLess(source.index("Start-Sleep"), source.index("--market US"))

    def test_wrapper_generates_report_only_after_a_new_tw_manifest_and_continues_on_failure(self):
        source = WRAPPER.read_text(encoding="utf-8")

        self.assertIn("$TwLatestBefore", source)
        self.assertIn("$TwLatestAfter", source)
        self.assertIn("-m reporting.cli", source)
        self.assertIn("日報生成失敗", source)
        self.assertLess(source.index("--market TW"), source.index("-m reporting.cli"))
        self.assertLess(source.index("-m reporting.cli"), source.index("--market US"))
        self.assertNotIn("exit $ReportExitCode", source)

    def test_installer_schedules_wrapper_instead_of_embedding_market_arguments(self):
        source = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("$Wrapper", source)
        self.assertIn("-File", source)
        self.assertIn("run_local_quant_task.ps1", source)


if __name__ == "__main__":
    unittest.main()
