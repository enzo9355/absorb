import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.report_fixtures import stock_document, write_quant_publish


class DailyReportCliTests(unittest.TestCase):
    def test_dry_run_validates_real_snapshot_without_publishing_mock_report(self):
        from reporting.cli import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_quant_publish(root, [stock_document("2330")])
            with patch("reporting.cli._load_industry_map", return_value={"半導體": ["2330"]}):
                exit_code = main(["--root", str(root), "--dry-run"])

            status = json.loads((root / "logs" / "report-status.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertTrue(status["success"])
            self.assertEqual(status["report_date"], "2026-07-03")
            self.assertIsNone(status["pdf_path"])
            self.assertFalse((root / "publish" / "reports" / "v1" / "latest-TW.json").exists())

    def test_cli_passes_latest_valid_previous_source_to_daily_comparison(self):
        from reporting.cli import main
        from reporting.industry_analytics import build_daily_report

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_quant_publish(root, [stock_document("2330", as_of="2026-07-02")])
            write_quant_publish(root, [stock_document("2330", as_of="2026-07-03")])
            with patch("reporting.cli._load_industry_map", return_value={"半導體": ["2330"]}), patch(
                "reporting.cli.build_daily_report", wraps=build_daily_report
            ) as build:
                exit_code = main(["--root", str(root), "--dry-run"])

            self.assertEqual(exit_code, 0)
            previous = build.call_args.kwargs["previous_source"]
            self.assertEqual(previous.manifest.market_as_of.isoformat(), "2026-07-02")

    def test_cli_uses_permanent_archive_and_removes_staged_pdf(self):
        from reporting.cli import main
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = stock_document("2330")
            document.update(name="台積電", sample_data=False)
            write_quant_publish(root, [document])

            def generate(_report, output):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"%PDF-1.4 generated")
                return ReportGenerationResult.from_path(
                    output, _report.report_date, page_count=1, warnings=[]
                )

            with patch("reporting.cli._load_industry_map", return_value={"半導體": ["2330"]}), patch(
                "reporting.cli.DailyIndustryReportGenerator.generate", side_effect=generate
            ) as mocked_generate:
                exit_code = main(["--root", str(root)])

            filename = "stock-papi-tw-industry-daily-2026-07-03.pdf"
            archive = root / "reports" / "TW"
            staged = archive / ".staging" / filename
            status = json.loads((root / "logs" / "report-status.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked_generate.call_args.args[1], staged)
            self.assertEqual(status["pdf_path"], str(archive / filename))
            self.assertFalse(staged.exists())


if __name__ == "__main__":
    unittest.main()
