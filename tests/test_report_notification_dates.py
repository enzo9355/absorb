import argparse
import datetime
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_papi.batch.cli import run_notification


class ReportNotificationDatesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        publish_v2 = self.root / "publish" / "reports" / "v2"
        metadata_dir = publish_v2 / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        post_close_content = {"market_observation": {"risk_state": "normal"}}
        post_close_c_sha = hashlib.sha256(
            json.dumps(post_close_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        post_close_meta = {
            "schema_version": 2,
            "kind": "absorb-report",
            "report_type": "post_close",
            "product_mode": "observation",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-17T10:00:00Z",
            "forecast_start_date": "2026-07-20",
            "forecast_end_date": "2026-07-20",
            "observation_start_date": "2026-07-17",
            "observation_end_date": "2026-07-20",
            "backtest_as_of": None,
            "data_as_of": "2026-07-17",
            "source_manifest": "quant/v1/manifests/TW-20260717T090000Z-aaaaaaaaaaaa.json",
            "source_manifest_sha256": "a" * 64,
            "model_versions": {},
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "content_sha256": post_close_c_sha,
            "summary": ["盤後報告摘要"],
            "title": "盤後觀察",
            "warnings": [],
            "content": post_close_content,
        }
        post_close_bytes = json.dumps(post_close_meta, sort_keys=True).encode("utf-8")
        post_close_hash = hashlib.sha256(post_close_bytes).hexdigest()
        post_close_rel = f"metadata/{post_close_hash}.json"
        (publish_v2 / post_close_rel).write_bytes(post_close_bytes)

        pre_market_content = {"core": post_close_content}
        pre_market_c_sha = hashlib.sha256(
            json.dumps(pre_market_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        pre_market_meta = {
            "schema_version": 2,
            "kind": "absorb-report",
            "report_type": "pre_market",
            "product_mode": "observation",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-20T00:00:00Z",
            "forecast_start_date": "2026-07-20",
            "forecast_end_date": "2026-07-20",
            "observation_start_date": "2026-07-17",
            "observation_end_date": "2026-07-20",
            "backtest_as_of": None,
            "data_as_of": "2026-07-17",
            "source_manifest": "quant/v1/manifests/TW-20260717T090000Z-aaaaaaaaaaaa.json",
            "source_manifest_sha256": "a" * 64,
            "model_versions": {},
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "content_sha256": pre_market_c_sha,
            "summary": ["盤前報告摘要"],
            "title": "盤前更新",
            "warnings": [],
            "content": pre_market_content,
        }
        pre_market_bytes = json.dumps(pre_market_meta, sort_keys=True).encode("utf-8")
        pre_market_hash = hashlib.sha256(pre_market_bytes).hexdigest()
        pre_market_rel = f"metadata/{pre_market_hash}.json"
        (publish_v2 / pre_market_rel).write_bytes(pre_market_bytes)

        index_doc = {
            "schema_version": 2,
            "kind": "absorb-report-index",
            "market": "TW",
            "reports": [
                {
                    "schema_version": 2,
                    "report_type": "post_close",
                    "product_mode": "observation",
                    "market": "TW",
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                    "published_at": "2026-07-17T10:00:00Z",
                    "data_as_of": "2026-07-17",
                    "metadata": post_close_rel,
                    "metadata_sha256": post_close_hash,
                    "content_sha256": post_close_c_sha,
                    "model_versions": {},
                    "title": "盤後觀察",
                    "summary": ["盤後報告摘要"],
                },
                {
                    "schema_version": 2,
                    "report_type": "pre_market",
                    "product_mode": "observation",
                    "market": "TW",
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                    "published_at": "2026-07-20T00:00:00Z",
                    "data_as_of": "2026-07-17",
                    "metadata": pre_market_rel,
                    "metadata_sha256": pre_market_hash,
                    "content_sha256": pre_market_c_sha,
                    "model_versions": {},
                    "title": "盤前更新",
                    "summary": ["盤前報告摘要"],
                },
            ],
        }
        (publish_v2 / "index-TW.json").write_bytes(
            json.dumps(index_doc, sort_keys=True).encode("utf-8")
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch.dict(
        os.environ,
        {
            "REPORT_NOTIFICATION_ENABLED": "true",
            "REPORT_PUBLIC_BASE_URL": "https://reports.absorb.tw",
        },
    )
    def test_post_close_notification_uses_source_market_date_in_url(self):
        delivered_urls = []

        def mock_deliver(self_mgr, **kwargs):
            delivered_urls.append(kwargs.get("public_url"))
            return {"status": "sent"}

        args = argparse.Namespace(
            root=str(self.root),
            report_type="post_close",
            audience=["admin"],
        )

        with patch("stock_papi.batch.notifications.NotificationManager.deliver", mock_deliver):
            code = run_notification(args)

        self.assertEqual(code, 0)
        self.assertEqual(len(delivered_urls), 1)
        self.assertEqual(
            delivered_urls[0],
            "https://reports.absorb.tw/reports/2026-07-17/post-close",
        )

    @patch.dict(
        os.environ,
        {
            "REPORT_NOTIFICATION_ENABLED": "true",
            "REPORT_PUBLIC_BASE_URL": "https://reports.absorb.tw",
        },
    )
    def test_pre_market_notification_uses_applicable_trading_date_in_url(self):
        delivered_urls = []

        def mock_deliver(self_mgr, **kwargs):
            delivered_urls.append(kwargs.get("public_url"))
            return {"status": "sent"}

        args = argparse.Namespace(
            root=str(self.root),
            report_type="pre_market",
            audience=["admin"],
        )

        with patch("stock_papi.batch.notifications.NotificationManager.deliver", mock_deliver):
            code = run_notification(args)

        self.assertEqual(code, 0)
        self.assertEqual(len(delivered_urls), 1)
        self.assertEqual(
            delivered_urls[0],
            "https://reports.absorb.tw/reports/2026-07-20/pre-market",
        )


if __name__ == "__main__":
    unittest.main()
