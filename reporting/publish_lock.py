"""Fail-closed cross-process lock for report-v2 publish transactions."""

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
from typing import Iterator

from .exceptions import ReportPublishError


_LOCK_NAME = ".publish-transaction-lock"
_OWNER_FILE_NAME = "owner-token"


def _acquire_report_v2_publish_lock(publish_root: Path) -> tuple[Path, str]:
    lock_path = Path(publish_root) / "publish" / "reports" / "v2" / _LOCK_NAME
    owner_token = secrets.token_hex(32)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.mkdir()
    except FileExistsError as exc:
        raise ReportPublishError(
            "report v2 publish transaction lock is already held"
        ) from exc
    except OSError as exc:
        raise ReportPublishError(
            "report v2 publish transaction lock acquisition failed"
        ) from exc

    owner_path = lock_path / _OWNER_FILE_NAME
    try:
        descriptor = os.open(
            owner_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii", newline="") as stream:
            stream.write(owner_token)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        # The directory remains as a fail-closed stale lock for manual recovery.
        raise ReportPublishError(
            "report v2 publish transaction lock initialization failed"
        ) from exc
    return lock_path, owner_token


def _release_report_v2_publish_lock(lock_path: Path, owner_token: str) -> None:
    owner_path = lock_path / _OWNER_FILE_NAME
    try:
        recorded_owner = owner_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ReportPublishError(
            "report v2 publish transaction lock ownership cannot be verified"
        ) from exc
    if not secrets.compare_digest(recorded_owner, owner_token):
        raise ReportPublishError(
            "report v2 publish transaction lock ownership mismatch"
        )

    try:
        owner_path.unlink()
        lock_path.rmdir()
    except OSError as exc:
        raise ReportPublishError(
            "report v2 publish transaction lock release failed"
        ) from exc


@contextmanager
def report_v2_publish_lock(publish_root: Path) -> Iterator[None]:
    """Serialize one complete report-v2 transaction across processes."""
    lock_path, owner_token = _acquire_report_v2_publish_lock(publish_root)
    body_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        try:
            _release_report_v2_publish_lock(lock_path, owner_token)
        except ReportPublishError as release_error:
            if body_error is not None:
                raise ReportPublishError(
                    "report v2 publish failed and transaction lock release failed"
                ) from release_error
            raise
