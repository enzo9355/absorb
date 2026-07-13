import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app


class ReportWebTests(unittest.TestCase):
    def setUp(self):
        self.pdf = b"%PDF-1.4 verified report bytes"
        self.digest = hashlib.sha256(self.pdf).hexdigest()
        self.index = {
            "schema_version": 1,
            "kind": "daily-industry-report-index",
            "market": "TW",
            "updated_at": "2026-07-03T10:00:00Z",
            "reports": [{
                "report_date": "2026-07-03",
                "data_as_of": "2026-07-03",
                "generated_at": "2026-07-03T10:00:00Z",
                "model_versions": {"lgbm-5d-v1": 2},
                "coverage": 0.98,
                "pdf_path": f"objects/{self.digest}.pdf",
                "pdf_sha256": self.digest,
                "pdf_size": len(self.pdf),
                "page_count": 7,
                "metadata": "metadata/" + "a" * 64 + ".json",
                "metadata_sha256": "a" * 64,
            }],
        }

    def _reader(self, object_name, _max_bytes):
        if object_name == "reports/v1/index-TW.json":
            return json.dumps(self.index).encode("utf-8")
        if object_name == f"reports/v1/objects/{self.digest}.pdf":
            return self.pdf
        return None

    def test_reports_page_lists_verified_history_and_navigation(self):
        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=self._reader, create=True
        ):
            response = stock_app.app.test_client().get("/reports")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("每日報告", html)
        self.assertIn("2026-07-03", html)
        self.assertIn("98.0%", html)
        self.assertIn("預覽", html)
        self.assertIn("下載", html)

    def test_empty_reports_page_has_clear_state(self):
        with patch.object(stock_app, "_gcs_get_report_object", return_value=None, create=True):
            response = stock_app.app.test_client().get("/reports")

        self.assertEqual(response.status_code, 200)
        self.assertIn("目前沒有可用的每日報告", response.get_data(as_text=True))

    def test_sample_download_is_fixed_labeled_pdf_without_gcs(self):
        from pypdf import PdfReader

        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=AssertionError("SAMPLE 不得讀取 GCS")
        ):
            response = stock_app.app.test_client().get("/reports/sample/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("SAMPLE", response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"%PDF"))
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.data)).pages)
        self.assertIn("SAMPLE / TEST DATA", text)
        self.assertIn("不得正式發布", text)
        self.assertIn("不得作為正式投資或模型結果", text)

    def test_reports_page_keeps_sample_download_outside_formal_history(self):
        with patch.object(stock_app, "_gcs_get_report_object", return_value=None, create=True):
            response = stock_app.app.test_client().get("/reports")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("僅供展示報告版面與下載功能", html)
        self.assertIn("/reports/sample/download", html)

    def test_preview_and_download_validate_index_hash_and_disposition(self):
        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=self._reader, create=True
        ):
            client = stock_app.app.test_client()
            preview = client.get("/reports/2026-07-03/preview")
            download = client.get("/reports/2026-07-03/download")

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "application/pdf")
        self.assertIn("inline", preview.headers["Content-Disposition"])
        self.assertIn(self.digest, preview.headers["ETag"])
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertIn("stock-papi-tw-industry-daily-2026-07-03.pdf", download.headers["Content-Disposition"])

    def test_bad_hash_returns_safe_error_and_date_or_path_cannot_be_injected(self):
        def corrupt_reader(object_name, max_bytes):
            content = self._reader(object_name, max_bytes)
            return b"corrupt" if object_name.endswith(".pdf") else content

        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=corrupt_reader, create=True
        ):
            client = stock_app.app.test_client()
            bad_hash = client.get("/reports/2026-07-03/preview")
            bad_date = client.get("/reports/not-a-date/preview")
            missing = client.get("/reports/2026-07-04/download")
            traversal = client.get("/reports/../../secret/preview")

        self.assertEqual(bad_hash.status_code, 503)
        self.assertNotIn("objects/", bad_hash.get_data(as_text=True))
        self.assertEqual(bad_date.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(traversal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
