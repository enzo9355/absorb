"""Phase 4D 品質閘門與發布報告測試。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backtest.quality_gate import QualityGate, QualityGateStatus


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCRIPT = REPOSITORY_ROOT / "scripts" / "generate_release_report.py"


def accepted_artifacts() -> dict[str, dict[str, object]]:
    """建立完整且通過的 CI artifact。"""
    return {
        "tests": {"passed": True, "exit_code": 0},
        "parity": {"accepted": True, "unexpected_differences": []},
        "coverage": {"passed": True, "percent": 85.0},
        "security": {"passed": True, "findings": []},
    }


class QualityGateTests(unittest.TestCase):
    def test_all_required_artifacts_produce_pass(self) -> None:
        artifacts = accepted_artifacts()

        report = QualityGate(minimum_coverage_percent=80.0).evaluate(
            test_result=artifacts["tests"],
            parity_result=artifacts["parity"],
            coverage_result=artifacts["coverage"],
            security_result=artifacts["security"],
        )

        self.assertEqual(report.status, QualityGateStatus.PASS)
        self.assertIn("**PASS**", report.to_markdown())

    def test_missing_or_rejected_artifact_fails_closed(self) -> None:
        artifacts = accepted_artifacts()
        artifacts["coverage"] = {"passed": True, "percent": 79.0}

        report = QualityGate(minimum_coverage_percent=80.0).evaluate(
            test_result=artifacts["tests"],
            parity_result=artifacts["parity"],
            coverage_result=artifacts["coverage"],
            security_result=None,
        )

        self.assertEqual(report.status, QualityGateStatus.REJECT)
        self.assertFalse(report.accepted)

    def test_report_script_writes_markdown_and_hash_evidence(self) -> None:
        artifacts = accepted_artifacts()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths: dict[str, Path] = {}
            for name, document in artifacts.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                paths[name] = path
            report_path = root / "release.md"
            evidence_path = root / "release-evidence.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPORT_SCRIPT),
                    "--test-result",
                    str(paths["tests"]),
                    "--parity-result",
                    str(paths["parity"]),
                    "--coverage-result",
                    str(paths["coverage"]),
                    "--security-result",
                    str(paths["security"]),
                    "--output",
                    str(report_path),
                    "--evidence-output",
                    str(evidence_path),
                ],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("**PASS**", report_path.read_text(encoding="utf-8"))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["quality_gate"], "PASS")
            self.assertIn("Dockerfile", evidence["source_hashes"])


if __name__ == "__main__":
    unittest.main()
