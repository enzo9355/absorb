import datetime
import hashlib
import json
import unittest

from stock_papi.intel.explanation import build_facts, render_summary
from stock_papi.intel.publish import (
    promote_information_release,
    record_source_health,
    validate_information_release,
)
from stock_papi.repositories.intel_snapshots import load_intel_snapshot


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def reference(path, content):
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


class FakeStore:
    def __init__(self):
        self.objects = {}
        self.generation = 0

    def load_object(self, path, max_bytes):
        value = self.objects.get(path)
        return value if value is not None and len(value) <= max_bytes else None

    def create_object(self, path, value):
        if path in self.objects:
            return self.objects[path] == value
        self.objects[path] = value
        return True

    def read_pointer(self, path):
        return self.objects.get(path), self.generation

    def compare_and_swap_pointer(self, path, value, expected_generation):
        if self.generation != expected_generation:
            return None
        self.objects[path] = value
        self.generation += 1
        return self.generation


NOW = "2026-09-24T21:00:00Z"
POLICY = {
    "policy_id": "rights-test-only",
    "version": "policy-v1",
    "reviewer": "test reviewer",
    "retention_policy": "test retention",
    "evidence_urls": ["https://example.test/synthetic-only"],
    "reviewed_at": "2026-09-20T00:00:00Z",
    "effective_from": "2026-09-20T00:00:00Z",
    "expires_at": "2026-10-01T00:00:00Z",
    "store_derived": "allowed",
    "display_aggregate": "allowed",
    "store_raw": "unknown",
    "display_raw": "unknown",
    "fetch": "unknown",
    "training": "unknown",
    "inference": "unknown",
    "external_LLM": "denied",
}


def candidate(store, release_id="test-release-1", *, cutoff="2026-09-23T21:00:00Z",
              valid_until="2026-09-25T21:00:00Z", model_mode=None):
    store = store or FakeStore()
    facts_list = build_facts([
        {
            "instrument_id": "instrument-common", "decision_cutoff_at": cutoff,
            "feature_name": name, "status": "unavailable", "value": None,
            "source_event_version_ids": [],
        }
        for name in (
            "disclosed_purchase_count_30d", "disclosed_sale_count_30d",
            "purchase_cluster_30d", "price_breakout_state",
        )
    ], [])
    summary = {
        "schema_version": "intel-api-v1",
        "instrument_id": "instrument-common",
        "release_id": release_id,
        "status": "available",
        "reason_codes": [],
        "summary": render_summary(facts_list, "rules-v1", "template-v1"),
    }
    events = {
        "schema_version": "intel-events-v1",
        "instrument_id": "instrument-common",
        "release_id": release_id,
        "page": 1,
        "page_count": 1,
        "events": [],
    }
    facts = {"schema_version": 1, "instrument_id": "instrument-common", "facts": facts_list}
    gate = {"ok": True, "errors": []}
    objects = {}
    for name, value in (("summary", summary), ("events", events), ("facts", facts), ("gate", gate)):
        content = encoded(value)
        ref = reference(f"intel/v1/objects/{hashlib.sha256(content).hexdigest()}.json", content)
        store.objects[ref["path"]] = content
        objects[name] = ref
    manifest = {
        "schema_version": 1,
        "mode": "information",
        "release_id": release_id,
        "market": "US",
        "generated_at": NOW,
        "decision_cutoff_at": cutoff,
        "valid_until": valid_until,
        "instrument_objects": {"instrument-common": {
            "summary": objects["summary"],
            "events": [objects["events"]],
            "facts": objects["facts"],
        }},
        "rights_policy_versions": ["policy-v1"],
        "coverage_report": {"status": "complete"},
        "gate_report": objects["gate"],
        "gate_report_hash": objects["gate"]["sha256"],
        "code_commit": "synthetic-test-commit",
    }
    if model_mode is not None:
        manifest["model_mode"] = model_mode
    manifest_bytes = encoded(manifest)
    store.objects[f"intel/v1/manifests/{release_id}.json"] = manifest_bytes
    manifest_ref = f"intel/v1/manifests/{release_id}.json"
    store.objects["intel/v1/health-US.json"] = encoded({
        "schema_version": 1, "market": "US", "status": "healthy",
        "checked_as_of": NOW, "valid_until": "2026-09-25T21:00:00Z",
    })
    store.objects["intel/v1/revocations.json"] = encoded({
        "schema_version": 1, "checked_at": NOW, "valid_until": "2026-09-25T21:00:00Z",
        "revoked_release_ids": [], "revoked_object_sha256": [],
    })
    pointer = {
        "schema_version": 1,
        "market": "US",
        "release_id": release_id,
        "manifest_ref": manifest_ref,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_size": len(manifest_bytes),
    }
    return store, manifest, manifest_ref, pointer


def install_current(store, manifest, manifest_ref, pointer):
    manifest_bytes = store.objects[manifest_ref]
    store.objects["intel/v1/latest-US.json"] = encoded(pointer)
    store.generation = 1
    store.objects[f"intel/v1/receipts/{manifest['release_id']}.json"] = encoded({
        "schema_version": 1,
        "release_id": manifest["release_id"],
        "manifest_ref": manifest_ref,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "expected_generation": 0,
        "generation": 1,
        "promoted_at": NOW,
        "status": "promoted",
    })


class IntelPublishTests(unittest.TestCase):
    def test_p01_compare_and_swap_rejects_racing_and_older_publishers(self):
        store, manifest, manifest_ref, _ = candidate(FakeStore())
        first = promote_information_release(store, manifest_ref, 0, now=NOW, policy=POLICY)
        self.assertTrue(first["ok"])
        self.assertEqual(first["generation"], 1)
        repeat = promote_information_release(store, manifest_ref, 0, now=NOW, policy=POLICY)
        self.assertTrue(repeat["ok"])
        self.assertTrue(repeat["idempotent"])

        second_id = "test-release-older"
        _, second_manifest, second_ref, _ = candidate(store, second_id, cutoff="2026-09-22T21:00:00Z")
        store.objects[second_ref] = encoded(second_manifest)
        raced = promote_information_release(store, second_ref, 1, now=NOW, policy=POLICY)
        self.assertFalse(raced["ok"])
        self.assertEqual(raced["reason"], "cutoff_regressed")

    def test_p02_corrupt_referenced_object_blocks_promotion(self):
        store, manifest, manifest_ref, _ = candidate(FakeStore())
        summary_ref = manifest["instrument_objects"]["instrument-common"]["summary"]
        store.objects[summary_ref["path"]] = b"x" * summary_ref["size"]

        report = validate_information_release(manifest, store.load_object, POLICY, now=NOW)

        self.assertFalse(report["ok"])
        self.assertIn("object_hash_mismatch", report["errors"])

    def test_summary_cutoff_must_match_versioned_facts(self):
        store, manifest, manifest_ref, _ = candidate(FakeStore())
        instrument = manifest["instrument_objects"]["instrument-common"]
        ref = instrument["summary"]
        summary = json.loads(store.objects[ref["path"]].decode("utf-8"))
        summary["summary"]["decision_cutoff_at"] = "2026-09-22T21:00:00Z"
        summary_bytes = encoded(summary)
        new_ref = reference(
            f"intel/v1/objects/{hashlib.sha256(summary_bytes).hexdigest()}.json",
            summary_bytes,
        )
        store.objects[new_ref["path"]] = summary_bytes
        instrument["summary"] = new_ref
        store.objects[manifest_ref] = encoded(manifest)

        report = validate_information_release(
            manifest, store.load_object, POLICY, now=NOW
        )

        self.assertFalse(report["ok"])
        self.assertIn("summary_fact_traceability_error", report["errors"])

    def test_s01_shadow_model_artifact_is_rejected_by_information_gate(self):
        store, manifest, _, _ = candidate(FakeStore(), model_mode="shadow")

        report = validate_information_release(manifest, store.load_object, POLICY, now=NOW)

        self.assertFalse(report["ok"])
        self.assertIn("shadow_model_not_allowed", report["errors"])

    def test_reader_rejects_currently_revoked_release_and_does_not_fallback(self):
        store, manifest, manifest_ref, pointer = candidate(FakeStore())
        install_current(store, manifest, manifest_ref, pointer)
        store.objects["intel/v1/revocations.json"] = encoded({
            "schema_version": 1, "checked_at": NOW, "valid_until": "2026-09-25T21:00:00Z",
            "revoked_release_ids": ["test-release-1"], "revoked_object_sha256": [],
        })

        result = load_intel_snapshot(
            "instrument-common", None, NOW, store.load_object, policy=POLICY
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertIn("artifact_revoked", result["reason_codes"])
        self.assertIsNone(result.get("summary"))

    def test_reader_rejects_expired_release_and_expired_health(self):
        expired_store, manifest, manifest_ref, pointer = candidate(
            FakeStore(), valid_until="2026-09-24T20:59:59Z"
        )
        install_current(expired_store, manifest, manifest_ref, pointer)
        expired = load_intel_snapshot(
            "instrument-common", None, NOW, expired_store.load_object, policy=POLICY
        )
        self.assertEqual(expired["status"], "unavailable")
        self.assertIn("source_delay", expired["reason_codes"])

        health_store, manifest, manifest_ref, pointer = candidate(FakeStore())
        install_current(health_store, manifest, manifest_ref, pointer)
        health_store.objects["intel/v1/health-US.json"] = encoded({
            "schema_version": 1, "market": "US", "status": "failed",
            "checked_as_of": NOW, "valid_until": "2026-09-25T21:00:00Z",
        })
        failed = load_intel_snapshot(
            "instrument-common", None, NOW, health_store.load_object, policy=POLICY
        )
        self.assertEqual(failed["status"], "unavailable")
        self.assertIn("source_unavailable", failed["reason_codes"])

    def test_p05_source_failure_health_cas_supersedes_old_healthy_state(self):
        store, manifest, manifest_ref, pointer = candidate(FakeStore())
        install_current(store, manifest, manifest_ref, pointer)
        checked_at = "2026-09-24T21:01:00Z"

        health_report = {
            "schema_version": 1,
            "market": "US",
            "status": "unavailable",
            "checked_at": checked_at,
            "valid_until": "2026-09-25T21:00:00Z",
            "reason_codes": ["source_fetch_failed"],
        }
        result = record_source_health(store, health_report, 1, now=checked_at)

        self.assertTrue(result["ok"])
        retry = record_source_health(store, health_report, 2, now=checked_at)
        self.assertTrue(retry["ok"])
        self.assertTrue(retry["idempotent"])
        snapshot = load_intel_snapshot(
            "instrument-common", None, checked_at, store.load_object, policy=POLICY
        )
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertIn("source_unavailable", snapshot["reason_codes"])
        same_time_healthy = record_source_health(store, {
            "schema_version": 1,
            "market": "US",
            "status": "healthy",
            "checked_at": checked_at,
            "valid_until": "2026-09-25T21:00:00Z",
            "reason_codes": [],
        }, 2, now=checked_at)
        self.assertFalse(same_time_healthy["ok"])
        self.assertEqual(same_time_healthy["reason"], "health_regressed")
        regressed = record_source_health(store, {
            "schema_version": 1,
            "market": "US",
            "status": "healthy",
            "checked_at": "2026-09-24T21:00:59Z",
            "valid_until": "2026-09-25T21:00:00Z",
            "reason_codes": [],
        }, 2, now=checked_at)
        self.assertFalse(regressed["ok"])
        self.assertEqual(regressed["reason"], "health_regressed")

    def test_reader_pins_manifest_and_rechecks_integrity(self):
        store, manifest, manifest_ref, pointer = candidate(FakeStore())
        install_current(store, manifest, manifest_ref, pointer)

        result = load_intel_snapshot(
            "instrument-common", "test-release-1", NOW, store.load_object, policy=POLICY
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["release"]["release_id"], "test-release-1")
        self.assertEqual(result["event_page"]["page_count"], 1)

    def test_pinned_release_stays_pinned_after_latest_pointer_moves(self):
        store, first_manifest, first_ref, first_pointer = candidate(FakeStore())
        install_current(store, first_manifest, first_ref, first_pointer)
        _, _, second_ref, _ = candidate(
            store, "test-release-2", cutoff="2026-09-24T21:00:00Z"
        )
        promoted = promote_information_release(
            store, second_ref, 1, now=NOW, policy=POLICY
        )
        self.assertTrue(promoted["ok"])

        result = load_intel_snapshot(
            "instrument-common", "test-release-1", NOW, store.load_object, policy=POLICY
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["release"]["release_id"], "test-release-1")

    def test_unknown_rights_or_health_never_defaults_to_available(self):
        store, manifest, manifest_ref, pointer = candidate(FakeStore())
        install_current(store, manifest, manifest_ref, pointer)
        denied = {**POLICY, "display_aggregate": "unknown"}
        self.assertFalse(validate_information_release(
            manifest, store.load_object, denied, now=NOW
        )["ok"])

        del store.objects["intel/v1/health-US.json"]
        result = load_intel_snapshot(
            "instrument-common", None, NOW, store.load_object, policy=POLICY
        )
        self.assertEqual(result["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
