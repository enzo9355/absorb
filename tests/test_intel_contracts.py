import unittest

from stock_papi.intel.contracts import select_event_versions, validate_event
from stock_papi.intel.identity import resolve_instrument


UTC = "2026-09-23T21:43:00Z"


def filing_event(**overrides):
    event = {
        "event_id": "event-1",
        "event_version_id": "version-1",
        "source_document_id": "accession-1",
        "source_row_id": "accession-1:nonDerivativeTransaction:0",
        "source_id": "sec-form4",
        "event_date": "2026-09-21",
        "event_time_precision": "date",
        "instrument_id": "instrument-common",
        "source_public_date": "2026-09-23",
        "source_time_precision": "timestamp",
        "source_timezone": "America/New_York",
        "source_published_at": "2026-09-23T21:30:00Z",
        "source_public_time_upper_bound": "2026-09-23T21:30:00Z",
        "first_seen_at": "2026-09-23T21:36:00Z",
        "validated_at": "2026-09-23T21:42:00Z",
        "recorded_at": UTC,
        "required_mapping_known_at": "2026-09-23T21:40:00Z",
        "required_relationship_or_review_known_at": None,
        "supersedes_version_id": None,
        "revision_kind": "original",
        "linkage_status": "not_applicable",
        "mapping_status": "resolved",
        "extraction_status": "parsed",
        "review_status": "verified",
        "aggregation_eligibility": True,
        "schema_version": 1,
        "parser_version": "test-v1",
        "mapping_version": "master-v1",
        "classification_version": "class-v1",
        "raw_value": {},
        "normalized_payload": {},
    }
    event.update(overrides)
    return event


def version(event_id, version_id, available_at, **overrides):
    value = {
        "event_id": event_id,
        "event_version_id": version_id,
        "available_at": available_at,
        "linkage_status": "linked",
        "aggregation_eligibility": True,
    }
    value.update(overrides)
    return value


class IntelContractTests(unittest.TestCase):
    def test_t01_available_at_is_latest_required_timestamp_and_cutoff_is_inclusive(self):
        event = validate_event(filing_event())

        self.assertEqual(event["available_at"], UTC)
        self.assertEqual(
            select_event_versions([event], [], "2026-09-23T21:42:00Z", "actual_system"),
            [],
        )
        self.assertEqual(
            [row["event_version_id"] for row in select_event_versions(
                [event], [], UTC, "actual_system"
            )],
            ["version-1"],
        )

    def test_t02_date_only_public_time_uses_next_local_midnight_as_utc_upper_bound(self):
        event = filing_event(
            source_time_precision="date",
            source_published_at=None,
            source_public_time_upper_bound=None,
            first_seen_at="2026-09-24T01:00:00Z",
            validated_at="2026-09-24T02:00:00Z",
            recorded_at="2026-09-24T02:30:00Z",
        )

        validated = validate_event(event)

        self.assertEqual(validated["source_public_time_upper_bound"], "2026-09-24T04:00:00Z")
        self.assertEqual(validated["available_at"], "2026-09-24T04:00:00Z")

    def test_t03_backfill_is_not_actual_system_history_or_reconstructed_without_evidence(self):
        late = version(
            "old-event", "old-v1", "2026-09-23T21:43:00Z",
            event_date="2020-01-02",
            research_available_at="2020-01-03T00:00:00Z",
        )

        self.assertEqual(
            select_event_versions([late], [], "2020-02-01T00:00:00Z", "actual_system"),
            [],
        )
        self.assertEqual(
            select_event_versions([late], [], "2020-02-01T00:00:00Z", "reconstructed_public"),
            [],
        )
        eligible = dict(late, reconstruction_evidence={
            "status": "verified",
            "latency_policy_version": "latency-v1",
            "source_history_complete": True,
            "public_time_complete": True,
            "revision_history_complete": True,
            "mapping_history_complete": True,
            "universe_history_complete": True,
        })
        self.assertEqual(
            [row["event_version_id"] for row in select_event_versions(
                [eligible], [], "2020-02-01T00:00:00Z", "reconstructed_public"
            )],
            ["old-v1"],
        )

    def test_t04_mapping_must_be_known_by_cutoff_as_well_as_effective_on_event_date(self):
        master = [{
            "record_version_id": "mapping-v1",
            "instrument_id": "instrument-common",
            "issuer_cik": "0000320193",
            "security_title": "Common Stock",
            "asset_type": "COMMON_EQUITY",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "known_from": "2026-09-24T00:00:00Z",
            "supersedes_version_id": None,
            "source_ref": "master-source-1",
        }]

        result = resolve_instrument(
            master, "320193", "Common Stock", "2026-09-23", "2026-09-23T23:00:00Z"
        )

        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["instrument_id"])

    def test_resolver_requires_exact_security_title_and_returns_versioned_common_equity(self):
        master = [{
            "record_version_id": "mapping-v1",
            "instrument_id": "instrument-common",
            "issuer_cik": "0000320193",
            "security_title": "Common Stock",
            "asset_type": "COMMON_EQUITY",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "known_from": "2026-09-20T00:00:00Z",
            "supersedes_version_id": None,
            "source_ref": "master-source-1",
        }]

        resolved = resolve_instrument(
            master, "320193", " common   stock ", "2026-09-23", UTC
        )
        title_mismatch = resolve_instrument(
            master, "320193", "Class A Common Stock", "2026-09-23", UTC
        )

        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["instrument_id"], "instrument-common")
        self.assertEqual(title_mismatch["status"], "unresolved")

    def test_ambiguous_security_mapping_is_not_guessed(self):
        common = {
            "record_version_id": "mapping-a",
            "instrument_id": "instrument-a",
            "issuer_cik": "0000320193",
            "security_title": "Common Stock",
            "asset_type": "COMMON_EQUITY",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "known_from": "2026-09-20T00:00:00Z",
            "supersedes_version_id": None,
            "source_ref": "source-a",
        }
        duplicate_class = dict(
            common,
            record_version_id="mapping-b",
            instrument_id="instrument-b",
            source_ref="source-b",
        )

        result = resolve_instrument(
            [common, duplicate_class], "320193", "Common Stock", "2026-09-23", UTC
        )

        self.assertEqual(result["status"], "ambiguous_mapping")
        self.assertIsNone(result["instrument_id"])

    def test_t05_selects_only_revision_available_at_each_cutoff(self):
        original = version("event-1", "v1", "2026-09-23T21:43:00Z")
        amended = version(
            "event-1", "v2", "2026-09-25T15:00:00Z",
            supersedes_version_id="v1",
        )
        links = [{
            "from_event_version_id": "v1",
            "to_event_version_id": "v2",
            "known_at": "2026-09-25T15:00:00Z",
            "linkage_status": "verified",
        }]

        thursday = select_event_versions(
            [original, amended], links, "2026-09-24T23:59:59Z", "actual_system"
        )
        friday = select_event_versions(
            [original, amended], links, "2026-09-26T00:00:00Z", "actual_system"
        )

        self.assertEqual([row["event_version_id"] for row in thursday], ["v1"])
        self.assertEqual([row["event_version_id"] for row in friday], ["v2"])

    def test_amendment_waits_for_revision_link_knowledge(self):
        original = version("event-1", "v1", "2026-09-23T21:43:00Z")
        amended = version(
            "event-1", "v2", "2026-09-24T18:00:00Z",
            supersedes_version_id="v1",
        )
        link = [{
            "from_event_version_id": "v1",
            "to_event_version_id": "v2",
            "known_at": "2026-09-25T15:00:00Z",
            "linkage_status": "verified",
        }]

        selected = select_event_versions(
            [original, amended], link, "2026-09-25T00:00:00Z", "actual_system"
        )

        self.assertEqual({row["event_version_id"] for row in selected}, {"v1", "v2"})
        self.assertTrue(all(row["linkage_status"] == "unresolved" for row in selected))
        self.assertTrue(all(row["aggregation_eligibility"] is False for row in selected))

    def test_e04_ambiguous_amendment_does_not_choose_a_superseded_row(self):
        original_a = version("event-a", "a-v1", "2026-09-23T21:00:00Z")
        original_b = version("event-b", "b-v1", "2026-09-23T21:00:00Z")
        amendment = version("event-amend", "amend-v1", "2026-09-25T15:00:00Z")
        links = [
            {"from_event_version_id": "a-v1", "to_event_version_id": "amend-v1",
             "known_at": "2026-09-25T15:00:00Z", "linkage_status": "candidate"},
            {"from_event_version_id": "b-v1", "to_event_version_id": "amend-v1",
             "known_at": "2026-09-25T15:00:00Z", "linkage_status": "candidate"},
        ]

        selected = select_event_versions(
            [original_a, original_b, amendment], links,
            "2026-09-26T00:00:00Z", "actual_system",
        )

        self.assertEqual(
            {row["event_version_id"] for row in selected}, {"a-v1", "b-v1", "amend-v1"}
        )
        self.assertTrue(all(row["linkage_status"] == "unresolved" for row in selected))
        self.assertTrue(all(row["aggregation_eligibility"] is False for row in selected))

    def test_unverified_same_event_revision_keeps_versions_but_blocks_aggregation(self):
        original = version("event-1", "v1", "2026-09-23T21:43:00Z")
        amendment = version(
            "event-1", "v2", "2026-09-25T15:00:00Z",
            supersedes_version_id="v1", linkage_status="candidate",
        )

        selected = select_event_versions(
            [original, amendment], [], "2026-09-26T00:00:00Z", "actual_system"
        )

        self.assertEqual({row["event_version_id"] for row in selected}, {"v1", "v2"})
        self.assertTrue(all(row["linkage_status"] == "unresolved" for row in selected))
        self.assertTrue(all(row["aggregation_eligibility"] is False for row in selected))

    def test_naive_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_event(filing_event(recorded_at="2026-09-23T21:43:00"))


if __name__ == "__main__":
    unittest.main()
