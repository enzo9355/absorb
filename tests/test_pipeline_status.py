import datetime
import json
import tempfile
import unittest
from pathlib import Path

from stock_papi.batch.cli import render_status
from stock_papi.batch.status import PipelineStatusError, PipelineStatusWriter


UTC = datetime.timezone.utc


class PipelineStatusTests(unittest.TestCase):
    def test_status_is_atomic_allowlisted_and_keeps_run_transcript(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer = PipelineStatusWriter(
                root,
                job_type="post_close_report",
                run_id="20260714T090000Z-aaaaaaaa",
                target_date=datetime.date(2026, 7, 14),
            )
            first = writer.record(
                "inference",
                now=datetime.datetime(2026, 7, 14, 9, tzinfo=UTC),
                details={"source_market_date": "2026-07-14"},
            )
            completed = writer.record(
                "completed",
                now=datetime.datetime(2026, 7, 14, 9, 5, tzinfo=UTC),
                details={
                    "report_date": "2026-07-14",
                    "manifest_path": "reports/v2/metadata/abc.json",
                },
            )

            current = json.loads(writer.current_path.read_text(encoding="utf-8"))
            transcript = [
                json.loads(line)
                for line in writer.transcript_path.read_text(encoding="utf-8").splitlines()
            ]
            last_success = json.loads(
                writer.last_success_path.read_text(encoding="utf-8")
            )
            self.assertEqual([item["sequence"] for item in transcript], [1, 2])
            self.assertEqual(transcript[0], first)
            self.assertEqual(current, completed)
            self.assertEqual(last_success, completed)
            self.assertFalse(list(writer.current_path.parent.glob("*.tmp")))

    def test_status_rejects_unknown_stage_and_detail_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            writer = PipelineStatusWriter(
                Path(temporary),
                job_type="upload",
                run_id="20260714T090000Z-aaaaaaaa",
                target_date=datetime.date(2026, 7, 14),
            )
            with self.assertRaises(PipelineStatusError):
                writer.record("execute-arbitrary")
            with self.assertRaises(PipelineStatusError):
                writer.record("upload", details={"authorization": "secret"})

    def test_error_text_is_redacted_before_current_and_transcript_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            writer = PipelineStatusWriter(
                Path(temporary),
                job_type="upload",
                run_id="20260714T090000Z-aaaaaaaa",
                target_date=datetime.date(2026, 7, 14),
            )
            writer.record(
                "failed",
                now=datetime.datetime(2026, 7, 14, 9, tzinfo=UTC),
                error=(
                    "Authorization: Bearer secret-token x-api-key=abc123 "
                    "user_id=U123456 credential=my-password"
                ),
            )

            persisted = writer.current_path.read_text(encoding="utf-8")
            for secret in ("secret-token", "abc123", "U123456", "my-password"):
                self.assertNotIn(secret, persisted)
            self.assertIn("[REDACTED]", persisted)

    def test_cli_summary_reports_last_success_stage_error_and_report_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer = PipelineStatusWriter(
                root,
                job_type="post_close_report",
                run_id="20260714T090000Z-aaaaaaaa",
                target_date=datetime.date(2026, 7, 14),
            )
            writer.record(
                "completed",
                now=datetime.datetime(2026, 7, 14, 9, tzinfo=UTC),
                details={"report_date": "2026-07-14"},
            )

            summary = render_status(root)

            self.assertIn("post_close_report", summary)
            self.assertIn("completed", summary)
            self.assertIn("2026-07-14", summary)


if __name__ == "__main__":
    unittest.main()
