"""由 CI artifact 產生 fail-closed 的發布品質報告與雜湊證據。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backtest.quality_gate import QualityGate


DEFAULT_HASH_TARGETS = (
    "Dockerfile",
    "app.py",
    "local_quant.py",
    "backtest/publish.py",
    "backtest/rollback.py",
    "backtest/quality_gate.py",
    "scripts/upload_local_quant.ps1",
    "scripts/manual_rollback.ps1",
    "scripts/verify_cutover.ps1",
    "scripts/generate_release_report.py",
)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """解析所有必須由 CI 提供的驗證 artifact。"""
    parser = argparse.ArgumentParser(description="產生 Stock Papi 發布品質閘門報告")
    parser.add_argument("--test-result", type=Path, required=True)
    parser.add_argument("--parity-result", type=Path, required=True)
    parser.add_argument("--coverage-result", type=Path, required=True)
    parser.add_argument("--security-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--source-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--hash-target", action="append", dest="hash_targets")
    parser.add_argument("--minimum-coverage", type=float, default=80.0)
    return parser.parse_args(arguments)


def load_json_object(path: Path) -> Mapping[str, object]:
    """只接受 JSON 物件，避免缺失或陣列 artifact 被靜默接受。"""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"無法讀取 JSON artifact：{path}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"artifact 必須為 JSON 物件：{path}")
    return document


def collect_hashes(source_root: Path, targets: Sequence[str]) -> dict[str, str]:
    """僅雜湊 source root 內明確指定的檔案。"""
    resolved_root = source_root.resolve()
    hashes: dict[str, str] = {}
    for target in targets:
        candidate = (resolved_root / target).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"雜湊目標超出 source root：{target}") from exc
        if not candidate.is_file():
            raise ValueError(f"雜湊目標不存在：{target}")
        hashes[candidate.relative_to(resolved_root).as_posix()] = hashlib.sha256(
            candidate.read_bytes()
        ).hexdigest()
    return hashes


def write_text(path: Path, content: str) -> None:
    """建立輸出目錄後一次寫入完整文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main(arguments: Sequence[str] | None = None) -> int:
    """產生報告；Gate 拒收時回傳非零，但仍保留可審核輸出。"""
    args = parse_arguments(arguments)
    gate = QualityGate(minimum_coverage_percent=args.minimum_coverage)
    report = gate.evaluate(
        test_result=load_json_object(args.test_result),
        parity_result=load_json_object(args.parity_result),
        coverage_result=load_json_object(args.coverage_result),
        security_result=load_json_object(args.security_result),
    )
    write_text(args.output, report.to_markdown())

    evidence_path = args.evidence_output or args.output.with_suffix(".json")
    targets = tuple(args.hash_targets or DEFAULT_HASH_TARGETS)
    evidence = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quality_gate": report.status.value,
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in report.checks
        ],
        "source_hashes": collect_hashes(args.source_root, targets),
    }
    write_text(
        evidence_path,
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    )
    print(f"Quality Gate: {report.status.value}")
    print(f"Report: {args.output}")
    print(f"Evidence: {evidence_path}")
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
