import datetime
import gzip
import hashlib
import json
from pathlib import Path


def stock_document(
    symbol: str,
    *,
    start_price: float = 100.0,
    rows: int = 70,
    as_of: str = "2026-07-03",
    ai_probability: float = 70.0,
) -> dict:
    """建立明確標示為測試用途的股票快照。"""
    end = datetime.date.fromisoformat(as_of)
    dates = [end - datetime.timedelta(days=rows - 1 - index) for index in range(rows)]
    daily = []
    for index, day in enumerate(dates):
        close = start_price + index
        daily.append({
            "Date": day.isoformat() + "T00:00:00.000",
            "Close": close,
            "MA20": close - 1,
            "MA60": close - 2,
            "AI_P": ai_probability if index >= 5 else None,
            "RSI": 55.0,
            "RET_1": 0.01,
            "RET_5": 0.05,
            "RET_20": 0.20,
            "VOL_RATIO": 1.2,
            "INST_NET_RATIO": 0.02,
            "ForeignNet": 1000.0,
            "MARKET_RET_1": 0.005,
            "MARKET_RET_5": 0.025,
            "MARKET_RET_20": 0.10,
            "MARKET_VOL_20": 0.012,
            "DATA_PRICE_WARNING": 0.0,
            "OPTION_DATA_MISSING": 0.0,
        })
    return {
        "schema_version": 1,
        "market": "TW",
        "symbol": symbol,
        "name": f"測試股票 {symbol}",
        "as_of": as_of,
        "model_version": "lgbm-5d-v1",
        "latest": daily[-1],
        "backtest": {"accuracy": 55.0, "top_features": ["月線趨勢支撐"]},
        "daily": daily,
        "sample_data": True,
    }


def write_quant_publish(root: Path, documents: list[dict]) -> Path:
    """建立 content-addressed 測試快照，不代表正式資料。"""
    publish = root / "publish" / "quant" / "v1"
    objects = publish / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    entries = {}
    for document in documents:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        compressed = gzip.compress(encoded, mtime=0)
        digest = hashlib.sha256(compressed).hexdigest()
        relative = f"objects/{digest}.json.gz"
        (publish / relative).write_bytes(compressed)
        entries[document["symbol"]] = {
            "path": relative,
            "sha256": digest,
            "size": len(compressed),
            "uncompressed_size": len(encoded),
            "as_of": document["as_of"],
            "model_version": document["model_version"],
        }
    manifest = {
        "schema_version": 2,
        "market": "TW",
        "generated_at": "2026-07-03T10:00:00Z",
        "universe_count": len(entries),
        "symbol_count": len(entries),
        "failure_count": 0,
        "failure_rate": 0.0,
        "coverage": 1.0,
        "failed_symbols": [],
        "market_as_of": max(document["as_of"] for document in documents),
        "symbols": entries,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_relative = f"manifests/TW-20260703T100000Z-{manifest_sha[:12]}.json"
    manifest_path = publish / manifest_relative
    manifest_path.parent.mkdir(exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    latest = {
        "schema_version": 2,
        "market": "TW",
        "generated_at": "2026-07-03T10:00:00Z",
        "manifest": manifest_relative,
        "manifest_sha256": manifest_sha,
    }
    (publish / "latest-TW.json").write_text(
        json.dumps(latest, separators=(",", ":")), encoding="utf-8"
    )
    return publish
