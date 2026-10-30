import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


from stock_papi.batch.calendar import CalendarError, TradingCalendarSet


def calendar_document(year, *, closed=(), special_open=()):
    return {
        "schema_version": 1,
        "market": "TW",
        "year": year,
        "source_url": "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
        "fetched_at": f"{year - 1}-12-01T00:00:00Z",
        "source_sha256": "a" * 64,
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "closed_dates": list(closed),
        "special_open_dates": list(special_open),
    }


class TradingCalendarTests(unittest.TestCase):
    def test_tw_typhoon_closure_does_not_block_october_catchup(self):
        from stock_papi.integrations.market_data.tw_calendar import get_tw_calendar_documents
        from stock_papi.batch.tw_official_post_close_cli import _required_trading_dates

        calendars = TradingCalendarSet.from_documents(get_tw_calendar_documents(2026, 2026))
        self.assertFalse(calendars.is_session(datetime.date(2026, 10, 23)))
        from stock_papi.web.routes.system import _next_session_for_market
        self.assertEqual(_next_session_for_market("TW", datetime.date(2026, 10, 22)), datetime.date(2026, 10, 27))
        self.assertEqual(calendars.next_session(datetime.date(2026, 10, 22)), datetime.date(2026, 10, 27))
        self.assertEqual(
            _required_trading_dates(
                calendars,
                earliest_latest_date=datetime.date(2026, 10, 22),
                target_market_date=datetime.date(2026, 10, 29),
            ),
            tuple(datetime.date(2026, 10, day) for day in (27, 28, 29)),
        )

    def test_official_closures_and_special_open_days_override_weekdays(self):
        calendars = TradingCalendarSet.from_documents([
            calendar_document(
                2026,
                closed=("2026-02-16", "2026-02-17"),
                special_open=("2026-02-14",),
            )
        ])

        self.assertTrue(calendars.is_session(datetime.date(2026, 2, 13)))
        self.assertFalse(calendars.is_session(datetime.date(2026, 2, 16)))
        self.assertTrue(calendars.is_session(datetime.date(2026, 2, 14)))
        self.assertFalse(calendars.is_session(datetime.date(2026, 2, 15)))

    def test_missing_year_or_invalid_source_fails_closed(self):
        calendars = TradingCalendarSet.from_documents([calendar_document(2026)])

        with self.assertRaises(CalendarError):
            calendars.is_session(datetime.date(2027, 1, 4))

        invalid = calendar_document(2026)
        invalid["source_url"] = "https://example.com/calendar.json"
        with self.assertRaises(CalendarError):
            TradingCalendarSet.from_documents([invalid])

    def test_next_session_and_five_session_horizon_cross_holiday(self):
        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026, closed=("2026-07-20",))
        ])
        source = datetime.date(2026, 7, 17)

        applicable = calendars.next_session(source)

        self.assertEqual(applicable, datetime.date(2026, 7, 21))
        self.assertEqual(
            calendars.session_offset(applicable, 4),
            datetime.date(2026, 7, 27),
        )

    def test_calendar_rejects_overlapping_or_out_of_year_dates(self):
        overlapping = calendar_document(
            2026,
            closed=("2026-02-16",),
            special_open=("2026-02-16",),
        )
        with self.assertRaises(CalendarError):
            TradingCalendarSet.from_documents([overlapping])

        outside = calendar_document(2026, closed=("2027-01-01",))
        with self.assertRaises(CalendarError):
            TradingCalendarSet.from_documents([outside])

    def test_calendar_accepts_rfc3339_fraction_longer_than_microseconds(self):
        document = calendar_document(2026)
        document["fetched_at"] = "2026-07-15T13:49:37.9260379+00:00"

        calendars = TradingCalendarSet.from_documents([document])

        self.assertTrue(calendars.is_session(datetime.date(2026, 7, 15)))

    def test_latest_session_on_or_before_walks_back_weekends_and_holidays(self):
        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026, closed=("2026-07-20",))
        ])

        self.assertEqual(
            calendars.latest_session_on_or_before(datetime.date(2026, 7, 20)),
            datetime.date(2026, 7, 17),
        )
        self.assertEqual(
            calendars.latest_session_on_or_before(datetime.date(2026, 7, 21)),
            datetime.date(2026, 7, 21),
        )
        self.assertEqual(
            calendars.latest_session_on_or_before(datetime.date(2026, 7, 19)),
            datetime.date(2026, 7, 17),
        )

    def test_latest_session_on_or_before_fails_closed_without_session_in_bounds(self):
        closed = tuple(f"2026-01-{day:02d}" for day in range(1, 32))
        calendars = TradingCalendarSet.from_documents([
            calendar_document(2026, closed=closed)
        ])

        with self.assertRaises(CalendarError):
            calendars.latest_session_on_or_before(datetime.date(2026, 1, 31))


ROOT = Path(__file__).resolve().parents[1]


class CalendarLatestSessionCliTests(unittest.TestCase):
    def test_cli_derives_latest_completed_session_from_calendar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = calendar_document(2026, closed=("2026-07-20",))
            artifact = root / "TW-2026.json"
            artifact.write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(ROOT), str(ROOT / ".deps")]
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "stock_papi.batch.cli",
                    "calendar-latest-session",
                    "--calendar-artifact",
                    str(artifact),
                    "--before",
                    "2026-07-20",
                ],
                cwd=str(ROOT),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip())
        self.assertEqual(result["before"], "2026-07-20")
        self.assertEqual(result["latest_session"], "2026-07-17")


if __name__ == "__main__":
    unittest.main()

