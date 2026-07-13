import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.report_fixtures import stock_document, write_quant_publish


class DailyReportPublishTests(unittest.TestCase):
    def _report(self, root: Path):
        from reporting.industry_analytics import build_daily_report
        from reporting.source_loader import load_report_source

        document = stock_document("2330")
        document.update(name="台積電", sample_data=False)
        write_quant_publish(root, [document])
        return build_daily_report(load_report_source(root), {"半導體": ["2330"]})

    def test_content_addressed_pdf_metadata_latest_and_sorted_index(self):
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            result = ReportGenerationResult.from_path(
                pdf, report.report_date, page_count=7, warnings=[]
            )

            latest_path = publish_report(root, report, result)

            publish = root / "publish" / "reports" / "v1"
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            metadata_path = publish / latest["metadata"]
            metadata_bytes = metadata_path.read_bytes()
            metadata = json.loads(metadata_bytes)
            self.assertEqual(
                hashlib.sha256(metadata_bytes).hexdigest(), latest["metadata_sha256"]
            )
            self.assertEqual(metadata["pdf_sha256"], result.sha256)
            self.assertEqual(metadata["report_schema_version"], 2)
            self.assertEqual(metadata["report_generator_version"], "2.0.0")
            self.assertRegex(metadata["git_commit_sha"], r"^[0-9a-f]{7,40}$|^unknown$")
            self.assertFalse(metadata["sample_data"])
            self.assertTrue((publish / metadata["pdf_path"]).is_file())
            index = json.loads((publish / "index-TW.json").read_text(encoding="utf-8"))
            self.assertEqual(index["reports"][0]["report_date"], "2026-07-03")
            mirror = root / "reports" / "TW" / "stock-papi-tw-industry-daily-2026-07-03.pdf"
            self.assertEqual(mirror.read_bytes(), pdf.read_bytes())
            self.assertEqual(
                json.loads(mirror.with_suffix(".json").read_text(encoding="utf-8")),
                metadata,
            )

    def test_same_pdf_hash_keeps_existing_local_mirror_unchanged(self):
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            pdf = root / "report.pdf"
            pdf.write_bytes(b"%PDF-1.4 identical")
            result = ReportGenerationResult.from_path(pdf, report.report_date, page_count=7, warnings=[])

            publish_report(root, report, result)
            mirror = root / "reports" / "TW" / "stock-papi-tw-industry-daily-2026-07-03.pdf"
            sidecar = mirror.with_suffix(".json")
            before = (mirror.read_bytes(), sidecar.read_bytes(), mirror.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)

            publish_report(root, report, result)

            self.assertEqual(
                (mirror.read_bytes(), sidecar.read_bytes(), mirror.stat().st_mtime_ns, sidecar.stat().st_mtime_ns),
                before,
            )

    def test_mirror_write_failure_restores_existing_friendly_copy(self):
        from reporting import publisher
        from reporting.exceptions import ReportPublishError
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            first = root / "first.pdf"
            first.write_bytes(b"%PDF-1.4 first")
            publish_result = ReportGenerationResult.from_path(
                first, report.report_date, page_count=7, warnings=[]
            )
            publisher.publish_report(root, report, publish_result)
            mirror = root / "reports" / "TW" / "stock-papi-tw-industry-daily-2026-07-03.pdf"
            sidecar = mirror.with_suffix(".json")
            before = (mirror.read_bytes(), sidecar.read_bytes())
            second = root / "second.pdf"
            second.write_bytes(b"%PDF-1.4 second")
            second_result = ReportGenerationResult.from_path(
                second, report.report_date, page_count=7, warnings=[]
            )
            original_write = publisher._write_atomic

            def fail_sidecar(path, content):
                if Path(path) == sidecar:
                    raise OSError("sidecar write failed")
                return original_write(path, content)

            with patch.object(publisher, "_write_atomic", side_effect=fail_sidecar):
                with self.assertRaises(ReportPublishError):
                    publisher.publish_report(root, report, second_result)

            self.assertEqual((mirror.read_bytes(), sidecar.read_bytes()), before)

    def test_failed_publish_preserves_previous_latest(self):
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            latest = root / "publish" / "reports" / "v1" / "latest-TW.json"
            latest.parent.mkdir(parents=True)
            latest.write_text('{"previous":true}', encoding="utf-8")
            failed = ReportGenerationResult.failure(report.report_date, "font missing")

            with self.assertRaisesRegex(ValueError, "successful"):
                publish_report(root, report, failed)

            self.assertEqual(latest.read_text(encoding="utf-8"), '{"previous":true}')

    def test_sample_report_cannot_replace_formal_latest(self):
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_quant_publish(root, [stock_document("2330")])
            from reporting.industry_analytics import build_daily_report
            from reporting.source_loader import load_report_source

            report = build_daily_report(load_report_source(root), {"半導體": ["2330"]})
            latest = root / "publish" / "reports" / "v1" / "latest-TW.json"
            latest.parent.mkdir(parents=True)
            latest.write_text('{"previous":true}', encoding="utf-8")
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")

            with self.assertRaisesRegex(ValueError, "SAMPLE"):
                publish_report(
                    root,
                    report,
                    ReportGenerationResult.from_path(
                        pdf, report.report_date, page_count=1, warnings=[]
                    ),
                )

            self.assertEqual(latest.read_text(encoding="utf-8"), '{"previous":true}')

    def test_same_day_republish_keeps_one_newest_index_entry(self):
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            first = root / "first.pdf"
            first.write_bytes(b"%PDF-1.4 first")
            publish_report(
                root,
                report,
                ReportGenerationResult.from_path(first, report.report_date, page_count=7, warnings=[]),
            )
            second = root / "second.pdf"
            second.write_bytes(b"%PDF-1.4 second")
            second_result = ReportGenerationResult.from_path(
                second, report.report_date, page_count=8, warnings=[]
            )

            publish_report(root, report, second_result)

            publish = root / "publish" / "reports" / "v1"
            index = json.loads((publish / "index-TW.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["reports"]), 1)
            self.assertEqual(index["reports"][0]["pdf_sha256"], second_result.sha256)
            mirror = root / "reports" / "TW" / "stock-papi-tw-industry-daily-2026-07-03.pdf"
            self.assertEqual(mirror.read_bytes(), second.read_bytes())
            self.assertTrue((publish / f"objects/{hashlib.sha256(first.read_bytes()).hexdigest()}.pdf").is_file())

    def test_corrupt_existing_index_does_not_replace_previous_latest(self):
        from reporting.exceptions import ReportPublishError
        from reporting.publisher import publish_report
        from reporting.schemas import ReportGenerationResult

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self._report(root)
            publish = root / "publish" / "reports" / "v1"
            publish.mkdir(parents=True)
            latest = publish / "latest-TW.json"
            latest.write_text('{"previous":true}', encoding="utf-8")
            (publish / "index-TW.json").write_text('{"broken":true}', encoding="utf-8")
            pdf = root / "report.pdf"
            pdf.write_bytes(b"%PDF-1.4 report")
            result = ReportGenerationResult.from_path(
                pdf, report.report_date, page_count=7, warnings=[]
            )

            with self.assertRaises(ReportPublishError):
                publish_report(root, report, result)

            self.assertEqual(latest.read_text(encoding="utf-8"), '{"previous":true}')


if __name__ == "__main__":
    unittest.main()
