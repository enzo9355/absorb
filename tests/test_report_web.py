import hashlib
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
        self.metadata = {
            "schema_version": 1,
            "kind": "daily-industry-report",
            "market": "TW",
            "report_date": "2026-07-03",
            "data_as_of": "2026-07-03",
            "generated_at": "2026-07-03T10:00:00Z",
            "coverage": 0.98,
            "pdf_path": f"objects/{self.digest}.pdf",
            "pdf_sha256": self.digest,
            "pdf_size": len(self.pdf),
            "page_count": 7,
            "summary": ["市場維持整理", "半導體相對強勢"],
            "warnings": ["歷史資料不代表未來"],
            "public_report": {
                "schema_version": 1,
                "market_recommendation": {
                    "action": "控制追價", "level": "neutral",
                    "headline": "市場訊號尚未形成一致優勢",
                    "confidence": "可信度中等",
                    "supporting_reasons": ["五日上漲機率 58%"],
                    "risk_reasons": ["量能不足"],
                    "suggested_action": "降低追價速度。",
                    "invalidation_conditions": ["市場趨勢轉弱"],
                },
                "key_points": ["市場維持整理", "半導體相對強勢"],
                "industries": [{
                    "name": "半導體", "probability": 62.0,
                    "rotation": "領先", "action": "優先關注",
                    "headline": "模型與產業強弱位置一致",
                    "risk": "接近輪動分界", "confidence": "可信度中等",
                }],
                "stocks": [{
                    "symbol": "2330", "name": "台積電", "probability": 68.0,
                    "action": "分批布局", "headline": "模型與趨勢偏多",
                    "risks": ["短線偏熱"], "confidence": "可信度有限",
                }],
                "backtest": {
                    "advantage": "過去相同規則優於買進持有。",
                    "sample_quality": "可信度中等",
                },
                "model_quality": {"samples": 120, "direction_accuracy": 55.0, "brier_score": 0.23},
            },
        }
        self.metadata_bytes = json.dumps(self.metadata, separators=(",", ":")).encode()
        self.metadata_digest = hashlib.sha256(self.metadata_bytes).hexdigest()
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
                "market_action": "控制追價",
                "headline": "市場訊號尚未形成一致優勢",
                "key_industries": ["半導體"],
                "metadata": f"metadata/{self.metadata_digest}.json",
                "metadata_sha256": self.metadata_digest,
            }],
        }

    def _reader(self, object_name, _max_bytes):
        if object_name == "reports/v1/index-TW.json":
            return json.dumps(self.index).encode("utf-8")
        if object_name == f"reports/v1/objects/{self.digest}.pdf":
            return self.pdf
        if object_name == f"reports/v1/metadata/{self.metadata_digest}.json":
            return self.metadata_bytes
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
        self.assertIn("控制追價", html)
        self.assertIn("半導體", html)
        self.assertIn("閱讀完整報告", html)
        self.assertNotIn("下載", html)

    def test_empty_reports_page_has_clear_state(self):
        with patch.object(stock_app, "_gcs_get_report_object", return_value=None, create=True):
            response = stock_app.app.test_client().get("/reports")

        self.assertEqual(response.status_code, 200)
        self.assertIn("目前沒有可用的每日報告", response.get_data(as_text=True))

    def test_sample_download_redirects_to_public_html_list_without_pdf_bytes(self):
        response = stock_app.app.test_client().get("/reports/sample/download")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/reports"))
        self.assertNotEqual(response.mimetype, "application/pdf")

    def test_reports_page_keeps_sample_download_outside_formal_history(self):
        with patch.object(stock_app, "_gcs_get_report_object", return_value=None, create=True):
            response = stock_app.app.test_client().get("/reports")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SAMPLE", html)
        self.assertNotIn("/reports/sample/download", html)

    def test_html_report_is_formal_public_entry_and_old_pdf_routes_redirect(self):
        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=self._reader, create=True
        ):
            client = stock_app.app.test_client()
            report = client.get("/reports/2026-07-03")
            preview = client.get("/reports/2026-07-03/preview")
            download = client.get("/reports/2026-07-03/download")

        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.mimetype, "text/html")
        self.assertIn("30 秒市場結論", report.get_data(as_text=True))
        self.assertIn("控制追價", report.get_data(as_text=True))
        self.assertIn("支持理由", report.get_data(as_text=True))
        self.assertIn("主要風險", report.get_data(as_text=True))
        self.assertIn("查看完整專業數據", report.get_data(as_text=True))
        self.assertEqual(report.headers["Cache-Control"], "public, max-age=300")
        self.assertEqual(preview.status_code, 302)
        self.assertTrue(preview.headers["Location"].endswith("/reports/2026-07-03"))
        self.assertEqual(download.status_code, 302)
        self.assertTrue(download.headers["Location"].endswith("/reports/2026-07-03"))
        self.assertNotEqual(download.mimetype, "application/pdf")

    def test_bad_hash_returns_safe_error_and_date_or_path_cannot_be_injected(self):
        def corrupt_reader(object_name, max_bytes):
            content = self._reader(object_name, max_bytes)
            return b"corrupt" if "/metadata/" in object_name else content

        with patch.object(
            stock_app, "_gcs_get_report_object", side_effect=corrupt_reader, create=True
        ):
            client = stock_app.app.test_client()
            bad_hash = client.get("/reports/2026-07-03")
            bad_date = client.get("/reports/not-a-date")
            missing = client.get("/reports/2026-07-04")
            traversal = client.get("/reports/../../secret")

        self.assertEqual(bad_hash.status_code, 503)
        self.assertNotIn("objects/", bad_hash.get_data(as_text=True))
        self.assertEqual(bad_date.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(traversal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
