import unittest
from pathlib import Path


class PipelineSchedulerTests(unittest.TestCase):
    def test_new_tasks_are_separate_resilient_limited_and_secret_free(self):
        scripts = Path(__file__).parents[1] / "scripts"
        script = (scripts / "install_pipeline_tasks.ps1").read_text(encoding="utf-8")
        for name in ("ABSORB-TW-PostClose", "ABSORB-TW-PreMarket", "ABSORB-FullBacktest", "ABSORB-US-Daily", "ABSORB-WeeklyModel", "ABSORB-ReportUploadRecovery"):
            self.assertIn(name, script)
        for setting in ("StartWhenAvailable = $true", "WakeToRun = $true", "MultipleInstances IgnoreNew", "RestartCount 3", "RunLevel Limited"):
            self.assertIn(setting, script)
        for secret in ("LINE_CHANNEL_ACCESS_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS", "Bearer"):
            self.assertNotIn(secret, script)
        self.assertNotIn("Unregister-ScheduledTask", script)
        for wrapper in (
            "run_tw_post_close_pipeline.ps1",
            "run_tw_pre_market_pipeline.ps1",
            "run_full_backtest.ps1",
            "run_us_daily.ps1",
            "run_weekly_model.ps1",
            "upload_local_quant.ps1",
        ):
            with self.subTest(wrapper=wrapper):
                self.assertTrue((scripts / wrapper).is_file())
                self.assertIn(wrapper, (scripts / "invoke_pipeline_task.ps1").read_text(encoding="utf-8"))
        self.assertIn("invoke_pipeline_task.ps1", script)
        self.assertIn("Task wrapper not found", script)
        self.assertIn("New-ScheduledTaskTrigger -Weekly", script)
        self.assertIn(r"D:\AbsorbData", script)
        self.assertIn("-RequireReportV2", (scripts / "invoke_pipeline_task.ps1").read_text(encoding="utf-8"))
        post_close = (scripts / "run_tw_post_close_pipeline.ps1").read_text(encoding="utf-8")
        self.assertLess(post_close.index("calendar-check"), post_close.index("--post-close"))

    def test_full_backtest_logs_nonfatal_python_warnings_but_keeps_exit_code(self):
        source = (Path(__file__).parents[1] / "scripts" / "run_full_backtest.ps1").read_text(encoding="utf-8")
        self.assertIn("$ErrorActionPreference = 'Continue'", source)
        self.assertIn("$ExitCode = $LASTEXITCODE", source)
        self.assertIn("$ErrorActionPreference = 'Stop'", source)

    def test_task_wrapper_records_success_or_failure_without_secrets(self):
        source = (Path(__file__).parents[1] / "scripts" / "invoke_pipeline_task.ps1").read_text(encoding="utf-8")
        for required in ("logs\\tasks", "current-", "Get-Command powershell.exe", "Start-Process", "RedirectStandardOutput", "RedirectStandardError", "$ChildProcess.WaitForExit()", "$ChildProcess.ExitCode", "success = $false"):
            with self.subTest(required=required):
                self.assertIn(required, source)
        for forbidden in ("LINE_CHANNEL_ACCESS_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS", "Bearer"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__": unittest.main()
