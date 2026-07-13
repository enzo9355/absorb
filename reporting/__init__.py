"""Stock Papi 本地台股產業日報套件。

此模組刻意不匯入 PDF 相依套件，避免 Cloud Run 冷啟動載入報告環境。
"""

import os
import subprocess
from pathlib import Path


REPORT_SCHEMA_VERSION = 2
REPORT_GENERATOR_VERSION = "2.0.0"


def git_commit_sha() -> str:
    """回傳建置版本；無 Git 時明確使用 unknown。"""
    configured = (os.getenv("GIT_COMMIT_SHA") or "").strip().lower()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        value = result.stdout.strip().lower()
        return value if value else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
