import datetime
import unittest
from zoneinfo import ZoneInfo

from stock_papi.intel.explanation import build_facts, render_summary
from stock_papi.intel.features import build_features


CUTOFF = "2026-09-24T21:00:00Z"
MASTER = [{
    "record_version_id": "mapping-v1",
    "instrument_id": "instrument-common",
    "issuer_cik": "0000320193",
    "security_title": "Common Stock",
    "asset_type": "COMMON_EQUITY",
    "effective_from": "2020-01-01",
    "effective_to": None,
    "known_from": "2026-09-20T00:00:00Z",
    "supersedes_version_id": None,
    "source_ref": "synthetic-master-row",
    "sector_benchmark_instrument_id": "sector-technology",
}]
COMPLETE_COVERAGE = {
    "discovery_complete": True,
    "acquisition_complete": True,
    "parsing_complete": True,
    "mapping_complete": True,
    "revision_resolution_complete": True,
    "economic_dedup_complete": True,
}


def event(version_id, *, public_date="2026-09-23", first_seen="2026-09-24T00:00:00Z",
          code="P", acquired_disposed="A", shares="10", price="5", source="filing-1",
          event_date="2026-09-23", owner_group="group-1", available_override=None):
    public_bound = (
            datetime.datetime.combine(
                datetime.date.fromisoformat(public_date) + datetime.timedelta(days=1),
                datetime.time.min,
                ZoneInfo("America/New_York"),
        ).astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )
    return {
        "event_id": source + ":row-0",
        "event_version_id": version_id,
        "source_document_id": source,
        "source_row_id": source + ":row-0",
        "source_id": "synthetic-sec-form4",
        "issuer_cik": "0000320193",
        "event_date": event_date,
        "event_time_precision": "date",
        "instrument_id": "instrument-common",
        "source_public_date": public_date,
        "source_time_precision": "date",
        "source_timezone": "America/New_York",
        "source_public_time_upper_bound": public_bound,
        "first_public_time_upper_bound": public_bound,
        "first_seen_at": first_seen,
        "validated_at": "2026-09-24T03:00:00Z",
        "recorded_at": "2026-09-24T03:30:00Z",
        "required_mapping_known_at": "2026-09-24T01:00:00Z",
        "required_relationship_or_review_known_at": None,
        "available_at": available_override,
        "supersedes_version_id": None,
        "revision_kind": "original",
        "linkage_status": "not_applicable",
        "mapping_status": "resolved",
        "extraction_status": "parsed",
        "review_status": "verified",
        "aggregation_eligibility": True,
        "schema_version": 1,
        "parser_version": "synthetic-parser-v1",
        "mapping_version": "synthetic-master-v1",
        "classification_version": "synthetic-class-v1",
        "table_kind": "non_derivative",
        "row_kind": "transaction",
        "economic_owner_group_id": owner_group,
        "economic_owner_group_status": "verified" if owner_group else "unresolved",
        "raw_value": {"synthetic": True},
        "normalized_payload": {
            "security_title": "Common Stock",
            "transaction_code": code,
            "acquired_disposed": acquired_disposed,
            "shares": shares,
            "price_per_share": price,
            "price_status": "value" if price is not None else "footnote_only",
            "price_currency": "USD" if price is not None else None,
        },
    }


def market_snapshot(*, close_missing_at=None, length=22, latest_volume=2000):
    end = datetime.date(2026, 9, 23)
    bars = []
    for index in range(length):
        day = end - datetime.timedelta(days=(length - index - 1))
        close = 100 + index
        bars.append({
            "Date": day.isoformat(),
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": None if close_missing_at == index else close,
            "Volume": latest_volume if index == length - 1 else 1000,
        })
    return {
        "verified": True,
        "market": "US",
        "symbol": "EXM",
        "as_of": bars[-1]["Date"],
        "available_at": "2026-09-24T20:00:00Z",
        "adjustment_basis": "synthetic-split-dividend-adjusted-v1",
        "calendar_version": "synthetic-us-calendar-v1",
        "manifest_ref": "quant/v1/manifests/synthetic.json",
        "artifact_sha256": "a" * 64,
        "daily": bars,
    }


def built(events=None, *, coverage=None, snapshot=None, cutoff=CUTOFF):
    return build_features(
        events or [],
        {"instruments": {"instrument-common": snapshot or market_snapshot()}},
        MASTER,
        coverage if coverage is not None else COMPLETE_COVERAGE,
        cutoff,
        "actual_system",
    )


def feature(rows, name):
    return next(row for row in rows if row["feature_name"] == name)


class IntelFeatureTests(unittest.TestCase):
    def test_t06_backfilled_old_filings_do_not_create_recent_purchase_cluster(self):
        old_events = [
            event(f"old-v{index}", public_date="2020-01-02", event_date="2020-01-01",
                  first_seen="2026-09-24T00:00:00Z", source=f"old-{index}", owner_group=f"g-{index}")
            for index in range(1, 4)
        ]

        rows = built(old_events)

        self.assertEqual(feature(rows, "disclosed_purchase_count_30d")["value"], 0)
        self.assertEqual(feature(rows, "purchase_cluster_30d")["value"], False)
        self.assertIn("no_event_observed", feature(rows, "disclosed_purchase_count_30d")["reason_codes"])

    def test_c02_complete_zero_and_incomplete_parser_failure_are_distinct(self):
        complete = built([])
        partial = built([], coverage={**COMPLETE_COVERAGE, "parsing_complete": False})

        zero = feature(complete, "disclosed_purchase_count_30d")
        unknown = feature(partial, "disclosed_purchase_count_30d")
        self.assertEqual((zero["value"], zero["status"]), (0, "available"))
        self.assertEqual(unknown["value"], None)
        self.assertEqual(unknown["status"], "partial")
        self.assertIn("schema_error", unknown["reason_codes"])

    def test_purchase_and_sale_facts_keep_their_own_values_in_fixed_summary(self):
        rows = built([
            event("buy-v1", source="buyer-a", shares="100", price="10"),
            event("sale-v1", source="seller-b", code="S", acquired_disposed="D",
                  shares="200", price="20", owner_group="group-b"),
        ])
        facts = build_facts(rows, [
            {"event_version_id": "buy-v1"}, {"event_version_id": "sale-v1"}
        ])
        summary = render_summary(facts, "rules-v1", "template-v1")
        purchase_fact = next(
            fact for fact in facts if fact["feature_name"] == "disclosed_purchase_count_30d"
        )

        self.assertIn("1 筆申報買入揭露", summary["slots"]["purchase_activity"]["text"])
        self.assertIn("1 筆申報賣出揭露", summary["slots"]["sale_activity"]["text"])
        self.assertNotIn("買入 200", str(summary))
        self.assertEqual(summary["slots"]["purchase_activity"]["fact_id"],
                         purchase_fact["fact_id"])

    def test_e03_identical_cross_document_rows_are_not_silently_counted(self):
        rows = built([
            event("duplicate-v1", source="filing-a"),
            event("duplicate-v2", source="filing-b"),
        ])

        count = feature(rows, "disclosed_purchase_count_30d")
        amount = feature(rows, "disclosed_purchase_amount_30d")
        self.assertIsNone(count["value"])
        self.assertIn("ambiguous_economic_duplicate", count["reason_codes"])
        self.assertIsNone(amount["value"])

    def test_e05_unknown_transaction_price_does_not_change_disclosed_count(self):
        rows = built([event("buy-v1", price=None)])

        self.assertEqual(feature(rows, "disclosed_purchase_count_30d")["value"], 1)
        amount = feature(rows, "disclosed_purchase_amount_30d")
        self.assertIsNone(amount["value"])
        self.assertIn("amount_unavailable", amount["reason_codes"])

    def test_m01_missing_bar_stays_null_without_dropping_event_features(self):
        rows = built(
            [event("buy-v1")],
            snapshot=market_snapshot(close_missing_at=16),
        )

        self.assertEqual(feature(rows, "disclosed_purchase_count_30d")["value"], 1)
        ret = feature(rows, "stock_return_5s")
        self.assertIsNone(ret["value"])
        self.assertIn("insufficient_history", ret["reason_codes"])

    def test_market_ratios_use_prior_sessions_and_fixed_adjustment_basis(self):
        rows = built([])

        self.assertAlmostEqual(feature(rows, "stock_return_5s")["value"], 121 / 116 - 1)
        self.assertAlmostEqual(feature(rows, "stock_return_20s")["value"], 121 / 101 - 1)
        self.assertEqual(feature(rows, "volume_ratio_20s")["value"], 2)
        self.assertEqual(feature(rows, "price_breakout_state")["value"], "above_prior_high")
        self.assertAlmostEqual(feature(rows, "drawdown_from_20s_high")["value"], 121 / 122 - 1)


if __name__ == "__main__":
    unittest.main()
