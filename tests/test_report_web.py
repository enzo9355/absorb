import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app

from reporting.observation_v2 import build_post_close_observation_metadata
from reporting.publisher import publish_report_v2
from tests.test_observation_public_surfaces import observation_dashboard


class Calendar:
    def next_session(self, value):
        self.requested = value
        return datetime.date(2026, 7, 16)


class ReportWebTests(unittest.TestCase):
    def _objects(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        metadata = build_post_close_observation_metadata(
            observation_dashboard(), Calendar()
        )
        publish_report_v2(root, metadata)
        publish = root / "publish" / "reports" / "v2"
        objects = {
            f"reports/v2/{path.relative_to(publish).as_posix()}": path.read_bytes()
            for path in publish.rglob("*")
            if path.is_file()
        }
        return temporary, objects, metadata

    def test_v2_observation_report_is_the_only_formal_report_surface(self):
        temporary, objects, metadata = self._objects()
        self.addCleanup(temporary.cleanup)

        with patch.object(
            stock_app,
            "_gcs_get_report_v2_object",
            side_effect=lambda path, _size: objects.get(path),
            create=True,
        ):
            client = stock_app.app.test_client()
            listing = client.get("/reports")
            trading_day = client.get("/reports/trading-day/2026-07-16")
            pre_market = client.get("/reports/2026-07-16/pre-market")
            weekly = client.get("/reports/weekly/2026-W29")

        self.assertEqual(listing.status_code, 200)
        listing_html = listing.get_data(as_text=True)
        self.assertIn(metadata["title"], listing_html)
        self.assertIn("盤後觀察", listing_html)
        self.assertIn("閱讀觀察報告", listing_html)

        self.assertEqual(trading_day.status_code, 200)
        html = trading_day.get_data(as_text=True)
        for label in (
            "今日市場準備",
            "市場實況",
            "產業觀察",
            "個股異常事件",
            "ETF 觀察",
            "資料品質",
        ):
            self.assertIn(label, html)
        for forbidden in (
            "五日上漲機率",
            "模型驗證週報",
            "勝率",
            "推薦",
            "回測",
        ):
            self.assertNotIn(forbidden, html)
        self.assertEqual(
            trading_day.headers["Cache-Control"], "public, max-age=300"
        )
        self.assertEqual(pre_market.status_code, 404)
        self.assertEqual(weekly.status_code, 404)

    def test_legacy_reports_are_hidden_and_not_loaded_in_research_mode(self):
        with patch.object(
            stock_app, "_gcs_get_report_object", return_value=b"must-not-load"
        ) as legacy:
            client = stock_app.app.test_client()
            listing = client.get("/reports")
            report = client.get("/reports/2026-07-03")
            preview = client.get("/reports/2026-07-03/preview")
            download = client.get("/reports/2026-07-03/download")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(report.status_code, 404)
        self.assertEqual(preview.status_code, 302)
        self.assertEqual(download.status_code, 302)
        legacy.assert_not_called()

    def test_empty_reports_page_has_clear_state(self):
        with patch.object(
            stock_app, "_gcs_get_report_v2_object", return_value=None, create=True
        ):
            response = stock_app.app.test_client().get("/reports")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "目前沒有可用的每日報告",
            response.get_data(as_text=True),
        )

    def test_sample_download_redirects_to_public_html_list(self):
        response = stock_app.app.test_client().get("/reports/sample/download")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/reports"))
        self.assertNotEqual(response.mimetype, "application/pdf")

    def test_corrupt_observation_metadata_fails_closed(self):
        temporary, objects, _metadata = self._objects()
        self.addCleanup(temporary.cleanup)
        metadata_path = next(
            path for path in objects if "/metadata/" in path
        )
        objects[metadata_path] = b"corrupt"

        with patch.object(
            stock_app,
            "_gcs_get_report_v2_object",
            side_effect=lambda path, _size: objects.get(path),
            create=True,
        ):
            client = stock_app.app.test_client()
            bad_hash = client.get("/reports/trading-day/2026-07-16")
            bad_date = client.get("/reports/trading-day/not-a-date")
            missing = client.get("/reports/trading-day/2026-07-17")
            traversal = client.get("/reports/../../secret")

        self.assertEqual(bad_hash.status_code, 503)
        self.assertNotIn("metadata/", bad_hash.get_data(as_text=True))
        self.assertEqual(bad_date.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(traversal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
