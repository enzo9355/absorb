import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.report_fixtures import stock_document, write_quant_publish
from tests.test_batch_calendar import calendar_document


class ObservationProductsCliTests(unittest.TestCase):
    def setUp(self):
        fetch = patch("stock_papi.services.institutional_flows.fetch_twse_flows", side_effect=ValueError("offline test"))
        fetch.start()
        self.addCleanup(fetch.stop)

    def test_build_rejects_validation_date_that_does_not_match_source_date(self):
        from stock_papi.batch.observation_products_cli import main

        arguments = [
            "build",
            "--source-market-date",
            "2026-08-07",
            "--source-validation-date",
            "2026-08-06",
            "--source-manifest",
            "quant/v1/manifests/TW-20260807T000000Z-aaaaaaaaaaaa.json",
            "--source-manifest-sha256",
            "a" * 64,
            "--calendar-artifact",
            "calendar.json",
        ]
        with patch(
            "stock_papi.batch.observation_products_cli.build"
        ) as build, self.assertRaisesRegex(
            ValueError, "must equal source market date"
        ):
            main(arguments, today=datetime.date(2026, 8, 15))
        build.assert_not_called()

    def test_build_rejects_validation_date_from_the_future(self):
        from stock_papi.batch.observation_products_cli import main

        arguments = [
            "build",
            "--source-market-date",
            "2026-08-16",
            "--source-validation-date",
            "2026-08-16",
            "--source-manifest",
            "quant/v1/manifests/TW-20260816T000000Z-aaaaaaaaaaaa.json",
            "--source-manifest-sha256",
            "a" * 64,
            "--calendar-artifact",
            "calendar.json",
        ]
        with patch(
            "stock_papi.batch.observation_products_cli.build"
        ) as build, self.assertRaisesRegex(
            ValueError, "cannot be in the future"
        ):
            main(arguments, today=datetime.date(2026, 8, 15))
        build.assert_not_called()

    def test_build_without_validation_override_keeps_freshness_gate(self):
        from stock_papi.batch.observation_products_cli import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = stock_document("2330", as_of="2026-08-07")
            document.update(name="台積電", sample_data=False)
            publish = write_quant_publish(root, [document])
            latest = json.loads(
                (publish / "latest-TW.json").read_text(encoding="utf-8")
            )
            calendar = root / "calendar.json"
            calendar.write_text(
                json.dumps(calendar_document(2026)), encoding="utf-8"
            )

            with patch(
                "reporting.cli._load_industry_map",
                return_value={"全市場": ["2330"], "半導體": ["2330"]},
            ), self.assertRaisesRegex(ValueError, "stale"):
                main(
                    [
                        "build",
                        "--root",
                        str(root),
                        "--source-market-date",
                        "2026-08-07",
                        "--source-manifest",
                        f"quant/v1/{latest['manifest']}",
                        "--source-manifest-sha256",
                        latest["manifest_sha256"],
                        "--calendar-artifact",
                        str(calendar),
                    ],
                    today=datetime.date(2026, 8, 15),
                )

    def test_build_accepts_explicit_source_validation_date_for_historical_runs(self):
        from stock_papi.batch.observation_products_cli import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = stock_document("2330", as_of="2026-08-07")
            document.update(name="台積電", sample_data=False)
            publish = write_quant_publish(root, [document])
            latest = json.loads(
                (publish / "latest-TW.json").read_text(encoding="utf-8")
            )
            calendar = root / "calendar.json"
            calendar.write_text(
                json.dumps(calendar_document(2026)), encoding="utf-8"
            )
            output = []
            with patch(
                "reporting.cli._load_industry_map",
                return_value={"全市場": ["2330"], "半導體": ["2330"]},
            ), patch("builtins.print", side_effect=output.append):
                exit_code = main(
                    [
                        "build",
                        "--root",
                        str(root),
                        "--source-market-date",
                        "2026-08-07",
                        "--source-validation-date",
                        "2026-08-07",
                        "--source-manifest",
                        f"quant/v1/{latest['manifest']}",
                        "--source-manifest-sha256",
                        latest["manifest_sha256"],
                        "--calendar-artifact",
                        str(calendar),
                    ]
                )

            receipt = json.loads(output[-1])
            self.assertEqual(exit_code, 0)
            self.assertEqual(receipt["observation_as_of"], "2026-08-07")

    def test_build_and_promote_use_explicit_verified_source_without_model_gate(self):
        from stock_papi.batch.observation_products_cli import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = stock_document("2330", as_of="2026-07-16")
            document.update(name="台積電", sample_data=False)
            publish = write_quant_publish(root, [document])
            latest = json.loads(
                (publish / "latest-TW.json").read_text(encoding="utf-8")
            )
            calendar = root / "calendar.json"
            calendar.write_text(
                json.dumps(calendar_document(2026)), encoding="utf-8"
            )
            output = []
            with patch(
                "reporting.cli._load_industry_map",
                return_value={"全市場": ["2330"], "半導體": ["2330"]},
            ), patch("builtins.print", side_effect=output.append):
                exit_code = main(
                    [
                        "build",
                        "--root",
                        str(root),
                        "--source-market-date",
                        "2026-07-16",
                        "--source-manifest",
                        f"quant/v1/{latest['manifest']}",
                        "--source-manifest-sha256",
                        latest["manifest_sha256"],
                        "--calendar-artifact",
                        str(calendar),
                    ],
                    today=datetime.date(2026, 7, 23),
                )
            receipt = json.loads(output[-1])

            self.assertEqual(exit_code, 0)
            self.assertEqual(receipt["mode"], "observation-candidate")
            candidate = Path(receipt["candidate_path"])
            self.assertTrue((candidate / "candidate.json").is_file())
            self.assertFalse(
                (root / "publish" / "dashboard" / "v1" / "latest-TW.json").exists()
            )

            output.clear()
            with patch("builtins.print", side_effect=output.append):
                exit_code = main(
                    [
                        "promote",
                        "--root",
                        str(root),
                        "--candidate",
                        str(candidate),
                    ]
                )
            promoted = json.loads(output[-1])
            self.assertEqual(exit_code, 0)
            self.assertEqual(promoted["mode"], "observation-local-promotion")
            self.assertTrue(Path(promoted["dashboard_latest"]).is_file())
            self.assertTrue(Path(promoted["report_latest"]).is_file())

    def test_cli_source_contains_no_model_or_bootstrap_dependency(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "stock_papi"
            / "batch"
            / "observation_products_cli.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "BacktestStore",
            "AI_P",
            "MODEL_VERSION",
            "allow-degraded-bootstrap",
            "recommendation_engine",
            "--today",
            "--ignore-freshness",
            "--allow-stale",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class ObservationProductsCliMarketIndexTests(unittest.TestCase):
    setUp = ObservationProductsCliTests.setUp
    def _fixture(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        document = stock_document("2330", as_of="2026-08-07")
        document.update(name="台積電", sample_data=False)
        publish = write_quant_publish(root, [document])
        latest = json.loads(
            (publish / "latest-TW.json").read_text(encoding="utf-8")
        )
        calendar = root / "calendar.json"
        calendar.write_text(
            json.dumps(calendar_document(2026)), encoding="utf-8"
        )
        return root, latest, calendar

    @staticmethod
    def _taiex_snapshot(as_of):
        previous = as_of - datetime.timedelta(days=1)
        return {
            "symbol": "TAIEX",
            "name": "加權指數",
            "source": "臺灣證券交易所",
            "as_of": as_of.isoformat(),
            "price": 23150.25,
            "change": 188.4,
            "change_pct": 0.82,
            "open": 22982.1,
            "high": 23210.8,
            "low": 22940.6,
            "candles": [
                {
                    "time": previous.isoformat(),
                    "open": 22800.0,
                    "high": 23010.0,
                    "low": 22760.0,
                    "close": 22961.85,
                },
                {
                    "time": as_of.isoformat(),
                    "open": 22982.1,
                    "high": 23210.8,
                    "low": 22940.6,
                    "close": 23150.25,
                },
            ],
            "ma20": [],
            "returns": {"1d": 0.82, "5d": 1.4, "20d": 2.1, "60d": None},
        }

    def _arguments(self, root, latest, calendar, *flags):
        return [
            "build",
            "--root",
            str(root),
            "--source-market-date",
            "2026-08-07",
            "--source-validation-date",
            "2026-08-07",
            "--source-manifest",
            f"quant/v1/{latest['manifest']}",
            "--source-manifest-sha256",
            latest["manifest_sha256"],
            "--calendar-artifact",
            str(calendar),
            *flags,
        ]

    def _run(self, arguments, loader_result=None, loader_error=None):
        from stock_papi.batch.observation_products_cli import main

        output = []
        market_index_loader = (
            patch(
                "stock_papi.services.market_index.fetch_twse_index_snapshot",
                return_value=loader_result,
            )
            if loader_error is None
            else patch(
                "stock_papi.services.market_index.fetch_twse_index_snapshot",
                side_effect=loader_error,
            )
        )
        with patch(
            "reporting.cli._load_industry_map",
            return_value={"全市場": ["2330"], "半導體": ["2330"]},
        ), market_index_loader, patch(
            "builtins.print", side_effect=output.append
        ):
            exit_code = main(arguments, today=datetime.date(2026, 8, 15))
        return exit_code, json.loads(output[-1])

    def test_if_available_includes_a_valid_snapshot(self):
        root, latest, calendar = self._fixture()
        exit_code, receipt = self._run(
            self._arguments(
                root, latest, calendar, "--include-market-index-if-available"
            ),
            loader_result=self._taiex_snapshot(datetime.date(2026, 8, 7)),
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["market_index_status"], "included")
        dashboard = json.loads(
            Path(receipt["dashboard_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(dashboard["market_index"]["symbol"], "TAIEX")

    def test_if_available_none_continues_without_market_index(self):
        root, latest, calendar = self._fixture()
        exit_code, receipt = self._run(
            self._arguments(
                root, latest, calendar, "--include-market-index-if-available"
            ),
            loader_result=None,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["market_index_status"], "unavailable")
        dashboard = json.loads(
            Path(receipt["dashboard_path"]).read_text(encoding="utf-8")
        )
        self.assertNotIn("market_index", dashboard)

    def test_if_available_loader_exception_continues_without_market_index(self):
        root, latest, calendar = self._fixture()
        exit_code, receipt = self._run(
            self._arguments(
                root, latest, calendar, "--include-market-index-if-available"
            ),
            loader_error=RuntimeError("verified TAIEX actuals are unavailable"),
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["market_index_status"], "unavailable")
        dashboard = json.loads(
            Path(receipt["dashboard_path"]).read_text(encoding="utf-8")
        )
        self.assertNotIn("market_index", dashboard)

    def test_include_market_index_stays_fail_closed_when_unavailable(self):
        root, latest, calendar = self._fixture()
        from stock_papi.batch.observation_products_cli import main

        with patch(
            "reporting.cli._load_industry_map",
            return_value={"全市場": ["2330"], "半導體": ["2330"]},
        ), patch(
            "stock_papi.services.market_index.fetch_twse_index_snapshot",
            return_value=None,
        ), self.assertRaisesRegex(
            ValueError, "verified TAIEX actuals are unavailable"
        ):
            main(
                self._arguments(
                    root, latest, calendar, "--include-market-index"
                ),
                today=datetime.date(2026, 8, 15),
            )

    def test_include_market_index_flags_are_mutually_exclusive(self):
        root, latest, calendar = self._fixture()
        from stock_papi.batch.observation_products_cli import main

        with self.assertRaises(SystemExit):
            main(
                self._arguments(
                    root,
                    latest,
                    calendar,
                    "--include-market-index",
                    "--include-market-index-if-available",
                ),
                today=datetime.date(2026, 8, 15),
            )

    def test_no_market_index_flag_reports_not_requested(self):
        root, latest, calendar = self._fixture()
        exit_code, receipt = self._run(
            self._arguments(root, latest, calendar)
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["market_index_status"], "not_requested")
        dashboard = json.loads(
            Path(receipt["dashboard_path"]).read_text(encoding="utf-8")
        )
        self.assertNotIn("market_index", dashboard)


if __name__ == "__main__":
    unittest.main()
