import hashlib
import json
import unittest

from stock_papi.repositories.dashboard_snapshots import (
    load_preview_dashboard_snapshot,
)


class PreviewDashboardRepositoryTests(unittest.TestCase):
    def test_preview_manifest_hash_is_required(self):
        dashboard = {
            "schema_version": 1,
            "kind": "absorb-daily-dashboard",
            "baseline_status": "initial_backtest_bootstrap",
            "presentation": {"strong_action_allowed": False},
            "sector_snapshot": {"sectors": {}},
        }
        content = json.dumps(dashboard).encode()
        manifest = {
            "schema_version": 1,
            "kind": "absorb-daily-candidate",
            "files": {
                "dashboard-snapshot.json": {
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            },
        }
        objects = {
            "previews/demo/candidate.json": json.dumps(manifest).encode(),
            "previews/demo/dashboard-snapshot.json": content,
        }
        loaded = load_preview_dashboard_snapshot(
            "previews/demo",
            load_object=lambda name, _maximum: objects.get(name),
            cache={},
        )
        self.assertEqual(loaded["baseline_status"], "initial_backtest_bootstrap")

        objects["previews/demo/dashboard-snapshot.json"] = content + b"x"
        self.assertIsNone(
            load_preview_dashboard_snapshot(
                "previews/demo",
                load_object=lambda name, _maximum: objects.get(name),
                cache={},
            )
        )


if __name__ == "__main__":
    unittest.main()
