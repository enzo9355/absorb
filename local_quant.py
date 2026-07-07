import argparse
import datetime
import gzip
import hashlib
import importlib
import io
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

from market_insights import (
    ETF_CATALOG,
    SUPPLY_CHAINS,
    build_industries,
    build_supply_chains,
    normalize_etf_holdings,
    parse_mops_items,
)


TAIPEI = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
RUN_START = datetime.time(2, 30)
US_RUN_START = datetime.time(5, 30)
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
STOCK_ARTIFACT_MAX_COMPRESSED_BYTES = 5 * 1024 * 1024
STOCK_ARTIFACT_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
US_EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}
CRYPTO_SECURITY_TERMS = (
    "bitcoin", "ethereum", "crypto", "solana", "litecoin", "dogecoin",
)
MOPS_SOURCES = (
    ("TWSE", "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"),
    ("TPEx", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"),
)
MARKET_INSIGHTS_MAX_BYTES = 5 * 1024 * 1024


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


def market_run_allowed(market, now):
    local_time = now.astimezone(TAIPEI).time()
    return window_phase(now) == "run" and (
        market != "US" or local_time >= US_RUN_START
    )


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


def _write_bytes_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _sha256_path(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _validated_artifact(root, market, symbol, generated_at):
    symbol = validate_market_symbol(market, symbol)
    path = Path(root) / "artifacts" / "stocks" / market / f"{symbol}.json.gz"
    if not path.is_file():
        raise RuntimeError(f"artifact is missing for {market}:{symbol}")
    compressed_size = path.stat().st_size
    if not 0 < compressed_size <= STOCK_ARTIFACT_MAX_COMPRESSED_BYTES:
        raise RuntimeError(f"artifact is invalid for {market}:{symbol}")
    compressed = path.read_bytes()
    if len(compressed) != compressed_size:
        raise RuntimeError(f"artifact is invalid for {market}:{symbol}")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            decoded = stream.read(STOCK_ARTIFACT_MAX_UNCOMPRESSED_BYTES + 1)
        if len(decoded) > STOCK_ARTIFACT_MAX_UNCOMPRESSED_BYTES:
            raise ValueError("artifact expands beyond limit")
        document = json.loads(decoded.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("market") != market
            or document.get("symbol") != symbol
        ):
            raise ValueError("artifact schema mismatch")
        _validate_json_value(document)
        as_of = datetime.date.fromisoformat(str(document["as_of"]))
        if as_of > generated_at.astimezone(TAIPEI).date():
            raise ValueError("artifact date is in the future")
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"artifact is invalid for {market}:{symbol}") from exc
    return path, compressed, document


def publish_market_snapshot(
    root, market, symbols, generated_at=None, failed_symbols=()
):
    if market not in ("TW", "US"):
        raise ValueError("unsupported market")
    symbols = sorted({validate_market_symbol(market, symbol) for symbol in symbols})
    if not symbols:
        raise ValueError("market universe is empty")
    excluded = {
        validate_market_symbol(market, symbol) for symbol in failed_symbols
    }
    if not excluded.issubset(symbols):
        raise ValueError("failed symbols must belong to market universe")
    generated_at = generated_at or datetime.datetime.now(TAIPEI)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=TAIPEI)
    generated_text = generated_at.astimezone(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    publish_root = Path(root) / "publish" / "quant" / "v1"
    object_root = publish_root / "objects"
    candidates = {}
    errors = []
    for symbol in symbols:
        if symbol in excluded:
            continue
        try:
            path, compressed, document = _validated_artifact(
                root, market, symbol, generated_at
            )
        except RuntimeError as exc:
            excluded.add(symbol)
            errors.append(str(exc))
            continue
        candidates[symbol] = {
            "source": path,
            "sha256": hashlib.sha256(compressed).hexdigest(),
            "size": len(compressed),
            "as_of": document["as_of"],
            "model_version": str(document.get("model_version") or "unknown"),
        }

    if candidates:
        market_as_of = max(item["as_of"] for item in candidates.values())
        for symbol in list(candidates):
            if candidates[symbol]["as_of"] != market_as_of:
                excluded.add(symbol)
                del candidates[symbol]
    else:
        market_as_of = None
    failure_rate = len(excluded) / len(symbols)
    if failure_rate >= 0.05 or not candidates:
        detail = f"; {errors[0]}" if errors else ""
        raise RuntimeError(
            f"market failure rate {failure_rate:.2%} is not publishable{detail}"
        )

    entries = {}
    for symbol, candidate in candidates.items():
        compressed = candidate["source"].read_bytes()
        digest = candidate["sha256"]
        if len(compressed) != candidate["size"] or hashlib.sha256(compressed).hexdigest() != digest:
            raise RuntimeError(f"artifact changed during publish for {market}:{symbol}")
        object_path = object_root / f"{digest}.json.gz"
        if object_path.exists():
            if (
                object_path.stat().st_size != len(compressed)
                or _sha256_path(object_path) != digest
            ):
                raise RuntimeError("published object hash mismatch")
            os.utime(object_path, None)
        else:
            _write_bytes_atomic(object_path, compressed)
        entries[symbol] = {
            "path": f"objects/{digest}.json.gz",
            "sha256": digest,
            "size": len(compressed),
            "as_of": candidate["as_of"],
            "model_version": candidate["model_version"],
        }

    manifest = {
        "schema_version": 2,
        "market": market,
        "generated_at": generated_text,
        "universe_count": len(symbols),
        "symbol_count": len(entries),
        "failure_count": len(excluded),
        "failure_rate": failure_rate,
        "coverage": len(entries) / len(symbols),
        "failed_symbols": sorted(excluded),
        "market_as_of": market_as_of,
        "symbols": entries,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    run_id = generated_at.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_name = f"{market}-{run_id}-{manifest_digest[:12]}.json"
    manifest_path = publish_root / "manifests" / manifest_name
    if manifest_path.exists():
        if manifest_path.read_bytes() != manifest_bytes:
            raise RuntimeError("immutable manifest conflict")
    else:
        _write_bytes_atomic(manifest_path, manifest_bytes)

    latest_path = publish_root / f"latest-{market}.json"
    _write_json_atomic(
        latest_path,
        {
            "schema_version": 2,
            "market": market,
            "generated_at": generated_text,
            "manifest": f"manifests/{manifest_name}",
            "manifest_sha256": manifest_digest,
        },
    )
    return latest_path


def publish_market_insights(root, document, generated_at=None):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("invalid market insights document")
    as_of = datetime.date.fromisoformat(str(document.get("as_of")))
    generated_at = generated_at or datetime.datetime.now(TAIPEI)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=TAIPEI)
    if as_of > generated_at.astimezone(TAIPEI).date():
        raise ValueError("market insights date is in the future")
    _validate_json_value(document)
    encoded = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=6, mtime=0)
    if len(compressed) > STOCK_ARTIFACT_MAX_COMPRESSED_BYTES:
        raise RuntimeError("market insights snapshot is too large")
    digest = hashlib.sha256(compressed).hexdigest()
    publish_root = Path(root) / "publish" / "quant" / "v1"
    object_path = publish_root / "objects" / f"{digest}.json.gz"
    if object_path.exists():
        if object_path.stat().st_size != len(compressed) or _sha256_path(object_path) != digest:
            raise RuntimeError("published insights object hash mismatch")
        os.utime(object_path, None)
    else:
        _write_bytes_atomic(object_path, compressed)
    generated_text = generated_at.astimezone(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    latest_path = publish_root / "latest-insights.json"
    _write_json_atomic(latest_path, {
        "schema_version": 1,
        "kind": "market-insights",
        "generated_at": generated_text,
        "as_of": document["as_of"],
        "path": f"objects/{digest}.json.gz",
        "sha256": digest,
        "size": len(compressed),
    })
    return latest_path


def _fetch_json_list(url):
    import requests

    response = requests.get(
        url,
        headers={"User-Agent": "StockPapi/1.0 (public market research)"},
        timeout=15,
    )
    response.raise_for_status()
    if int(response.headers.get("Content-Length") or 0) > MARKET_INSIGHTS_MAX_BYTES:
        raise RuntimeError("market insights response is too large")
    content = response.content
    if len(content) > MARKET_INSIGHTS_MAX_BYTES:
        raise RuntimeError("market insights response is too large")
    document = json.loads(content)
    if not isinstance(document, list):
        raise ValueError("market insights response must be a list")
    return document


def _fetch_yfinance_holdings(etf):
    import yfinance as yf

    frame = yf.Ticker(etf["ticker"]).funds_data.top_holdings
    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for symbol, row in frame.iterrows():
        rows.append({
            "symbol": str(symbol),
            "name": row.get("Name") or row.get("name") or str(symbol),
            "weight": row.get("Holding Percent") if "Holding Percent" in row else row.get("holdingPercent"),
        })
    return rows


def _read_insights_metric(root, symbol):
    symbol = str(symbol).upper()
    market = "TW" if re.fullmatch(r"\d{4,6}", symbol) else "US"
    if market == "US" and not re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?", symbol):
        return None
    try:
        _path, _compressed, document = _validated_artifact(
            root, market, symbol, datetime.datetime.now(TAIPEI)
        )
        latest = document["latest"]
        probability = max(0, min(100, int(round(float(latest["AI_P"])))))
        close = float(latest["Close"])
        ma20 = float(latest["MA20"])
        return {
            "name": str(document.get("name") or symbol),
            "prob": probability,
            "trend": "多頭" if close > ma20 else "空頭",
            "as_of": str(document["as_of"]),
        }
    except (KeyError, RuntimeError, TypeError, ValueError):
        return None


def _load_local_market_insights(root):
    try:
        publish_root = Path(root) / "publish" / "quant" / "v1"
        latest = json.loads((publish_root / "latest-insights.json").read_text(encoding="utf-8"))
        path = str(latest["path"])
        if (
            latest.get("schema_version") != 1
            or latest.get("kind") != "market-insights"
            or re.fullmatch(r"objects/[0-9a-f]{64}\.json\.gz", path) is None
        ):
            return None
        compressed = (publish_root / path).read_bytes()
        if len(compressed) != latest["size"] or hashlib.sha256(compressed).hexdigest() != latest["sha256"]:
            return None
        decoded = gzip.decompress(compressed)
        if len(decoded) > STOCK_ARTIFACT_MAX_UNCOMPRESSED_BYTES:
            return None
        document = json.loads(decoded)
        return document if document.get("schema_version") == 1 else None
    except (KeyError, OSError, TypeError, ValueError):
        return None


def build_market_insights_document(root, pipeline, now=None, fetch_json=None, fetch_etf=None):
    checked_at = now or datetime.datetime.now(TAIPEI)
    previous = _load_local_market_insights(root) or {}
    fetch_json = fetch_json or _fetch_json_list
    fetch_etf = fetch_etf or _fetch_yfinance_holdings

    mops = []
    successful_mops_sources = 0
    for source, url in MOPS_SOURCES:
        try:
            mops.extend(parse_mops_items(fetch_json(url), source))
            successful_mops_sources += 1
        except Exception:
            continue
    if not successful_mops_sources:
        mops = list(previous.get("mops") or [])
    mops.sort(key=lambda row: row.get("published_at", ""), reverse=True)

    previous_etfs = {item.get("ticker"): item for item in previous.get("etfs") or []}
    etfs = []
    for etf in ETF_CATALOG:
        try:
            normalized = normalize_etf_holdings(fetch_etf(etf), etf)
        except Exception:
            normalized = previous_etfs.get(etf["ticker"])
        if normalized and normalized.get("holdings"):
            etfs.append(normalized)

    symbols = {
        str(symbol).upper()
        for category, codes in pipeline.industry_map.items()
        if category not in {"全市場", "ETF專區"}
        for symbol in codes
    }
    symbols.update(
        symbol
        for chain in SUPPLY_CHAINS
        for _stage, nodes in chain["stages"]
        for symbol, _name, _market in nodes
    )
    metrics = {}
    for symbol in symbols:
        metric = _read_insights_metric(root, symbol)
        if metric:
            metrics[symbol] = metric

    return {
        "schema_version": 1,
        "as_of": checked_at.astimezone(TAIPEI).date().isoformat(),
        "industries": build_industries(pipeline.industry_map, metrics),
        "mops": mops[:200],
        "etfs": etfs,
        "supply_chains": build_supply_chains(metrics),
        "sources": [source for source, _url in MOPS_SOURCES] + ["yfinance", "Stock Papi local artifacts"],
    }


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
    same_batch = (
        checkpoint.get("stage") == "market_batch"
        and checkpoint.get("market") == market
    )
    start = (
        checkpoint.get("next_index", 0)
        if same_batch
        else 0
    )
    symbol_set = {str(symbol) for symbol in symbols}
    failures = []
    seen_failures = set()
    if same_batch:
        for item in checkpoint.get("failed", []):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", ""))
            if symbol not in symbol_set or symbol in seen_failures:
                continue
            failures.append({"symbol": symbol, "error": str(item.get("error") or "Error")})
            seen_failures.add(symbol)
    if (
        start >= len(symbols)
        and not failures
        and checkpoint.get("cycle_completed_on") != checked_at.date().isoformat()
        and (
            not checkpoint.get("cycle_completed_on")
            or checkpoint.get("published_cycle_on")
            == checkpoint.get("cycle_completed_on")
        )
    ):
        start = 0
    next_index = start
    attempted = completed = 0

    def save_state():
        state = {
            "stage": "market_batch",
            "market": market,
            "next_index": next_index,
            "failed": failures,
            "updated_at": checked_at.isoformat(),
        }
        if next_index >= len(symbols) and not failures:
            state["cycle_completed_on"] = checked_at.date().isoformat()
        save_checkpoint(root, state, market=market)

    for retry in list(failures):
        if attempted:
            checked_at = now_fn()
        if window_phase(checked_at) != "run":
            break
        symbol = retry["symbol"]
        attempted += 1
        failures = [item for item in failures if item["symbol"] != symbol]
        try:
            payload = analyze_symbol(symbol)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": type(exc).__name__})
        else:
            write_stock_artifact(root, market, symbol, payload)
            completed += 1
        save_state()
        if delay:
            sleep_fn(delay)

    while attempted < limit and next_index < len(symbols):
        if attempted:
            checked_at = now_fn()
        if window_phase(checked_at) != "run":
            break
        symbol = str(symbols[next_index])
        attempted += 1
        try:
            payload = analyze_symbol(symbol)
        except Exception as exc:
            failures = [item for item in failures if item["symbol"] != symbol]
            failures.append({"symbol": symbol, "error": type(exc).__name__})
        else:
            write_stock_artifact(root, market, symbol, payload)
            completed += 1
        next_index += 1
        save_state()
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


def build_stock_snapshot(pipeline, market, symbol):
    symbol = validate_market_symbol(market, symbol)
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
    parser.add_argument("--insights", action="store_true")
    parser.add_argument("--market", choices=("TW", "US", "ALL"), default="TW")
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
        if args.run and args.market == "US" and not market_run_allowed(
            "US", checked_at
        ):
            phase = "closed"
        status = {
            "checked_at": checked_at.isoformat(),
            "dry_run": bool(args.dry_run),
            "run": bool(args.run),
            "insights": bool(args.insights),
            "free_gb": round(available / 1024**3, 1),
            "phase": phase,
            "root": str(root),
        }
        status_path = root / "logs" / "runner-status.json"
        _write_json_atomic(status_path, status)
        if sum((bool(args.dry_run), bool(args.run), bool(args.insights))) != 1:
            raise ValueError("choose one of --dry-run, --run or --insights")
        if args.insights and phase == "run":
            with acquire_lock(root, now=checked_at):
                status["cleanup"] = cleanup_expired_data(root, now=checked_at)
                pipeline = load_stock_pipeline(root)
                document = build_market_insights_document(root, pipeline, now=checked_at)
                publish_market_insights(root, document, generated_at=checked_at)
                status["market_insights"] = {
                    "as_of": document["as_of"],
                    "mops": len(document["mops"]),
                    "etfs": len(document["etfs"]),
                }
                _write_json_atomic(status_path, status)
                print(json.dumps(status["market_insights"], ensure_ascii=False, separators=(",", ":")))
        if args.run and phase == "run":
            with acquire_lock(root, now=checked_at):
                status["cleanup"] = cleanup_expired_data(root, now=checked_at)
                _write_json_atomic(status_path, status)
                pipeline = load_stock_pipeline(root)
                now_fn = (
                    (lambda: checked_at)
                    if now is not None
                    else (lambda: datetime.datetime.now(TAIPEI))
                )
                summaries = {}
                markets = ("TW", "US") if args.market == "ALL" else (args.market,)
                for market in markets:
                    market_now = now_fn()
                    if not market_run_allowed(market, market_now):
                        break
                    symbols = (
                        get_taiwan_symbols(pipeline)
                        if market == "TW"
                        else get_us_symbols(root, now=market_now)
                    )
                    summary = run_market_batch(
                        root,
                        market,
                        symbols,
                        lambda symbol, selected=market: build_stock_snapshot(
                            pipeline, selected, symbol
                        ),
                        limit=args.limit,
                        now_fn=now_fn,
                        delay=args.delay,
                    )
                    if summary.get("next_index", 0) >= len(symbols):
                        failed_symbols = [
                            item["symbol"] for item in summary.get("failed", [])
                        ]
                        try:
                            publish_market_snapshot(
                                root,
                                market,
                                symbols,
                                generated_at=market_now,
                                failed_symbols=failed_symbols,
                            )
                        except RuntimeError as exc:
                            summary["published"] = False
                            summary["publish_error"] = str(exc)
                        else:
                            checkpoint = load_checkpoint(root, market=market)
                            checkpoint["published_cycle_on"] = (
                                checkpoint.get("cycle_completed_on")
                                or market_now.date().isoformat()
                            )
                            checkpoint["published_at"] = market_now.isoformat()
                            checkpoint["published_failure_count"] = len(failed_symbols)
                            save_checkpoint(root, checkpoint, market=market)
                            summary["published"] = True
                    summaries[market] = summary
                print(json.dumps(summaries, ensure_ascii=False, separators=(",", ":")))
        print(f"local quant phase={phase} free_gb={available / 1024**3:.1f}")
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"local quant refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
