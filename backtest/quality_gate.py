"""發布前品質閘門：只接受可驗證的 CI、Parity、coverage 與安全 artifact。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping

from .parity_checker import ParityReport


class QualityGateStatus(str, Enum):
    """品質閘門的唯一結論。"""

    PASS = "PASS"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """單一可追溯的發布檢查結果。"""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class QualityGateReport:
    """品質閘門報告，可輸出為 Markdown。"""

    status: QualityGateStatus
    generated_at: datetime
    checks: tuple[QualityCheck, ...]

    @property
    def accepted(self) -> bool:
        return self.status is QualityGateStatus.PASS

    def to_markdown(self) -> str:
        lines = [
            "# Stock Papi 發布品質閘門報告",
            "",
            f"- 結論：**{self.status.value}**",
            f"- 產生時間：{self.generated_at.isoformat()}",
            "",
            "| 檢查項目 | 結果 | 說明 |",
            "| --- | --- | --- |",
        ]
        for check in self.checks:
            result = "PASS" if check.passed else "REJECT"
            lines.append(f"| {check.name} | {result} | {check.detail} |")
        return "\n".join(lines) + "\n"


class QualityGate:
    """將獨立 CI artifact 收斂成 fail-closed 的發布結論。"""

    def __init__(self, *, minimum_coverage_percent: float = 80.0) -> None:
        if not 0.0 <= minimum_coverage_percent <= 100.0:
            raise ValueError("minimum_coverage_percent 必須介於 0 與 100")
        self._minimum_coverage_percent = minimum_coverage_percent

    @staticmethod
    def parity_artifact(report: ParityReport) -> dict[str, object]:
        """將 LegacyParityChecker 的結果轉為可交給 CI 的 JSON artifact。"""
        return {
            "accepted": report.accepted,
            "expected_differences": list(report.expected_differences),
            "unexpected_differences": list(report.unexpected_differences),
        }

    def evaluate(
        self,
        *,
        test_result: Mapping[str, object] | None,
        parity_result: Mapping[str, object] | None,
        coverage_result: Mapping[str, object] | None,
        security_result: Mapping[str, object] | None,
    ) -> QualityGateReport:
        checks = (
            self._check_tests(test_result),
            self._check_parity(parity_result),
            self._check_coverage(coverage_result),
            self._check_security(security_result),
        )
        return QualityGateReport(
            status=(
                QualityGateStatus.PASS
                if all(check.passed for check in checks)
                else QualityGateStatus.REJECT
            ),
            generated_at=datetime.now(timezone.utc),
            checks=checks,
        )

    @staticmethod
    def _check_tests(result: Mapping[str, object] | None) -> QualityCheck:
        if result is None:
            return QualityCheck("CI tests", False, "缺少測試結果 artifact")
        passed = result.get("passed") is True and result.get("exit_code") == 0
        detail = "測試命令成功" if passed else "測試失敗或 exit_code 非零"
        return QualityCheck("CI tests", passed, detail)

    @staticmethod
    def _check_parity(result: Mapping[str, object] | None) -> QualityCheck:
        if result is None:
            return QualityCheck("Legacy parity", False, "缺少 Parity artifact")
        unexpected = result.get("unexpected_differences")
        passed = result.get("accepted") is True and unexpected == []
        detail = "新舊引擎無非預期差異" if passed else "存在非預期差異或 artifact 格式不合法"
        return QualityCheck("Legacy parity", passed, detail)

    def _check_coverage(self, result: Mapping[str, object] | None) -> QualityCheck:
        if result is None:
            return QualityCheck("Test coverage", False, "缺少 coverage artifact")
        percentage = result.get("percent")
        if not isinstance(percentage, (int, float)):
            return QualityCheck("Test coverage", False, "coverage percent 格式不合法")
        passed = bool(result.get("passed")) and percentage >= self._minimum_coverage_percent
        detail = f"{percentage:.2f}%（門檻 {self._minimum_coverage_percent:.2f}%）"
        return QualityCheck("Test coverage", passed, detail)

    @staticmethod
    def _check_security(result: Mapping[str, object] | None) -> QualityCheck:
        if result is None:
            return QualityCheck("Security scan", False, "缺少安全掃描 artifact")
        findings = result.get("findings")
        passed = result.get("passed") is True and findings == []
        detail = "未發現阻斷性問題" if passed else "安全掃描失敗、有發現項目或 artifact 格式不合法"
        return QualityCheck("Security scan", passed, detail)
