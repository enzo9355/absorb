import datetime
import gzip
import hashlib
import hmac
import io
import json
import re
import time

from stock_papi.repositories.quant_snapshots import (
    MAX_QUANT_ARTIFACT_COMPRESSED_BYTES,
    MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES,
    QUANT_MANIFEST_CACHE_SECONDS,
)


MARKET_INSIGHTS_CACHE = {}


def load_market_insights(today=None, *, load_object, cache=MARKET_INSIGHTS_CACHE):
    now = time.time()
    cached = cache.get("latest")
    if cached and now - cached[1] < QUANT_MANIFEST_CACHE_SECONDS:
        return cached[0]
    latest_bytes = load_object("quant/v1/latest-insights.json", 100_000)
    if latest_bytes is None:
        return None
    try:
        latest = json.loads(latest_bytes.decode("utf-8"))
        path = str(latest["path"])
        digest = str(latest["sha256"])
        size = latest["size"]
        snapshot_date = datetime.date.fromisoformat(str(latest["as_of"]))
        age = (today or datetime.date.today()) - snapshot_date
        if (
            latest.get("schema_version") != 1
            or latest.get("kind") != "market-insights"
            or re.fullmatch(r"objects/[0-9a-f]{64}\.json\.gz", path) is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or not 0 < size <= MAX_QUANT_ARTIFACT_COMPRESSED_BYTES
            or not 0 <= age.days <= 7
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
        if len(decoded) > MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES:
            return None
        document = json.loads(decoded.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("as_of") != latest.get("as_of")
            or any(not isinstance(document.get(key), list) for key in (
                "industries", "mops", "etfs", "supply_chains", "sources"
            ))
        ):
            return None
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        return None
    cache["latest"] = (document, now)
    return document

