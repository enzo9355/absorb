import copy
import datetime as dt
import unittest

from stock_papi.services.company_events import (
    CompanyEventSchemaError,
    build_watchlist_summary,
    split_event_window,
    validate_event_catalog,
)


def _event(
    event_id="event-1",
    *,
    source_id=None,
    symbol="2330",
    name="台積電",
    event_type="法說會",
    published_at="2026-09-16T09:00:00+08:00",
    effective_at="2026-09-18T14:00:00+08:00",
    summary="公司公告已提供日期，時間與內容以官方來源為準。",
    status="confirmed",
    correction_of=None,
):
    source_id = source_id or event_id
    return {
        "id": event_id,
        "source_id": source_id,
        "symbol": symbol,
        "name": name,
        "market": "TW",
        "event_type": event_type,
        "title": "法說會日期公告",
        "summary": summary,
        "published_at": published_at,
        "effective_at": effective_at,
        "period_start": None,
        "period_end": None,
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "source_title": "TWSE OpenAPI 重大訊息",
        "source_publisher": "臺灣證券交易所",
        "source_locator": "t187ap04_L",
        "source_checked_at": "2026-09-17T08:00:00+08:00",
        "source_status": "available",
        "status": status,
        "correction_of": correction_of,
    }


def _catalog(events):
    return {
        "schema_version": 1,
        "catalog_id": "company-events",
        "updated_at": "2026-09-17T08:00:00+08:00",
        "coverage_note": "只收錄具有官方來源與明確日期的事件。",
        "events": events,
    }


class CompanyEventTests(unittest.TestCase):
    def test_validation_deduplicates_same_source_and_preserves_correction(self):
        original = _event(source_id="mops-1")
        duplicate = copy.deepcopy(original)
        duplicate["id"] = "event-duplicate"
        correction = _event(
            "event-2",
            source_id="mops-2",
            effective_at="2026-09-19T14:00:00+08:00",
            status="corrected",
            correction_of="mops-1",
        )

        result = validate_event_catalog(_catalog([original, duplicate, correction]))

        self.assertEqual([item["id"] for item in result["events"]], ["event-1", "event-2"])
        self.assertEqual(result["events"][1]["correction_of"], "mops-1")

    def test_validation_rejects_untrusted_source_and_invalid_date(self):
        document = _catalog([_event()])
        document["events"][0]["source"] = "https://example.com/forged"
        with self.assertRaises(CompanyEventSchemaError):
            validate_event_catalog(document)

        document = _catalog([_event()])
        document["events"][0]["effective_at"] = "2026-09-18"
        with self.assertRaises(CompanyEventSchemaError):
            validate_event_catalog(document)

    def test_window_separates_past_upcoming_and_undated_without_fabricating_today(self):
        events = validate_event_catalog(
            _catalog(
                [
                    _event("past", effective_at="2026-09-01T09:00:00+08:00"),
                    _event("upcoming", effective_at="2026-09-20T09:00:00+08:00"),
                    _event("outside", effective_at="2026-07-01T09:00:00+08:00"),
                    _event("undated", effective_at=None),
                ]
            )
        )["events"]

        result = split_event_window(events, as_of=dt.date(2026, 9, 17))

        self.assertEqual([item["id"] for item in result["past"]], ["past"])
        self.assertEqual([item["id"] for item in result["upcoming"]], ["upcoming"])
        self.assertEqual([item["id"] for item in result["undated"]], ["undated"])
        self.assertEqual(result["as_of"], "2026-09-17")

    def test_watchlist_summary_keeps_all_companies_and_only_matches_symbols(self):
        events = validate_event_catalog(
            _catalog(
                [
                    _event("event-2330", symbol="2330"),
                    _event("event-2454", symbol="2454", name="聯發科"),
                ]
            )
        )["events"]
        observations = {
            "2330": {
                "observation_as_of": "2026-09-16",
                "change_pct": 1.2,
                "volume_ratio": 1.4,
                "risk_events": [],
            }
        }

        result = build_watchlist_summary(
            [{"code": "2330", "name": "台積電"}, {"code": "1101", "name": "台泥"}],
            events,
            observation_for=lambda code: observations.get(code),
            as_of=dt.date(2026, 9, 17),
        )

        self.assertEqual([item["code"] for item in result["all"]], ["2330", "1101"])
        self.assertEqual([item["id"] for item in result["new_events"]], [])
        self.assertEqual(result["all"][0]["observation"]["change_pct"], 1.2)
        self.assertEqual(result["all"][1]["events"], [])

    def test_watchlist_summary_separates_valid_empty_from_uncovered_company(self):
        result = build_watchlist_summary(
            [{"code": "2330", "name": "台積電"}],
            [],
            event_status="empty",
            as_of=dt.date(2026, 9, 17),
        )
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["all"][0]["event_status"], "empty")

        source_snapshot = _event("snapshot", symbol="", name="台股上市公司", effective_at=None, status="source_snapshot")
        result = build_watchlist_summary(
            [{"code": "2330", "name": "台積電"}],
            validate_event_catalog(_catalog([source_snapshot]))["events"],
            as_of=dt.date(2026, 9, 17),
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["all"][0]["event_status"], "not_covered")


if __name__ == "__main__":
    unittest.main()
