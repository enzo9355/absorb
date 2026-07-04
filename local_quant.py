import argparse
import datetime
import gzip
import json
import math
import os
import re
import secrets
import shutil
import sys
from pathlib import Path


TAIPEI = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
RUN_START = datetime.time(5, 30)
DRAIN_START = datetime.time(9, 20)
CHECKPOINT_START = datetime.time(9, 25)
RUN_END = datetime.time(9, 30)
LAYOUT_DIRS = (
    "raw", "cache", "checkpoints", "artifacts", "publish", "logs", "secrets",
)


def validate_data_root(path):
    path = Path(path).expanduser()
    if (
        path.drive.upper() != "D:"
        or path.parent != Path("D:/")
        or path.name.lower() != "stockpapidata"
    ):
        raise ValueError(r"data root must be D:\StockPapiData")
    return path


def window_phase(now=None):
    current = (now or datetime.datetime.now(TAIPEI)).astimezone(TAIPEI).time()
    if RUN_START <= current < DRAIN_START:
        return "run"
    if DRAIN_START <= current < CHECKPOINT_START:
        return "drain"
    if CHECKPOINT_START <= current < RUN_END:
        return "checkpoint"
    return "closed"


def ensure_layout(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in LAYOUT_DIRS:
        (root / name).mkdir(exist_ok=True)
    return root


def check_free_space(root, min_free_gb=100.0, free_bytes=None):
    free_bytes = shutil.disk_usage(Path(root)).free if free_bytes is None else free_bytes
    if free_bytes < min_free_gb * 1024**3:
        raise RuntimeError(f"D drive requires at least {min_free_gb:g} GB free")
    return free_bytes


class RunnerLock:
    def __init__(self, path, token):
        self.path = Path(path)
        self.token = token

    def release(self):
        if not self.path.exists():
            return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("runner lock is unreadable") from exc
        if current.get("token") != self.token:
            raise RuntimeError("runner lock ownership changed")
        self.path.unlink()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.release()


def acquire_lock(root, now=None, stale_after=datetime.timedelta(hours=6)):
    now = now or datetime.datetime.now(TAIPEI)
    lock_path = Path(root) / "checkpoints" / "runner.lock"
    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
            started_at = datetime.datetime.fromisoformat(existing["started_at"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("existing runner lock is invalid") from exc
        if now - started_at <= stale_after:
            raise RuntimeError("local quant runner is already active")
        archive = lock_path.with_name(
            f"runner.lock.stale.{now.strftime('%Y%m%dT%H%M%S')}"
        )
        os.replace(lock_path, archive)

    token = secrets.token_hex(16)
    payload = json.dumps(
        {"pid": os.getpid(), "token": token, "started_at": now.isoformat()},
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        descriptor = os.open(
            lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
    except FileExistsError as exc:
        raise RuntimeError("local quant runner is already active") from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return RunnerLock(lock_path, token)


def save_checkpoint(root, state):
    if not isinstance(state, dict):
        raise TypeError("checkpoint must be a dictionary")
    checkpoint = Path(root) / "checkpoints" / "progress.json"
    _write_json_atomic(checkpoint, state)


def _write_json_atomic(path, state):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _validate_json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _validate_json_value(item)
        return
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _write_gzip_json_atomic(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            stream.write(encoded)
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, path)


def write_stock_artifact(root, market, symbol, payload):
    symbol = str(symbol)
    if market != "TW" or not re.fullmatch(r"[0-9]{4,6}", symbol):
        raise ValueError("invalid Taiwan symbol")
    if not isinstance(payload, dict):
        raise TypeError("stock artifact payload must be a dictionary")
    document = dict(payload)
    document.update(schema_version=1, market=market, symbol=symbol)
    _validate_json_value(document)
    target = Path(root) / "artifacts" / "stocks" / market / f"{symbol}.json.gz"
    _write_gzip_json_atomic(target, document)
    return target


def load_checkpoint(root):
    checkpoint = Path(root) / "checkpoints" / "progress.json"
    if not checkpoint.exists():
        return {}
    try:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("checkpoint is invalid") from exc
    if not isinstance(state, dict):
        raise RuntimeError("checkpoint must contain an object")
    return state


def main(argv=None, now=None, free_bytes=None):
    parser = argparse.ArgumentParser(description="Stock Papi local quant runner")
    parser.add_argument("--root", default=r"D:\StockPapiData")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-free-gb", type=float, default=100.0)
    args = parser.parse_args(argv)

    try:
        root = validate_data_root(Path(args.root))
        if args.init:
            ensure_layout(root)
        elif not root.is_dir():
            raise RuntimeError("data root is not initialized")
        available = check_free_space(root, args.min_free_gb, free_bytes)
        checked_at = now or datetime.datetime.now(TAIPEI)
        phase = window_phase(checked_at)
        _write_json_atomic(
            root / "logs" / "runner-status.json",
            {
                "checked_at": checked_at.isoformat(),
                "dry_run": bool(args.dry_run),
                "free_gb": round(available / 1024**3, 1),
                "phase": phase,
                "root": str(root),
            },
        )
        if not args.dry_run:
            raise RuntimeError("phase one only supports --dry-run")
        if phase == "run":
            with acquire_lock(root, now=checked_at):
                save_checkpoint(
                    root,
                    {"stage": "ready", "checked_at": checked_at.isoformat()},
                )
        print(f"local quant phase={phase} free_gb={available / 1024**3:.1f}")
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"local quant refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
