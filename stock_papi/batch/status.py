"""原子 pipeline status 與每次 run transcript。"""

import datetime
import json
import os
import re
from pathlib import Path

from stock_papi.batch.runtime import JOB_TYPES, job_namespace


STAGES = frozenset(
    {
        "pending",
        "data_wait",
        "inference",
        "settlement",
        "aggregation",
        "render",
        "publish",
        "verify",
        "notify",
        "upload",
        "backtest",
        "yielded",
        "completed",
        "failed",
    }
)
DETAIL_KEYS = frozenset(
    {
        "source_market_date",
        "applicable_trading_date",
        "report_date",
        "manifest_path",
        "manifest_sha256",
        "model_version",
        "output_path",
        "processed",
        "failed",
    }
)


class PipelineStatusError(ValueError):
    """Status 欄位或既有 transcript 不合法。"""


def _timestamp(value):
    if (
        not isinstance(value, datetime.datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PipelineStatusError("status time must be timezone-aware")
    return value.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _write_bytes_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_json_atomic(path, document):
    _write_bytes_atomic(
        path,
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )


def redact_error(value):
    text = str(value).replace("\r", " ").replace("\n", " ")[:1000]
    patterns = (
        r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        r"(?i)(bearer\s+)[A-Za-z0-9._~-]+",
        r"(?i)((?:x-api-key|api[_-]?key|token|credential|password|secret|user[_-]?id)\s*[:=]\s*)[^\s,;]+",
    )
    text = re.sub(patterns[0], "Authorization: [REDACTED]", text)
    text = re.sub(patterns[1], r"\1[REDACTED]", text)
    text = re.sub(patterns[2], r"\1[REDACTED]", text)
    return text[:500]


def _details(values):
    if values is None:
        return {}
    if not isinstance(values, dict) or not set(values) <= DETAIL_KEYS:
        raise PipelineStatusError("status details contain unknown keys")
    result = {}
    for key, value in values.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise PipelineStatusError("status detail value is invalid")
        if isinstance(value, str) and len(value) > 500:
            raise PipelineStatusError("status detail value is too long")
        result[key] = value
    return result


class PipelineStatusWriter:
    def __init__(self, root, *, job_type, run_id, target_date):
        if job_type not in JOB_TYPES:
            raise PipelineStatusError("unknown job type")
        if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", str(run_id)) is None:
            raise PipelineStatusError("invalid run id")
        if type(target_date) is not datetime.date:
            raise PipelineStatusError("target_date must be a date")
        self.root = Path(root)
        self.job_type = job_type
        self.run_id = run_id
        self.target_date = target_date
        self.current_path = job_namespace(root, job_type).status
        self.last_success_path = (
            self.current_path.parent / f"last-success-{job_type}.json"
        )
        self.transcript_path = (
            self.current_path.parent / "runs" / job_type / f"{run_id}.jsonl"
        )

    def _transcript(self):
        if not self.transcript_path.exists():
            return b"", 0
        try:
            content = self.transcript_path.read_bytes()
            lines = content.splitlines()
            for line in lines:
                document = json.loads(line)
                if (
                    document.get("job_type") != self.job_type
                    or document.get("run_id") != self.run_id
                ):
                    raise PipelineStatusError("status transcript identity mismatch")
        except (OSError, ValueError, AttributeError) as exc:
            raise PipelineStatusError("status transcript is invalid") from exc
        return content, len(lines)

    def record(self, stage, *, now=None, details=None, error=None):
        if stage not in STAGES:
            raise PipelineStatusError("unknown status stage")
        checked_at = now or datetime.datetime.now(datetime.timezone.utc)
        existing, count = self._transcript()
        document = {
            "schema_version": 1,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "target_date": self.target_date.isoformat(),
            "sequence": count + 1,
            "stage": stage,
            "updated_at": _timestamp(checked_at),
            "details": _details(details),
            "error": None if error is None else redact_error(error),
        }
        line = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        ) + b"\n"
        _write_bytes_atomic(self.transcript_path, existing + line)
        _write_json_atomic(self.current_path, document)
        if stage == "completed":
            _write_json_atomic(self.last_success_path, document)
        return document
