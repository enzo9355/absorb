"""Tests for US market date semantics across PostClose, PreMarket, weekends, and holidays."""

import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from stock_papi.batch.calendar import TradingCalendarSet
from stock_papi.batch.us_official_post_close_cli import run_us_post_close
from stock_papi.batch.us_pre_market_cli import run_us_pre_market
from stock_papi.integrations.market_data.us_calendar import (
    get_us_calendar_documents,
    get_us_exchange_holidays,
)
from stock_papi.integrations.market_data.us_universe import USUniverseBreakdown


class TestUSDateSemantics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.status_patch = patch(
            "stock_papi.batch.us_official_post_close_cli.get_us_trading_status_snapshot",
            return_value={},
        )
        self.status_patch.start()
        self.addCleanup(self.status_patch.stop)
        cal_docs = get_us_calendar_documents(2026, 2026)
        self.calendars = TradingCalendarSet.from_documents(cal_docs)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_valid_df(self, symbol="AAPL", date=None):
        date = date or datetime.date(2026, 8, 19)
        dates = [d.date() for d in pd.date_range(end=date, periods=30, freq="B")]
        df = pd.DataFrame(
            {
                "Open": [150.0] * len(dates),
                "High": [155.0] * len(dates),
                "Low": [149.0] * len(dates),
                "Close": [152.0] * len(dates),
                "Volume": [1000000.0] * len(dates),
                "MA5": [152.0] * len(dates),
                "MA20": [152.0] * len(dates),
                "MA60": [152.0] * len(dates),
                "VOL_RATIO": [1.0] * len(dates),
                "RSI": [50.0] * len(dates),
                "MACD": [0.0] * len(dates),
                "MACD_SIGNAL": [0.0] * len(dates),
                "MACD_OSC": [0.0] * len(dates),
                "K": [50.0] * len(dates),
                "D": [50.0] * len(dates),
            },
            index=dates,
        )
        df.index.name = "Date"
        return df

    def test_post_close_and_pre_market_date_flow(self):
        """PostClose on Wednesday 2026-08-19 has applicable_trading_date 2026-08-20.
        PreMarket on Thursday 2026-08-20 binds source 2026-08-19 and applicable 2026-08-20."""
        wednesday = datetime.date(2026, 8, 19)
        thursday = datetime.date(2026, 8, 20)

        self.assertEqual(self.calendars.next_session(wednesday), thursday)

        symbols = ["AAPL", "MSFT"]
        breakdown = USUniverseBreakdown(
            configured_listed_count=2,
            eligible_listed_count=2,
            active_universe_count=2,
            excluded_exchange_count=0,
            excluded_crypto_count=0,
            excluded_invalid_count=0,
            excluded_derivative_count=0,
            derivative_breakdown={},
            terminated_delisted_count=0,
            exchange_counts={"NASDAQ": 2},
            symbols=symbols,
            exclusions_by_symbol={},
        )

        with patch("stock_papi.batch.us_official_post_close_cli.get_us_universe_breakdown", return_value=breakdown),              patch("stock_papi.batch.us_official_post_close_cli.fetch_us_stock_history", side_effect=lambda s, target_market_date=None, mock_df=None: self._make_valid_df(s, target_market_date)):
            # 1. Run PostClose on Wednesday
            post_close_promoted = run_us_post_close(self.root, wednesday)
            self.assertIsNotNone(post_close_promoted)

            # Check post-close report metadata
            latest_pc = json.loads((self.root / "publish" / "reports" / "v2" / "latest-US-post_close.json").read_text(encoding="utf-8"))
            pc_meta = json.loads((self.root / "publish" / "reports" / "v2" / latest_pc["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(pc_meta["source_market_date"], "2026-08-19")
            self.assertEqual(pc_meta["applicable_trading_date"], "2026-08-20")

            # 2. Run PreMarket for Thursday
            pre_market_promoted = run_us_pre_market(self.root, thursday)
            self.assertIsNotNone(pre_market_promoted)

            latest_pm = json.loads((self.root / "publish" / "reports" / "v2" / "latest-US-pre_market.json").read_text(encoding="utf-8"))
            pm_meta = json.loads((self.root / "publish" / "reports" / "v2" / latest_pm["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(pm_meta["source_market_date"], "2026-08-19")
            self.assertEqual(pm_meta["applicable_trading_date"], "2026-08-20")

    def _publish_post_close(self, target_market_date):
        symbols = ["AAPL", "MSFT"]
        breakdown = USUniverseBreakdown(
            configured_listed_count=2,
            eligible_listed_count=2,
            active_universe_count=2,
            excluded_exchange_count=0,
            excluded_crypto_count=0,
            excluded_invalid_count=0,
            excluded_derivative_count=0,
            derivative_breakdown={},
            terminated_delisted_count=0,
            exchange_counts={"NASDAQ": 2},
            symbols=symbols,
            exclusions_by_symbol={},
        )
        with patch(
            "stock_papi.batch.us_official_post_close_cli.get_us_universe_breakdown",
            return_value=breakdown,
        ), patch(
            "stock_papi.batch.us_official_post_close_cli.fetch_us_stock_history",
            side_effect=lambda s, target_market_date=None, mock_df=None: self._make_valid_df(
                s, target_market_date
            ),
        ):
            return run_us_post_close(self.root, target_market_date)

    def test_pre_market_rejects_base_applying_to_another_session(self):
        """PostClose on 2026-09-04 applies to 2026-09-08 (Labor Day gap).

        A pre-market run for 2026-09-09 must fail closed rather than bind that
        base: the report route requires the base post-close to share the
        pre-market applicable_trading_date, so publishing it can only produce a
        report that is permanently unservable."""
        friday = datetime.date(2026, 9, 4)
        tuesday = datetime.date(2026, 9, 8)
        wednesday = datetime.date(2026, 9, 9)

        self.assertEqual(self.calendars.next_session(friday), tuesday)
        self.assertTrue(self.calendars.is_session(wednesday))
        self.assertIsNotNone(self._publish_post_close(friday))

        with self.assertRaises(RuntimeError) as ctx:
            run_us_pre_market(self.root, wednesday)
        self.assertIn("2026-09-09", str(ctx.exception))
        self.assertFalse(
            (
                self.root
                / "publish"
                / "reports"
                / "v2"
                / "latest-US-pre_market.json"
            ).exists()
        )

        # The matching session still publishes, so the guard is not a blanket stop.
        self.assertIsNotNone(run_us_pre_market(self.root, tuesday))

    def test_published_pre_market_report_renders(self):
        """The overnight overlay is validated on read, and the report view
        accepts only a verified five-symbol signal or the no-overnight-data
        state. A US pre-market artifact that declares anything else is
        published successfully and then served as 503 forever, so the produced
        artifact is rendered here rather than only inspected as metadata."""
        import app as stock_app

        wednesday = datetime.date(2026, 8, 19)
        thursday = datetime.date(2026, 8, 20)
        self._publish_post_close(wednesday)
        run_us_pre_market(self.root, thursday)

        published = self.root / "publish" / "reports" / "v2"
        objects = {
            f"reports/v2/{path.relative_to(published).as_posix()}": path.read_bytes()
            for path in published.rglob("*")
            if path.is_file()
        }
        with patch.object(
            stock_app,
            "_gcs_get_report_v2_object",
            lambda path, _size: objects.get(path),
            create=True,
        ):
            client = stock_app.app.test_client()
            response = client.get(f"/reports/us/{thursday.isoformat()}/pre-market")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("以下內容僅為前一交易日盤後摘要，不是盤前訊號。", html)

    def test_pre_market_rejects_unbound_post_close_pointer_hash(self):
        """The pointer hash must match the metadata bytes it names."""
        friday = datetime.date(2026, 9, 4)
        tuesday = datetime.date(2026, 9, 8)
        self._publish_post_close(friday)

        pointer_path = (
            self.root / "publish" / "reports" / "v2" / "latest-US-post_close.json"
        )
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["metadata_sha256"] = "f" * 64
        pointer_path.write_text(
            json.dumps(pointer, ensure_ascii=False), encoding="utf-8"
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_us_pre_market(self.root, tuesday)
        self.assertIn("not bound", str(ctx.exception))

    def test_friday_to_monday_session_transition(self):
        """Friday session next_session must resolve to Monday, skipping Saturday and Sunday."""
        friday = datetime.date(2026, 8, 21)
        monday = datetime.date(2026, 8, 24)
        self.assertEqual(self.calendars.next_session(friday), monday)

    def test_holiday_session_transition(self):
        """Day before Labor Day (Friday Sept 4, 2026) -> Tuesday Sept 8, 2026."""
        fri_before_labor = datetime.date(2026, 9, 4)
        tue_after_labor = datetime.date(2026, 9, 8)
        self.assertEqual(self.calendars.next_session(fri_before_labor), tue_after_labor)


if __name__ == "__main__":
    unittest.main()
