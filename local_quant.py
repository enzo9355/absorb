import argparse
import datetime
import gzip
import importlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import time
from pathlib import Path


TAIPEI = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
RUN_START = datetime.time(5, 30)
DRAIN_START = datetime.time(9, 20)
CHECKPOINT_START = datetime.time(9, 25)
RUN_END = datetime.time(9, 30)
LAYOUT_DIRS = (
    "raw", "cache", "checkpoints", "artifacts", "publish", "logs", "secrets",
)
RETENTION_DAYS = {
    "cache/tmp": 1,
    "cache/pycache": 30,
    "raw": 30,
    "logs": 30,
    "publish": 30,
}
SEC_US_UNIVERSE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_US_UNIVERSE_MAX_BYTES = 5 * 1024 * 1024
US_EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}
CRYPTO_SECURITY_TERMS = (
    "bitcoin", "ethereum", "crypto", "solana", "litecoin", "dogecoin",
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


def _is_reparse_point(entry, metadata):
    return entry.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _cleanup_tree(directory, cutoff, root, summary):
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return
    except OSError:
        summary["failed"] += 1
        return
    for entry in entries:
        path = Path(entry.path)
        try:
            metadata = entry.stat(follow_symlinks=False)
            if _is_reparse_point(entry, metadata):
                summary["skipped_reparse_points"] += 1
                continue
            if not path.resolve(strict=False).is_relative_to(root):
                raise RuntimeError("cleanup path escaped data root")
            if entry.is_dir(follow_symlinks=False):
                _cleanup_tree(path, cutoff, root, summary)
                try:
                    path.rmdir()
                except OSError:
                    pass
            elif entry.is_file(follow_symlinks=False) and metadata.st_mtime < cutoff:
                path.unlink()
                summary["deleted_files"] += 1
                summary["reclaimed_bytes"] += metadata.st_size
        except RuntimeError:
            raise
        except OSError:
            summary["failed"] += 1


def cleanup_expired_data(root, now=None):
    root = validate_data_root(root)
    root_resolved = root.resolve(strict=True)
    checked_at = now or datetime.datetime.now(TAIPEI)
    summary = {
        "deleted_files": 0,
        "reclaimed_bytes": 0,
        "failed": 0,
        "skipped_reparse_points": 0,
    }
    for relative, days in RETENTION_DAYS.items():
        cutoff = (checked_at - datetime.timedelta(days=days)).timestamp()
        _cleanup_tree(root / Path(relative), cutoff, root_resolved, summary)

    checkpoints = root / "checkpoints"
    cutoff = (checked_at - datetime.timedelta(days=7)).timestamp()
    try:
        entries = list(os.scandir(checkpoints))
    except OSError:
        summary["failed"] += 1
        return summary
    for entry in entries:
        if not re.fullmatch(r"runner\.lock\.stale\.\d{8}T\d{6}", entry.name):
            continue
        try:
            metadata = entry.stat(follow_symlinks=False)
            if _is_reparse_point(entry, metadata):
                summary["skipped_reparse_points"] += 1
            elif entry.is_file(follow_symlinks=False) and metadata.st_mtime < cutoff:
                Path(entry.path).unlink()
                summary["deleted_files"] += 1
                summary["reclaimed_bytes"] += metadata.st_size
        except OSError:
            summary["failed"] += 1
    return summary


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


def _checkpoint_path(root, market="TW"):
    if market == "TW":
        filename = "progress.json"
    elif market == "US":
        filename = "progress-US.json"
    else:
        raise ValueError("unsupported market")
    return Path(root) / "checkpoints" / filename


def save_checkpoint(root, state, market="TW"):
    if not isinstance(state, dict):
        raise TypeError("checkpoint must be a dictionary")
    checkpoint = _checkpoint_path(root, market)
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


def validate_market_symbol(market, symbol):
    symbol = str(symbol)
    valid = (
        market == "TW" and bool(re.fullmatch(r"[0-9]{4,6}", symbol))
    ) or (
        market == "US"
        and len(symbol) <= 10
        and bool(re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?", symbol))
    )
    if not valid:
        raise ValueError("invalid market symbol")
    return symbol


def write_stock_artifact(root, market, symbol, payload):
    symbol = validate_market_symbol(market, symbol)
    if not isinstance(payload, dict):
        raise TypeError("stock artifact payload must be a dictionary")
    document = dict(payload)
    document.update(schema_version=1, market=market, symbol=symbol)
    _validate_json_value(document)
    target = Path(root) / "artifacts" / "stocks" / market / f"{symbol}.json.gz"
    _write_gzip_json_atomic(target, document)
    return target


def run_market_batch(
    root,
    market,
    symbols,
    analyze_symbol,
    limit=200,
    now_fn=lambda: datetime.datetime.now(TAIPEI),
    delay=0.5,
    sleep_fn=time.sleep,
):
    if market not in ("TW", "US") or limit < 1 or delay < 0:
        raise ValueError("invalid market batch settings")
    checkpoint = load_checkpoint(root, market=market)
    checked_at = now_fn()
    start = (
        checkpoint.get("next_index", 0)
        if checkpoint.get("stage") == "market_batch"
        and checkpoint.get("market") == market
        else 0
    )
    if (
        start >= len(symbols)
        and checkpoint.get("cycle_completed_on") != checked_at.date().isoformat()
    ):
        start = 0
    next_index = start
    attempted = completed = 0
    failures = []
    for index in range(start, min(len(symbols), start + limit)):
        if index != start:
            checked_at = now_fn()
        if window_phase(checked_at) != "run":
            break
        symbol = str(symbols[index])
        attempted += 1
        try:
            payload = analyze_symbol(symbol)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": type(exc).__name__})
        else:
            write_stock_artifact(root, market, symbol, payload)
            completed += 1
        next_index = index + 1
        state = {
            "stage": "market_batch",
            "market": market,
            "next_index": next_index,
            "failed": failures,
            "updated_at": checked_at.isoformat(),
        }
        if next_index >= len(symbols):
            state["cycle_completed_on"] = checked_at.date().isoformat()
        save_checkpoint(root, state, market=market)
        if delay:
            sleep_fn(delay)
    return {
        "attempted": attempted,
        "completed": completed,
        "failed": failures,
        "next_index": next_index,
    }


def load_stock_pipeline(root):
    cache = Path(root) / "cache" / "yfinance"
    cache.mkdir(parents=True, exist_ok=True)
    import yfinance as yf

    yf.set_tz_cache_location(str(cache))
    os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "local-only")
    os.environ.setdefault("LINE_CHANNEL_SECRET", "local-only")
    removed = {
        key: os.environ.pop(key)
        for key in ("GEMINI_API_KEY", "GCP_PROJECT_ID")
        if key in os.environ
    }
    try:
        return importlib.import_module("app")
    finally:
        os.environ.update(removed)


def get_taiwan_symbols(pipeline):
    return sorted(
        {
            str(symbol)
            for symbol in pipeline.industry_map.get("全市場", [])
            if re.fullmatch(r"[0-9]{4,6}", str(symbol))
        }
    )


def parse_sec_us_universe(document):
    if not isinstance(document, dict):
        raise ValueError("invalid SEC universe document")
    fields = document.get("fields")
    rows = document.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise ValueError("invalid SEC universe schema")
    required = {"name", "ticker", "exchange"}
    if not required.issubset(fields):
        raise ValueError("SEC universe fields are incomplete")
    positions = {name: fields.index(name) for name in required}
    symbols = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < len(fields):
            continue
        exchange = row[positions["exchange"]]
        name = str(row[positions["name"]] or "").lower()
        symbol = str(row[positions["ticker"]] or "").strip().upper()
        if exchange not in US_EXCHANGES or any(term in name for term in CRYPTO_SECURITY_TERMS):
            continue
        try:
            symbols.add(validate_market_symbol("US", symbol))
        except ValueError:
            continue
    if not symbols:
        raise ValueError("SEC universe contains no supported US symbols")
    return sorted(symbols)


def fetch_sec_us_universe_json():
    import requests

    response = requests.get(
        SEC_US_UNIVERSE_URL,
        headers={
            "User-Agent": "StockPapi/1.0 (https://github.com/enzo9355/Stock-Papi)"
        },
        timeout=15,
    )
    response.raise_for_status()
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > SEC_US_UNIVERSE_MAX_BYTES:
        raise RuntimeError("SEC universe response is too large")
    content = response.content
    if len(content) > SEC_US_UNIVERSE_MAX_BYTES:
        raise RuntimeError("SEC universe response is too large")
    return json.loads(content)


def _read_us_universe_cache(path):
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
        symbols = [validate_market_symbol("US", item) for item in cached["symbols"]]
        if not symbols or not isinstance(cached.get("as_of"), str):
            return None
        return {"as_of": cached["as_of"], "symbols": sorted(set(symbols))}
    except (KeyError, OSError, TypeError, ValueError):
        return None


def get_us_symbols(root, fetch_json=None, now=None):
    checked_at = now or datetime.datetime.now(TAIPEI)
    cache_path = Path(root) / "raw" / "us-universe.json"
    cached = _read_us_universe_cache(cache_path) if cache_path.exists() else None
    if cached and cached["as_of"] == checked_at.date().isoformat():
        return cached["symbols"]
    try:
        symbols = parse_sec_us_universe((fetch_json or fetch_sec_us_universe_json)())
    except Exception as exc:
        if cached:
            return cached["symbols"]
        raise RuntimeError("US universe is unavailable") from exc
    _write_json_atomic(
        cache_path,
        {
            "as_of": checked_at.date().isoformat(),
            "source": SEC_US_UNIVERSE_URL,
            "symbols": symbols,
        },
    )
    return symbols


def build_taiwan_stock_snapshot(pipeline, symbol):
    symbol = str(symbol)
    if not re.fullmatch(r"[0-9]{4,6}", symbol):
        raise ValueError("invalid Taiwan symbol")
    frame = pipeline.get_data(symbol, 730)
    if frame is None or frame.empty:
        raise ValueError("price history is unavailable")
    frame = pipeline.calc_all(frame)
    if frame is None or frame.empty:
        raise ValueError("calculated history is unavailable")
    backtest = pipeline.run_ai_engine(frame)
    if not isinstance(backtest, dict):
        raise ValueError("backtest is unavailable")

    daily = json.loads(
        frame.reset_index().to_json(
            orient="records",
            date_format="iso",
            date_unit="ms",
        )
    )
    latest = daily[-1]
    as_of = str(latest.get("Date", "")).split("T", 1)[0]
    if not as_of:
        raise ValueError("latest market date is unavailable")
    horizon = int(getattr(pipeline, "PREDICTION_HORIZON", 5))
    return {
        "as_of": as_of,
        "name": pipeline.get_stock_name(symbol),
        "rows": len(daily),
        "model_version": f"lgbm-{horizon}d-v1",
        "latest": latest,
        "backtest": backtest,
        "daily": daily,
    }


def load_checkpoint(root, market="TW"):
    checkpoint = _checkpoint_path(root, market)
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
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--market", choices=("TW",), default="TW")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.5)
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
        status = {
            "checked_at": checked_at.isoformat(),
            "dry_run": bool(args.dry_run),
            "run": bool(args.run),
            "free_gb": round(available / 1024**3, 1),
            "phase": phase,
            "root": str(root),
        }
        status_path = root / "logs" / "runner-status.json"
        _write_json_atomic(status_path, status)
        if args.dry_run and args.run:
            raise ValueError("choose either --dry-run or --run")
        if not args.dry_run and not args.run:
            raise ValueError("choose --dry-run or --run")
        if args.dry_run and phase == "run":
            with acquire_lock(root, now=checked_at):
                save_checkpoint(
                    root,
                    {"stage": "ready", "checked_at": checked_at.isoformat()},
                )
        elif args.run and phase == "run":
            with acquire_lock(root, now=checked_at):
                status["cleanup"] = cleanup_expired_data(root, now=checked_at)
                _write_json_atomic(status_path, status)
                pipeline = load_stock_pipeline(root)
                symbols = get_taiwan_symbols(pipeline)
                now_fn = (
                    (lambda: checked_at)
                    if now is not None
                    else (lambda: datetime.datetime.now(TAIPEI))
                )
                summary = run_market_batch(
                    root,
                    args.market,
                    symbols,
                    lambda symbol: build_taiwan_stock_snapshot(pipeline, symbol),
                    limit=args.limit,
                    now_fn=now_fn,
                    delay=args.delay,
                )
                print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
        print(f"local quant phase={phase} free_gb={available / 1024**3:.1f}")
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"local quant refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
