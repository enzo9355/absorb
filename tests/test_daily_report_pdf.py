import tempfile
import unittest
import inspect
from pathlib import Path

from tests.report_fixtures import stock_document, write_quant_publish


class DailyReportPdfTests(unittest.TestCase):
    def _report(self, root):
        from reporting.industry_analytics import build_daily_report
        from reporting.source_loader import load_report_source

        write_quant_publish(root, [stock_document("2330"), stock_document("2317")])
        return build_daily_report(
            load_report_source(root),
            {"半導體": ["2330", "2317"], "AI 題材": ["2330"]},
        )

    def test_missing_chinese_font_fails_without_overwriting_existing_pdf(self):
        from reporting.config import ReportConfig
        from reporting.pdf_generator import DailyIndustryReportGenerator

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report.pdf"
            output.write_bytes(b"previous")
            generator = DailyIndustryReportGenerator(
                ReportConfig(font_path=root / "missing.ttf", bold_font_path=root / "missing.ttf")
            )

            result = generator.generate(self._report(root), output)

            self.assertFalse(result.success)
            self.assertEqual(output.read_bytes(), b"previous")
            self.assertFalse(output.with_suffix(".pdf.tmp").exists())

    def test_generated_pdf_opens_and_extracts_traditional_chinese(self):
        from pypdf import PdfReader
        from reporting.config import ReportConfig
        from reporting.pdf_generator import DailyIndustryReportGenerator

        font = Path(r"C:\Windows\Fonts\NotoSansTC-VF.ttf")
        title_font = Path(r"C:\Windows\Fonts\NotoSerifTC-VF.ttf")
        self.assertTrue(font.is_file(), "測試環境缺少 Noto Sans TC")
        self.assertTrue(title_font.is_file(), "測試環境缺少 Noto Serif TC")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "sample-report.pdf"
            generator = DailyIndustryReportGenerator(
                ReportConfig(
                    font_path=font,
                    bold_font_path=font,
                    title_font_path=title_font,
                    min_backtest_periods=2,
                )
            )

            result = generator.generate(self._report(root), output)
            self.assertTrue(result.success, result.error_message)
            reader = PdfReader(output)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)

            self.assertGreaterEqual(len(reader.pages), 5)
            self.assertIn("SAMPLE / TEST DATA", text)
            self.assertIn("不得正式發布", text)
            self.assertIn("不得作為正式投資或模型結果", text)
            self.assertIn("台股產業量化分析日報", text)
            self.assertIn("本報告內容僅供量化研究", text)
            self.assertIn("產業五日上漲機率排名", text)
            self.assertIn("排名依產業有效成分股最新五日上漲機率等權平均", text)
            self.assertIn("接近分界", text)
            self.assertIn("X 軸：20 日相對大盤報酬", text)
            self.assertIn("策略累積報酬（已扣成本）", text)
            self.assertIn("0.585%", text)
            self.assertIn("pooled OOS 樣本數", text)
            self.assertIn("外資近五日淨買賣超（股）", text)
            self.assertIn("source manifest", text)
            self.assertIn("report schema version", text)
            self.assertIn("自動生成、未經人工分析師覆核", text)
            self.assertIn("無前期報告可比較", text)
            self.assertTrue(all(len((page.extract_text() or "").strip()) > 30 for page in reader.pages))

    def test_pdf_uses_flowing_layout_without_fixed_page_breaks(self):
        from reporting.pdf_generator import DailyIndustryReportGenerator

        self.assertNotIn("PageBreak", inspect.getsource(DailyIndustryReportGenerator._build_pdf))

    def test_formal_report_rejects_placeholder_stock_names(self):
        from reporting.config import ReportConfig
        from reporting.industry_analytics import build_daily_report
        from reporting.pdf_generator import DailyIndustryReportGenerator
        from reporting.source_loader import load_report_source

        font = Path(r"C:\Windows\Fonts\NotoSansTC-VF.ttf")
        title_font = Path(r"C:\Windows\Fonts\NotoSerifTC-VF.ttf")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = stock_document("2330")
            document["sample_data"] = False
            write_quant_publish(root, [document])
            report = build_daily_report(load_report_source(root), {"半導體": ["2330"]})
            result = DailyIndustryReportGenerator(
                ReportConfig(
                    font_path=font,
                    bold_font_path=font,
                    title_font_path=title_font,
                )
            ).generate(report, root / "formal.pdf")

        self.assertFalse(result.success)
        self.assertIn("測試股票", result.error_message)


if __name__ == "__main__":
    unittest.main()
