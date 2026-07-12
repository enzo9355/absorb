import datetime
import gzip
import hashlib
import hmac
import io
import json
import math
import re
import time


QUANT_MANIFEST_CACHE_SECONDS = 300
MAX_QUANT_ARTIFACT_COMPRESSED_BYTES = 5 * 1024 * 1024
MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
QUANT_MANIFEST_CACHE = {}


def published_quant_manifest(market, today=None, *, load_object, cache=QUANT_MANIFEST_CACHE):
    now = time.time()
    cached = cache.get(market)
    if cached and now - cached[1] < QUANT_MANIFEST_CACHE_SECONDS:
        return cached[0]
    latest_bytes = load_object(f"quant/v1/latest-{market}.json", 100_000)
    if latest_bytes is None:
        return None
    try:
        latest = json.loads(latest_bytes.decode("utf-8"))
        manifest_path = str(latest["manifest"])
        if (
            latest.get("schema_version") != 2
            or latest.get("market") != market
            or re.fullmatch(
                rf"manifests/{market}-[0-9]{{8}}T[0-9]{{6}}Z-[0-9a-f]{{12}}\.json",
                manifest_path,
            ) is None
        ):
            return None
        manifest_bytes = load_object(f"quant/v1/{manifest_path}", 5_000_000)
        if manifest_bytes is None or not hmac.compare_digest(
            hashlib.sha256(manifest_bytes).hexdigest(),
            str(latest["manifest_sha256"]),
        ):
            return None
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        market_date = datetime.date.fromisoformat(str(manifest["market_as_of"]))
        age = (today or datetime.date.today()) - market_date
        universe_count = manifest.get("universe_count")
        symbol_count = manifest.get("symbol_count")
        failure_count = manifest.get("failure_count")
        coverage = manifest.get("coverage")
        failure_rate = manifest.get("failure_rate")
        failed_symbols = manifest.get("failed_symbols")
        symbols = manifest.get("symbols")
        if (
            manifest.get("schema_version") != 2
            or manifest.get("market") != market
            or not isinstance(symbols, dict)
            or type(universe_count) is not int
            or type(symbol_count) is not int
            or type(failure_count) is not int
            or universe_count < 1
            or symbol_count != len(symbols)
            or failure_count != universe_count - symbol_count
            or not isinstance(failed_symbols, list)
            or len(failed_symbols) != failure_count
            or type(coverage) not in (int, float)
            or type(failure_rate) not in (int, float)
            or coverage <= 0.95
            or failure_rate >= 0.05
            or not math.isclose(coverage, symbol_count / universe_count)
            or not math.isclose(failure_rate, failure_count / universe_count)
            or not 0 <= age.days <= 7
        ):
            return None
    except (KeyError, TypeError, UnicodeError, ValueError):
        return None
    cache[market] = (manifest, now)
    return manifest


def fetch_quant_snapshot(
    code, today=None, *, is_us_ticker_fn, load_manifest, load_object
):
    market = "US" if is_us_ticker_fn(code) else "TW" if str(code).isdigit() else None
    if market is None:
        return None
    manifest = load_manifest(market, today=today)
    entry = (manifest or {}).get("symbols", {}).get(code)
    if not isinstance(entry, dict):
        return None
    try:
        path = str(entry["path"])
        digest = str(entry["sha256"])
        size = entry["size"]
        uncompressed_size = entry["uncompressed_size"]
        if (
            re.fullmatch(r"objects/[0-9a-f]{64}\.json\.gz", path) is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or not 0 < size <= MAX_QUANT_ARTIFACT_COMPRESSED_BYTES
            or type(uncompressed_size) is not int
            or not 0 < uncompressed_size <= MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES
            or entry.get("as_of") != manifest.get("market_as_of")
        ):
            return None
        compressed = load_object(f"quant/v1/{path}", size)
        if (
            compressed is None
            or len(compressed) != size
            or not hmac.compare_digest(hashlib.sha256(compressed).hexdigest(), digest)
        ):
            return None
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            decoded = stream.read(MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES + 1)
        if len(decoded) != uncompressed_size:
            return None
        document = json.loads(decoded.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("market") != market
            or document.get("symbol") != code
            or document.get("as_of") != entry.get("as_of")
            or not isinstance(document.get("backtest"), dict)
            or not isinstance(document.get("daily"), list)
        ):
            return None
        return document
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        return None
