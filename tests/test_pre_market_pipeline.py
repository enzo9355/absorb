import datetime
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from reporting.schemas import ReportMetadataV2
from stock_papi.batch.pre_market import PreMarketPipeline, PreMarketPipelineError
from stock_papi.integrations.market_data.overnight import (
    OvernightSourceError,
    OvernightSourceSpec,
    fetch_overnight_source,
)


UTC = datetime.timezone.utc


def base_receipt():
    metadata = {
        "schema_version": 2,
        "kind": "absorb-report",
        "product_mode": "observation",
        "report_type": "post_close",
        "market": "TW",
        "source_market_date": "2026-07-14",
        "applicable_trading_date": "2026-07-15",
        "published_at": "2026-07-14T10:00:00Z",
        "forecast_start_date": "2026-07-15",
        "forecast_end_date": "2026-07-15",
        "observation_start_date": "2026-07-14",
        "observation_end_date": "2026-07-15",
        "backtest_as_of": None,
        "data_as_of": "2026-07-14",
        "source_manifest": "quant/v1/manifests/TW-20260714T090000Z-aaaaaaaaaaaa.json",
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
        "title": "盤後市場觀察",
        "summary": ["市場風險狀態為中性"],
        "warnings": [],
        "content": {
            "market_observation": {"risk_state": "normal"},
            "daily_focus": ["市場風險狀態為中性"],
        },
    }
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"metadata": metadata, "metadata_sha256": hashlib.sha256(encoded).hexdigest()}


def overnight(name, signal="risk_off", as_of="2026-07-14T23:30:00Z"):
    return {
        "source": name,
        "as_of": as_of,
        "signal": signal,
        "summary": f"{name} 隔夜變化",
        "attribution_url": "https://example.com/market-data",
    }


class PreMarketPipelineTests(unittest.TestCase):
    def test_overnight_fetch_enforces_timeout_size_schema_timestamp_and_freshness(self):
        spec = OvernightSourceSpec(
            name="US futures",
            url="https://example.com/futures",
            timeout_seconds=3,
            max_bytes=1024,
            max_age=datetime.timedelta(hours=12),
        )
        calls = []
        result = fetch_overnight_source(
            spec,
            fetch_bytes=lambda url, timeout, max_bytes: calls.append((url, timeout, max_bytes))
            or json.dumps(overnight("US futures")).encode("utf-8"),
            now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC),
        )
        self.assertEqual(calls, [(spec.url, 3, 1024)])
        self.assertEqual(result["signal"], "risk_off")
        with self.assertRaises(OvernightSourceError):
            fetch_overnight_source(
                spec,
                fetch_bytes=lambda *_: b"x" * 1025,
                now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC),
            )
        with self.assertRaises(OvernightSourceError):
            fetch_overnight_source(
                spec,
                fetch_bytes=lambda *_: json.dumps(overnight("US futures", as_of="2026-07-13T00:00:00Z")).encode(),
                now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC),
            )

    def test_missing_or_invalid_base_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            prediction_base = base_receipt()
            prediction_base["metadata"].pop("product_mode")
            prediction_base["metadata_sha256"] = hashlib.sha256(
                json.dumps(
                    prediction_base["metadata"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for value in (
                None,
                {
                    "metadata": {"report_type": "pre_market"},
                    "metadata_sha256": "a" * 64,
                },
                prediction_base,
            ):
                with self.subTest(value=value), self.assertRaises(PreMarketPipelineError):
                    PreMarketPipeline(
                        Path(temporary),
                        applicable_trading_date=datetime.date(2026, 7, 15),
                        load_base=lambda value=value: value,
                        source_loaders=[],
                        publish=lambda _metadata: {},
                        notify=lambda _receipt: {},
                    ).run(now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC))

    def test_partial_sources_keep_core_bytes_unchanged_and_publish_without_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = base_receipt()
            before = json.dumps(base["metadata"]["content"], sort_keys=True, separators=(",", ":")).encode()
            published = []
            pipeline = PreMarketPipeline(
                Path(temporary),
                applicable_trading_date=datetime.date(2026, 7, 15),
                load_base=lambda: base,
                source_loaders=[
                    lambda: overnight("US futures", "risk_off"),
                    lambda: (_ for _ in ()).throw(TimeoutError("provider timeout")),
                ],
                publish=lambda metadata: published.append(metadata) or {"content_sha256": "b" * 64},
                notify=lambda _receipt: {"sent": True},
            )

            result = pipeline.run(now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC))

            document = published[0]
            parsed = ReportMetadataV2.from_document(document)
            after = json.dumps(document["content"]["core"], sort_keys=True, separators=(",", ":")).encode()
            self.assertEqual(before, after)
            self.assertEqual(parsed.product_mode, "observation")
            self.assertEqual(document["content"]["overnight_overlay"]["status"], "risk_off")
            self.assertEqual(len(document["content"]["overnight_overlay"]["unavailable"]), 1)
            self.assertEqual(document["product_mode"], "observation")
            self.assertEqual(document["model_versions"], {})
            self.assertIsNone(document["backtest_as_of"])
            self.assertEqual(
                document["prediction_capability"],
                base["metadata"]["prediction_capability"],
            )
            self.assertEqual(document["title"], "ABSORB 盤前風險更新")
            self.assertNotIn("pdf_path", document)
            self.assertEqual(result["status"], "completed")

    def test_all_unavailable_is_insufficient_and_rerun_does_not_duplicate_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            pipeline = PreMarketPipeline(
                Path(temporary),
                applicable_trading_date=datetime.date(2026, 7, 15),
                load_base=base_receipt,
                source_loaders=[lambda: None],
                publish=lambda metadata: calls.append("publish") or {"content_sha256": "b" * 64},
                notify=lambda receipt: calls.append("notify") or {"sent": True},
            )
            first = pipeline.run(now=datetime.datetime(2026, 7, 15, 0, tzinfo=UTC))
            second = pipeline.run(now=datetime.datetime(2026, 7, 15, 0, 5, tzinfo=UTC))

            overlay = first["outputs"]["metadata"]["content"]["overnight_overlay"]
            self.assertEqual(overlay["status"], "insufficient")
            self.assertEqual(overlay["message"], "資料不足，維持盤後觀察")
            self.assertEqual(calls, ["publish", "notify"])
            self.assertEqual(second["status"], "completed")


if __name__ == "__main__":
    unittest.main()
