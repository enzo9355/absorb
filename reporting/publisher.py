import datetime
import hashlib
import json
import os
from pathlib import Path

from . import REPORT_GENERATOR_VERSION, REPORT_SCHEMA_VERSION, git_commit_sha
from .config import ReportConfig
from .exceptions import ReportPublishError
from .public_report import build_public_report
from .schemas import DailyIndustryReport, LoadedReportSource, ReportGenerationResult
from .web import validate_report_index


def _json_bytes(document: dict) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


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


def _local_mirror_path(archive: Path, market: str, report_date: datetime.date) -> Path:
    return Path(archive) / f"stock-papi-{market.lower()}-industry-daily-{report_date.isoformat()}.pdf"


def _mirror_matches(pdf_path: Path, sidecar_path: Path, pdf_sha256: str) -> bool:
    try:
        if hashlib.sha256(pdf_path.read_bytes()).hexdigest() != pdf_sha256:
            return False
        return json.loads(sidecar_path.read_text(encoding="utf-8")).get("pdf_sha256") == pdf_sha256
    except (OSError, ValueError, TypeError):
        return False


def _restore_atomic(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        _write_atomic(path, previous)


def _write_local_mirror(
    archive: Path,
    market: str,
    report_date: datetime.date,
    pdf_bytes: bytes,
    metadata_bytes: bytes,
    pdf_sha256: str,
) -> Path:
    """將已發布的 PDF 與 metadata 寫入可讀鏡像，失敗時還原既有副本。"""
    pdf_path = _local_mirror_path(archive, market, report_date)
    sidecar_path = pdf_path.with_suffix(".json")
    if _mirror_matches(pdf_path, sidecar_path, pdf_sha256):
        return pdf_path
    previous_pdf = None
    previous_sidecar = None
    try:
        previous_pdf = pdf_path.read_bytes() if pdf_path.exists() else None
        previous_sidecar = sidecar_path.read_bytes() if sidecar_path.exists() else None
        _write_atomic(pdf_path, pdf_bytes)
        _write_atomic(sidecar_path, metadata_bytes)
    except OSError as exc:
        try:
            _restore_atomic(pdf_path, previous_pdf)
            _restore_atomic(sidecar_path, previous_sidecar)
        except OSError:
            pass
        raise ReportPublishError("local report mirror update failed") from exc
    return pdf_path


def is_source_already_published(root: Path, source: LoadedReportSource) -> bool:
    """判斷同交易日、同來源 manifest 是否已正式發布。"""
    publish = Path(root) / "publish" / "reports" / "v1"
    latest_path = publish / "latest-TW.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        metadata_path = publish / str(latest["metadata"])
        metadata_bytes = metadata_path.read_bytes()
        if hashlib.sha256(metadata_bytes).hexdigest() != latest["metadata_sha256"]:
            return False
        metadata = json.loads(metadata_bytes)
        return (
            metadata.get("report_date") == source.manifest.market_as_of.isoformat()
            and metadata.get("source_manifest_sha256") == source.manifest.manifest_sha256
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False


def publish_report(
    root: Path,
    report: DailyIndustryReport,
    result: ReportGenerationResult,
    config: ReportConfig | None = None,
    archive_dir: Path | None = None,
) -> Path:
    """以 content-addressed PDF/metadata 更新 index，最後替換 latest。"""
    settings = config or ReportConfig(root=Path(root))
    if not result.success or result.output_path is None or result.sha256 is None:
        raise ValueError("only a successful report can be published")
    if any(stock.sample_data for stock in report.source.stocks):
        raise ValueError("SAMPLE / TEST DATA 不得正式發布")
    try:
        pdf_bytes = result.output_path.read_bytes()
    except OSError as exc:
        raise ReportPublishError("generated PDF is unavailable") from exc
    if (
        len(pdf_bytes) != result.file_size
        or not 0 < len(pdf_bytes) <= settings.max_pdf_bytes
        or hashlib.sha256(pdf_bytes).hexdigest() != result.sha256
    ):
        raise ReportPublishError("generated PDF size or hash mismatch")

    publish = Path(root) / "publish" / "reports" / "v1"
    pdf_relative = f"objects/{result.sha256}.pdf"
    pdf_path = publish / pdf_relative
    if pdf_path.exists():
        if pdf_path.read_bytes() != pdf_bytes:
            raise ReportPublishError("immutable PDF object conflict")
    else:
        _write_atomic(pdf_path, pdf_bytes)

    manifest = report.source.manifest
    public_report = build_public_report(report)
    metadata = {
        "schema_version": 1,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_generator_version": REPORT_GENERATOR_VERSION,
        "git_commit_sha": git_commit_sha(),
        "sample_data": False,
        "kind": "daily-industry-report",
        "market": "TW",
        "report_date": report.report_date.isoformat(),
        "title": "Stock Papi 台股產業量化分析日報",
        "generated_at": result.generated_at.isoformat().replace("+00:00", "Z"),
        "data_as_of": manifest.market_as_of.isoformat(),
        "source_manifest": f"quant/v1/{manifest.manifest_path}",
        "source_manifest_sha256": manifest.manifest_sha256,
        "model_versions": report.model_versions,
        "universe_count": manifest.universe_count,
        "symbol_count": manifest.symbol_count,
        "failure_count": manifest.failure_count,
        "coverage": manifest.coverage,
        "pdf_path": pdf_relative,
        "pdf_sha256": result.sha256,
        "pdf_size": result.file_size,
        "page_count": result.page_count,
        "summary": report.summary,
        "warnings": result.warnings,
        "public_report": public_report,
    }
    metadata_bytes = _json_bytes(metadata)
    metadata_sha = hashlib.sha256(metadata_bytes).hexdigest()
    metadata_relative = f"metadata/{metadata_sha}.json"
    metadata_path = publish / metadata_relative
    if metadata_path.exists():
        if metadata_path.read_bytes() != metadata_bytes:
            raise ReportPublishError("immutable metadata conflict")
    else:
        _write_atomic(metadata_path, metadata_bytes)

    entry = {
        "report_date": metadata["report_date"],
        "data_as_of": metadata["data_as_of"],
        "generated_at": metadata["generated_at"],
        "model_versions": metadata["model_versions"],
        "coverage": metadata["coverage"],
        "pdf_path": pdf_relative,
        "pdf_sha256": result.sha256,
        "pdf_size": result.file_size,
        "page_count": result.page_count,
        "market_action": public_report["market_recommendation"]["action"],
        "headline": public_report["market_recommendation"]["headline"],
        "key_industries": [
            item["name"] for item in public_report["industries"][:3]
        ],
        "metadata": metadata_relative,
        "metadata_sha256": metadata_sha,
    }
    index_path = publish / "index-TW.json"
    if index_path.exists():
        try:
            reports = validate_report_index(index_path.read_bytes(), settings)
        except Exception as exc:
            raise ReportPublishError("existing report index is invalid") from exc
    else:
        reports = []
    reports = [item for item in reports if item.get("report_date") != entry["report_date"]]
    reports.append(entry)
    reports.sort(key=lambda item: item["report_date"], reverse=True)
    index = {
        "schema_version": 1,
        "kind": "daily-industry-report-index",
        "market": "TW",
        "updated_at": metadata["generated_at"],
        "reports": reports[: settings.index_history_days],
    }
    index_bytes = _json_bytes(index)
    if len(index_bytes) > settings.max_index_bytes:
        raise ReportPublishError("report index exceeds size limit")
    _write_atomic(index_path, index_bytes)

    latest = {
        "schema_version": 1,
        "kind": "daily-industry-report",
        "market": "TW",
        "report_date": metadata["report_date"],
        "generated_at": metadata["generated_at"],
        "metadata": metadata_relative,
        "metadata_sha256": metadata_sha,
    }
    latest_path = publish / "latest-TW.json"
    _write_atomic(latest_path, _json_bytes(latest))
    _write_local_mirror(
        archive_dir or (Path(root) / "reports" / manifest.market),
        manifest.market,
        report.report_date,
        pdf_bytes,
        metadata_bytes,
        result.sha256,
    )
    return latest_path
