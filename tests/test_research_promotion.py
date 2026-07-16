from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stock_papi.research.promotion import (
    decide_promotion,
    write_promotion_artifacts,
)


def evaluation():
    return {
        "schema_version": 1,
        "kind": "absorb-research-evaluation",
        "dataset_manifest_sha256": "a" * 64,
        "dataset": {
            "row_count": 10000,
            "symbol_count": 100,
        },
        "models": {
            "constant_prior": {
                "status": "RUN",
                "final_holdout": {
                    "classification": {
                        "brier": 0.25,
                        "log_loss": 0.693,
                        "roc_auc": 0.5,
                        "ece_10": 0.02,
                    }
                },
            },
            "direction_lightgbm": {
                "status": "RUN",
                "final_holdout": {
                    "classification": {
                        "brier": 0.22,
                        "log_loss": 0.64,
                        "roc_auc": 0.58,
                        "ece_10": 0.03,
                        "calibration_slope": 0.95,
                        "calibration_intercept": 0.02,
                    },
                    "ranking": {
                        "spearman_ic": 0.04,
                        "top_decile_spread": 0.02,
                        "turnover": 0.45,
                    },
                    "transaction": {
                        "net_return_after_base_cost": 0.01,
                    },
                    "stability": {
                        "bootstrap_ci": {
                            "top_decile_net_return": {
                                "lower": 0.001,
                                "upper": 0.02,
                            }
                        }
                    },
                },
            },
            "ranking_lightgbm": {
                "status": "NOT_RUN",
                "reason": "PIT universe unavailable",
            },
        },
    }


class ResearchPromotionTests(unittest.TestCase):
    def test_missing_pit_dependency_blocks_candidate_and_latest_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decision = decide_promotion(
                evaluation(),
                {
                    "formal_pit_status": "BLOCKED",
                    "formal_pit_blockers": ["tradable_universe"],
                },
            )
            result = write_promotion_artifacts(root, evaluation(), decision)

            self.assertEqual(decision["overall"], "BLOCKED")
            self.assertIsNone(result["candidate_path"])
            self.assertIsNone(result["preview_receipt_path"])
            self.assertTrue(Path(result["decision_path"]).is_file())
            self.assertFalse(any(root.rglob("latest*.json")))

    def test_all_probability_gates_only_create_immutable_candidate_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = evaluation()
            decision = decide_promotion(
                source,
                {
                    "formal_pit_status": "PASS",
                    "formal_pit_blockers": [],
                },
            )
            result = write_promotion_artifacts(root, source, decision)

            self.assertEqual(decision["overall"], "PASS")
            candidate = json.loads(
                Path(result["candidate_path"]).read_text(encoding="utf-8")
            )
            preview = json.loads(
                Path(result["preview_receipt_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(candidate["mode"], "validated_preview")
            self.assertEqual(preview["traffic_percent"], 0)
            self.assertFalse(any(root.rglob("latest*.json")))

            repeated = write_promotion_artifacts(root, source, decision)
            self.assertEqual(repeated, result)
            Path(result["candidate_path"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable"):
                write_promotion_artifacts(root, source, decision)


if __name__ == "__main__":
    unittest.main()
