"""Safely add verified uncompressed sizes to one legacy TW quant manifest."""

import argparse
import datetime
import gzip
import hashlib
import hmac
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .source_loader import _json_object, _safe_child, _validate_manifest


MAX_QUANT_ARTIFACT_COMPRESSED_BYTES = 10 * 1024 * 1024
MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class MigrationResult:
    validated_count: int
    failed_count: int
    max_compressed_size: int
    max_uncompressed_size: int
    market_as_of: str
    old_manifest: str
    new_manifest: str | None
    dry_run: bool


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stream_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            size += len(chunk)
            if size > MAX_QUANT_ARTIFACT_COMPRESSED_BYTES:
                raise RuntimeError("stock object compressed size exceeds limit")
            digest.update(chunk)
    return size, digest.hexdigest()


def _stream_decode(path: Path) -> bytes:
    decoded = bytearray()
    try:
        with path.open("rb") as raw, gzip.GzipFile(fileobj=raw, mode="rb") as stream:
            while True:
                remaining = MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES - len(decoded)
                chunk = stream.read(min(_CHUNK_BYTES, remaining + 1))
                if not chunk:
                    break
                decoded.extend(chunk)
                if len(decoded) > MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES:
                    raise RuntimeError("stock object expands beyond limit")
    except OSError as exc:
        raise RuntimeError("stock object gzip is invalid") from exc
    return bytes(decoded)


def _validate_stock(document: dict, symbol: str, market: str, manifest_as_of: str, model_version: str) -> None:
    if (
        document.get("schema_version") != 1
        or document.get("market") != market
        or document.get("symbol") != symbol
        or document.get("as_of") != manifest_as_of
        or document.get("model_version") != model_version
        or not isinstance(document.get("daily"), list)
        or not document["daily"]
        or not all(isinstance(row, dict) for row in document["daily"])
        or not isinstance(document.get("backtest"), dict)
    ):
        raise RuntimeError(f"stock object schema mismatch for {symbol}")
    if str(document["daily"][-1].get("Date") or "").split("T", 1)[0] != manifest_as_of:
        raise RuntimeError(f"stock object daily as_of mismatch for {symbol}")


def migrate_manifest(
    root: Path,
    market: str,
    latest: Path,
    *,
    dry_run: bool,
) -> MigrationResult:
    """Verify every legacy object, then publish a new immutable manifest."""
    if market != "TW":
        raise ValueError("第一階段 migration 只支援 TW")
    root = Path(root)
    publish_root = root / "publish"
    quant_root = publish_root / "quant" / "v1"
    latest_relative = str(Path(latest)).replace("\\", "/")
    latest_path = _safe_child(publish_root, latest_relative, "latest")
    if latest_path.parent != quant_root.resolve(strict=True) or latest_path.name != "latest-TW.json":
        raise RuntimeError("latest path is not allowlisted")

    latest_bytes = latest_path.read_bytes()
    latest_document = _json_object(latest_bytes, "latest")
    manifest_relative = str(latest_document.get("manifest") or "")
    manifest_sha = str(latest_document.get("manifest_sha256") or "")
    if (
        latest_document.get("schema_version") != 2
        or latest_document.get("market") != market
        or re.fullmatch(r"manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json", manifest_relative) is None
        or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None
    ):
        raise RuntimeError("latest pointer is invalid")

    manifest_path = _safe_child(quant_root, manifest_relative, "manifest")
    manifest_bytes = manifest_path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(manifest_bytes).hexdigest(), manifest_sha):
        raise RuntimeError("manifest hash mismatch")
    manifest = _json_object(manifest_bytes, "manifest")
    _validate_manifest(manifest, market)

    migrated_entries = {}
    max_compressed = 0
    max_uncompressed = 0
    changed = False
    for symbol in sorted(manifest["symbols"]):
        entry = manifest["symbols"][symbol]
        if not isinstance(entry, dict) or re.fullmatch(r"[0-9]{4,6}", symbol) is None:
            raise RuntimeError("manifest symbol entry is invalid")
        relative = str(entry.get("path") or "")
        digest = str(entry.get("sha256") or "")
        compressed_size = entry.get("size")
        model_version = str(entry.get("model_version") or "")
        if (
            re.fullmatch(r"objects/[0-9a-f]{64}\.json\.gz", relative) is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(compressed_size) is not int
            or not 0 < compressed_size <= MAX_QUANT_ARTIFACT_COMPRESSED_BYTES
            or entry.get("as_of") != manifest["market_as_of"]
            or not model_version
        ):
            raise RuntimeError(f"stock object metadata is invalid for {symbol}")
        object_path = _safe_child(quant_root, relative, "stock object")
        actual_size, actual_digest = _stream_digest(object_path)
        if actual_size != compressed_size or not hmac.compare_digest(actual_digest, digest):
            raise RuntimeError(f"stock object size or hash mismatch for {symbol}")
        decoded = _stream_decode(object_path)
        repeated_size, repeated_digest = _stream_digest(object_path)
        if repeated_size != actual_size or not hmac.compare_digest(repeated_digest, actual_digest):
            raise RuntimeError(f"stock object changed while reading for {symbol}")
        document = _json_object(decoded, "stock object")
        _validate_stock(document, symbol, market, manifest["market_as_of"], model_version)
        stored_uncompressed = entry.get("uncompressed_size")
        if stored_uncompressed is not None and (
            type(stored_uncompressed) is not int or stored_uncompressed != len(decoded)
        ):
            raise RuntimeError(f"stock object uncompressed size mismatch for {symbol}")
        migrated_entries[symbol] = {**entry, "uncompressed_size": len(decoded)}
        changed = changed or stored_uncompressed is None
        max_compressed = max(max_compressed, actual_size)
        max_uncompressed = max(max_uncompressed, len(decoded))

    new_relative = None
    if not dry_run and changed:
        generated_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        generated_text = generated_at.isoformat().replace("+00:00", "Z")
        migrated = {**manifest, "generated_at": generated_text, "symbols": migrated_entries}
        new_bytes = json.dumps(
            migrated,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        new_sha = hashlib.sha256(new_bytes).hexdigest()
        run_id = generated_at.strftime("%Y%m%dT%H%M%SZ")
        new_relative = f"manifests/{market}-{run_id}-{new_sha[:12]}.json"
        new_path = quant_root / new_relative
        if new_path.exists():
            if new_path.read_bytes() != new_bytes:
                raise RuntimeError("immutable manifest conflict")
        else:
            _write_atomic(new_path, new_bytes)
        new_latest = {
            "schema_version": 2,
            "market": market,
            "generated_at": generated_text,
            "manifest": new_relative,
            "manifest_sha256": new_sha,
        }
        _write_atomic(
            latest_path,
            json.dumps(
                new_latest,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8"),
        )
    elif not dry_run:
        new_relative = manifest_relative

    return MigrationResult(
        validated_count=len(migrated_entries),
        failed_count=0,
        max_compressed_size=max_compressed,
        max_uncompressed_size=max_uncompressed,
        market_as_of=str(manifest["market_as_of"]),
        old_manifest=manifest_relative,
        new_manifest=new_relative,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全遷移 legacy TW quant manifest")
    parser.add_argument("--root", type=Path, default=Path(r"D:\StockPapiData"))
    parser.add_argument("--market", choices=("TW",), default="TW")
    parser.add_argument(
        "--latest", type=Path, default=Path(r"quant\v1\latest-TW.json")
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = migrate_manifest(
            args.root, args.market, args.latest, dry_run=args.dry_run
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "validated_count": 0,
                    "failed_count": 1,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"success": True, **asdict(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
