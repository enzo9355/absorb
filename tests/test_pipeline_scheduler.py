import unittest
from pathlib import Path


class PipelineSchedulerTests(unittest.TestCase):
    def test_new_tasks_are_separate_resilient_limited_and_secret_free(self):
        scripts = Path(__file__).parents[1] / "scripts"
        script = (scripts / "install_pipeline_tasks.ps1").read_text(encoding="utf-8")
        for name in ("StockPapi-TW-PostClose", "StockPapi-TW-PreMarket", "StockPapi-FullBacktest", "StockPapi-US-Daily", "StockPapi-WeeklyModel", "StockPapi-ReportUploadRecovery"):
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
                self.assertIn(wrapper, script)
        self.assertIn("Task wrapper not found", script)
        self.assertIn("New-ScheduledTaskTrigger -Weekly", script)


if __name__ == "__main__": unittest.main()
