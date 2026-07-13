import datetime
import gzip
import hashlib
import hmac
import io
import json
import math
import re
import stat
from pathlib import Path
from typing import Any

from .config import ReportConfig
from .exceptions import ReportSourceError
from .schemas import LoadedReportSource, ReportSourceManifest, StockSnapshot

StockSnapshot = StockSnapshot


def _read_limited(path: Path, limit: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
        if not 0 < size <= limit:
            raise ReportSourceError(f"{label} size is invalid")
        content = path.read_bytes()
    except OSError as exc:
        raise ReportSourceError(f"{label} is unavailable") from exc
    if len(content) != size:
        raise ReportSourceError(f"{label} changed while reading")
    return content


def _safe_child(root: Path, relative: str, label: str) -> Path:
    """拒絕跳脫發布根目錄或經過 symlink/junction 的來源路徑。"""
    try:
        root_resolved = root.resolve(strict=True)
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root_resolved):
            raise ReportSourceError(f"{label} escaped publish root")
        current = root / relative
        while current != root:
            metadata = current.lstat()
            if current.is_symlink() or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ReportSourceError(f"{label} uses a reparse point")
            current = current.parent
    except OSError as exc:
        raise ReportSourceError(f"{label} is unavailable") from exc
    return path


def _validate_finite_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReportSourceError("source contains non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_finite_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReportSourceError("source contains non-string key")
            _validate_finite_json(item)
        return
    raise ReportSourceError("source contains unsupported JSON value")


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReportSourceError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ReportSourceError(f"{label} must contain an object")
    _validate_finite_json(document)
    return document


def _validate_manifest(document: dict[str, Any], market: str) -> None:
    try:
        universe = document["universe_count"]
        count = document["symbol_count"]
        failures = document["failure_count"]
        coverage = document["coverage"]
        failure_rate = document["failure_rate"]
        symbols = document["symbols"]
        failed_symbols = document["failed_symbols"]
        market_as_of = datetime.date.fromisoformat(str(document["market_as_of"]))
        datetime.datetime.fromisoformat(str(document["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportSourceError("manifest fields are invalid") from exc
    if (
        document.get("schema_version") != 2
        or document.get("market") != market
        or type(universe) is not int
        or type(count) is not int
        or type(failures) is not int
        or not isinstance(symbols, dict)
        or not isinstance(failed_symbols, list)
        or type(coverage) not in (int, float)
        or type(failure_rate) not in (int, float)
        or universe < 1
        or count != len(symbols)
        or failures != universe - count
        or len(failed_symbols) != failures
        or not math.isclose(float(coverage), count / universe)
        or not math.isclose(float(failure_rate), failures / universe)
        or not 0 < float(coverage) <= 1
        or not 0 <= float(failure_rate) < 0.05
        or market_as_of > datetime.date.today()
    ):
        raise ReportSourceError("manifest consistency check failed")


def _decompress_object(content: bytes, limit: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as stream:
            decoded = stream.read(limit + 1)
    except OSError as exc:
        raise ReportSourceError("stock object gzip is invalid") from exc
    if len(decoded) > limit:
        raise ReportSourceError("stock object expands beyond limit")
    return decoded


def _load_manifest_source(
    publish: Path,
    market: str,
    manifest_relative: str,
    manifest_sha: str,
    settings: ReportConfig,
    report_date: datetime.date | None = None,
) -> LoadedReportSource:
    """載入一份已指定 SHA-256 的 immutable manifest。"""
    manifest_path = _safe_child(publish, manifest_relative, "manifest")
    manifest_bytes = _read_limited(manifest_path, 5_000_000, "manifest")
    if not hmac.compare_digest(hashlib.sha256(manifest_bytes).hexdigest(), manifest_sha):
        raise ReportSourceError("manifest hash mismatch")
    manifest = _json_object(manifest_bytes, "manifest")
    _validate_manifest(manifest, market)
    as_of = datetime.date.fromisoformat(str(manifest["market_as_of"]))
    if report_date is not None and as_of != report_date:
        raise ReportSourceError("requested report date does not match manifest")

    stocks = []
    for symbol in sorted(manifest["symbols"]):
        entry = manifest["symbols"][symbol]
        if not isinstance(entry, dict) or re.fullmatch(r"[0-9]{4,6}", str(symbol)) is None:
            raise ReportSourceError("manifest symbol entry is invalid")
        relative = str(entry.get("path") or "")
        digest = str(entry.get("sha256") or "")
        size = entry.get("size")
        if (
            re.fullmatch(r"objects/[0-9a-f]{64}\.json\.gz", relative) is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or not 0 < size <= settings.max_gzip_bytes
            or entry.get("as_of") != manifest["market_as_of"]
        ):
            raise ReportSourceError("stock object path or metadata is invalid")
        object_path = _safe_child(publish, relative, "stock object")
        object_bytes = _read_limited(object_path, settings.max_gzip_bytes, "stock object")
        if len(object_bytes) != size or not hmac.compare_digest(
            hashlib.sha256(object_bytes).hexdigest(), digest
        ):
            raise ReportSourceError("stock object size or hash mismatch")
        decoded = _decompress_object(object_bytes, settings.max_uncompressed_bytes)
        uncompressed_size = entry.get("uncompressed_size")
        if type(uncompressed_size) is not int or uncompressed_size != len(decoded):
            raise ReportSourceError("stock object uncompressed size mismatch")
        document = _json_object(decoded, "stock object")
        if (
            document.get("schema_version") != 1
            or document.get("market") != market
            or document.get("symbol") != symbol
            or document.get("as_of") != manifest["market_as_of"]
            or document.get("model_version") != entry.get("model_version")
            or not isinstance(document.get("daily"), list)
            or not document["daily"]
            or not all(isinstance(row, dict) for row in document["daily"])
            or not isinstance(document.get("backtest"), dict)
        ):
            raise ReportSourceError("stock object schema mismatch")
        latest_date = str(document["daily"][-1].get("Date") or "").split("T", 1)[0]
        if latest_date != manifest["market_as_of"]:
            raise ReportSourceError("stock object daily as_of mismatch")
        stocks.append(StockSnapshot.from_document(document, digest, size))

    if len(stocks) != manifest["symbol_count"]:
        raise ReportSourceError("manifest symbol count mismatch")
    source_manifest = ReportSourceManifest(
        schema_version=2,
        market=market,
        generated_at=str(manifest["generated_at"]),
        market_as_of=as_of,
        universe_count=manifest["universe_count"],
        symbol_count=manifest["symbol_count"],
        failure_count=manifest["failure_count"],
        failure_rate=float(manifest["failure_rate"]),
        coverage=float(manifest["coverage"]),
        failed_symbols=[str(item) for item in manifest["failed_symbols"]],
        manifest_path=manifest_relative,
        manifest_sha256=manifest_sha,
    )
    return LoadedReportSource(source_manifest, stocks)


def load_report_source(
    root: Path,
    market: str = "TW",
    *,
    report_date: datetime.date | None = None,
    config: ReportConfig | None = None,
) -> LoadedReportSource:
    """從 latest 指標安全載入 manifest 所列的台股快照。"""
    settings = config or ReportConfig(root=Path(root), market=market)
    if market != "TW":
        raise ReportSourceError("第一階段只支援 TW 日報")
    publish = Path(root) / "publish" / "quant" / "v1"
    latest = _json_object(_read_limited(publish / "latest-TW.json", 100_000, "latest"), "latest")
    manifest_relative = str(latest.get("manifest") or "")
    manifest_sha = str(latest.get("manifest_sha256") or "")
    if (
        latest.get("schema_version") != 2
        or latest.get("market") != market
        or re.fullmatch(r"manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json", manifest_relative) is None
        or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None
    ):
        raise ReportSourceError("latest pointer is invalid")
    return _load_manifest_source(
        publish, market, manifest_relative, manifest_sha, settings, report_date
    )


def load_previous_report_source(
    root: Path,
    before: datetime.date,
    market: str = "TW",
    *,
    config: ReportConfig | None = None,
) -> LoadedReportSource | None:
    """找出目前交易日前最新一份可完整驗證的 immutable manifest。"""
    settings = config or ReportConfig(root=Path(root), market=market)
    if market != "TW":
        raise ReportSourceError("第一階段只支援 TW 日報")
    publish = Path(root) / "publish" / "quant" / "v1"
    candidates = []
    for path in (publish / "manifests").glob("TW-*.json"):
        match = re.fullmatch(
            r"TW-[0-9]{8}T[0-9]{6}Z-([0-9a-f]{12})\.json", path.name
        )
        if match is None:
            continue
        try:
            relative = f"manifests/{path.name}"
            safe_path = _safe_child(publish, relative, "previous manifest")
            content = _read_limited(safe_path, 5_000_000, "previous manifest")
            digest = hashlib.sha256(content).hexdigest()
            if not hmac.compare_digest(match.group(1), digest[:12]):
                continue
            document = _json_object(content, "previous manifest")
            _validate_manifest(document, market)
            as_of = datetime.date.fromisoformat(str(document["market_as_of"]))
            if as_of < before:
                candidates.append((as_of, str(document["generated_at"]), relative, digest))
        except (OSError, ReportSourceError, TypeError, ValueError):
            continue
    for _as_of, _generated_at, relative, digest in sorted(candidates, reverse=True):
        try:
            return _load_manifest_source(publish, market, relative, digest, settings)
        except ReportSourceError:
            continue
    return None
