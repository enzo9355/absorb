import datetime
import hashlib
import json
import unittest
from unittest.mock import patch

from stock_papi.repositories.dashboard_snapshots import load_dashboard_snapshot


class DashboardSnapshotRepositoryTests(unittest.TestCase):
    def test_latest_dashboard_cache_expires_after_30_seconds(self):
        cache = {"latest": ({"cached": True}, 100)}
        times = iter((129.9, 130.0))
        with patch(
            "stock_papi.repositories.dashboard_snapshots.time.time",
            side_effect=lambda: next(times),
        ):
            fresh_enough = load_dashboard_snapshot(
                load_object=lambda _name, _limit: None, cache=cache
            )
            expired = load_dashboard_snapshot(
                load_object=lambda _name, _limit: None, cache=cache
            )

        self.assertEqual(fresh_enough, {"cached": True})
        self.assertIsNone(expired)

    def test_reads_only_hash_verified_dashboard_object(self):
        document = {
            "schema_version": 2,
            "kind": "absorb-observation-dashboard",
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-07-15",
            "generated_at": "2026-07-16T06:35:08Z",
            "source_manifest": (
                "quant/v1/manifests/TW-20260716T063508Z-aaaaaaaaaaaa.json"
            ),
            "source_manifest_sha256": "a" * 64,
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "market_observation": {},
            "industry_observations": [],
            "heatmap": [],
            "daily_focus": [],
            "stock_events": [],
            "etf_observations": [],
            "data_quality": {},
            "gates": {},
        }
        content = json.dumps(document, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest()
        latest = json.dumps({
            "schema_version": 2,
            "kind": "absorb-observation-dashboard",
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-07-15",
            "generated_at": "2026-07-16T06:35:08Z",
            "source_manifest": (
                "quant/v1/manifests/TW-20260716T063508Z-aaaaaaaaaaaa.json"
            ),
            "source_manifest_sha256": "a" * 64,
            "path": f"objects/{digest}.json",
            "sha256": digest,
            "size": len(content),
        }).encode()
        objects = {
            "dashboard/v1/latest-TW.json": latest,
            f"dashboard/v1/objects/{digest}.json": content,
        }
        result = load_dashboard_snapshot(
            today=datetime.date(2026, 7, 16),
            load_object=lambda name, _limit: objects.get(name),
            cache={},
        )
        self.assertEqual(result["observation_as_of"], "2026-07-15")

    def test_rejects_prediction_fields_even_when_hash_matches(self):
        document = {
            "schema_version": 2,
            "kind": "absorb-observation-dashboard",
            "product_mode": "observation",
            "market": "TW",
            "observation_as_of": "2026-07-15",
            "prediction_capability": {},
            "market_observation": {"probability": 99},
            "industry_observations": [],
            "heatmap": [],
            "daily_focus": [],
            "stock_events": [],
            "etf_observations": [],
            "data_quality": {},
            "gates": {},
        }
        content = json.dumps(document, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest()
        objects = {
            "dashboard/v1/latest-TW.json": json.dumps(
                {
                    "schema_version": 2,
                    "kind": "absorb-observation-dashboard",
                    "product_mode": "observation",
                    "market": "TW",
                    "observation_as_of": "2026-07-15",
                    "path": f"objects/{digest}.json",
                    "sha256": digest,
                    "size": len(content),
                }
            ).encode(),
            f"dashboard/v1/objects/{digest}.json": content,
        }

        self.assertIsNone(
            load_dashboard_snapshot(
                today=datetime.date(2026, 7, 16),
                load_object=lambda name, _limit: objects.get(name),
                cache={},
            )
        )


if __name__ == "__main__":
    unittest.main()
