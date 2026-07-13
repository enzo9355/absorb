import datetime
import json
import math
import re
import hashlib
import hmac

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
            market_action = item.get("market_action")
            headline = item.get("headline")
            key_industries = item.get("key_industries")
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
            or (market_action is not None and (not isinstance(market_action, str) or not 1 <= len(market_action) <= 20))
            or (headline is not None and (not isinstance(headline, str) or not 1 <= len(headline) <= 200))
            or (
                key_industries is not None
                and (
                    not isinstance(key_industries, list)
                    or len(key_industries) > 5
                    or not all(isinstance(value, str) and 1 <= len(value) <= 40 for value in key_industries)
                )
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


def validate_report_metadata(content: bytes, item: dict) -> dict:
    """驗證 content-addressed metadata，並綁定已驗證 index 項目。"""
    if not isinstance(content, bytes) or not 0 < len(content) <= 2 * 1024 * 1024:
        raise ReportWebError("報告 metadata 大小不合法")
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), item["metadata_sha256"]):
        raise ReportWebError("報告 metadata 雜湊不符")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReportWebError("報告 metadata 格式不合法") from exc
    if not isinstance(document, dict):
        raise ReportWebError("報告 metadata 必須是 JSON object")
    expected = {
        "schema_version": 1,
        "kind": "daily-industry-report",
        "market": "TW",
        "report_date": item["report_date"],
        "data_as_of": item["data_as_of"],
        "pdf_path": item["pdf_path"],
        "pdf_sha256": item["pdf_sha256"],
        "pdf_size": item["pdf_size"],
        "page_count": item["page_count"],
    }
    if any(document.get(key) != value for key, value in expected.items()):
        raise ReportWebError("報告 metadata 與索引不一致")
    if not isinstance(document.get("summary"), list) or not all(
        isinstance(value, str) and len(value) <= 500 for value in document["summary"]
    ):
        raise ReportWebError("報告摘要格式不合法")
    if not isinstance(document.get("warnings"), list) or not all(
        isinstance(value, str) and len(value) <= 500 for value in document["warnings"]
    ):
        raise ReportWebError("報告警示格式不合法")
    public_report = document.get("public_report")
    if public_report is not None:
        _validate_public_report(public_report)
    return document


def _validate_public_report(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ReportWebError("公開報告 schema 不合法")
    recommendation = document.get("market_recommendation")
    if not isinstance(recommendation, dict):
        raise ReportWebError("公開報告市場建議缺失")
    for key in ("action", "level", "headline", "confidence"):
        if not isinstance(recommendation.get(key), str) or not recommendation[key]:
            raise ReportWebError("公開報告市場建議不完整")
    for key in ("supporting_reasons", "risk_reasons", "invalidation_conditions"):
        values = recommendation.get(key)
        if not isinstance(values, list) or len(values) > 10 or not all(
            isinstance(value, str) and 1 <= len(value) <= 500 for value in values
        ):
            raise ReportWebError("公開報告理由格式不合法")
    for key, limit in (("key_points", 10), ("industries", 100), ("stocks", 100)):
        values = document.get(key)
        if not isinstance(values, list) or len(values) > limit:
            raise ReportWebError("公開報告清單格式不合法")
    if not isinstance(document.get("backtest"), dict) or not isinstance(document.get("model_quality"), dict):
        raise ReportWebError("公開報告專業資料缺失")
