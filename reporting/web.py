import datetime
import json
import math
import re

from .config import ReportConfig
from .exceptions import ReportWebError


def validate_report_index(content: bytes, config: ReportConfig | None = None) -> list[dict]:
    """驗證雲端報告 index，回傳可信且已排序的摘要。"""
    settings = config or ReportConfig()
    if not isinstance(content, bytes) or not 0 < len(content) <= settings.max_index_bytes:
        raise ReportWebError("報告索引大小不合法")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReportWebError("報告索引格式不合法") from exc
    if not isinstance(document, dict):
        raise ReportWebError("報告索引必須是 JSON object")
    reports = document.get("reports")
    if (
        document.get("schema_version") != 1
        or document.get("kind") != "daily-industry-report-index"
        or document.get("market") != "TW"
        or not isinstance(reports, list)
        or len(reports) > settings.index_history_days
    ):
        raise ReportWebError("報告索引 schema 不合法")
    validated = []
    seen_dates = set()
    for item in reports:
        try:
            report_date = datetime.date.fromisoformat(str(item["report_date"]))
            data_as_of = datetime.date.fromisoformat(str(item["data_as_of"]))
            pdf_path = str(item["pdf_path"])
            pdf_sha = str(item["pdf_sha256"])
            pdf_size = item["pdf_size"]
            metadata = str(item["metadata"])
            metadata_sha = str(item["metadata_sha256"])
            coverage = item["coverage"]
            page_count = item["page_count"]
            model_versions = item["model_versions"]
            datetime.datetime.fromisoformat(str(item["generated_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportWebError("報告索引項目不完整") from exc
        if (
            report_date in seen_dates
            or data_as_of != report_date
            or report_date > datetime.date.today()
            or re.fullmatch(r"objects/[0-9a-f]{64}\.pdf", pdf_path) is None
            or re.fullmatch(r"[0-9a-f]{64}", pdf_sha) is None
            or pdf_path != f"objects/{pdf_sha}.pdf"
            or type(pdf_size) is not int
            or not 0 < pdf_size <= settings.max_pdf_bytes
            or re.fullmatch(r"metadata/[0-9a-f]{64}\.json", metadata) is None
            or re.fullmatch(r"[0-9a-f]{64}", metadata_sha) is None
            or metadata != f"metadata/{metadata_sha}.json"
            or type(coverage) not in (int, float)
            or isinstance(coverage, bool)
            or not math.isfinite(float(coverage))
            or not 0 <= float(coverage) <= 1
            or type(page_count) is not int
            or page_count < 1
            or not isinstance(model_versions, dict)
            or not all(
                isinstance(key, str) and type(value) is int and value >= 0
                for key, value in model_versions.items()
            )
        ):
            raise ReportWebError("報告索引項目驗證失敗")
        seen_dates.add(report_date)
        validated.append(dict(item))
    validated.sort(key=lambda item: item["report_date"], reverse=True)
    return validated


def find_report(reports: list[dict], report_date: str) -> dict | None:
    """只依已驗證索引查找交易日，絕不接受 object path。"""
    try:
        parsed = datetime.date.fromisoformat(report_date)
    except (TypeError, ValueError):
        return None
    if parsed.isoformat() != report_date:
        return None
    return next((item for item in reports if item["report_date"] == report_date), None)
