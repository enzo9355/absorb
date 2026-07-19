"""Safe HTML view-model adapter for canonical professional reports."""

from __future__ import annotations

import copy
from typing import Any

from .professional_schema import ProfessionalPostCloseReport, ProfessionalSection


def _section_view(section: ProfessionalSection) -> dict[str, Any]:
    return {
        "status": section.status,
        "data_as_of": section.data_as_of.isoformat() if section.data_as_of else None,
        "reason": section.reason,
        "data": copy.deepcopy(section.data),
    }


def build_professional_report_view(
    report: ProfessionalPostCloseReport, *, pdf_download_url: str | None = None
) -> dict[str, Any]:
    """Return a Jinja-safe view model without internal object paths or raw metadata."""

    if not isinstance(report, ProfessionalPostCloseReport):
        raise TypeError("report must be ProfessionalPostCloseReport")
    identity = report.identity
    return {
        "title": "ABSORB 台股市場、產業與量化研究日報",
        "identity": {
            "report_id": identity.report_id,
            "source_market_date": identity.source_market_date.isoformat(),
            "applicable_trading_date": identity.applicable_trading_date.isoformat(),
            "published_at": identity.published_at.isoformat(),
            "content_sha256_short": identity.content_sha256[:12],
            "source_manifest_sha256_short": identity.source_manifest_sha256[:12],
            "code_commit_sha_short": identity.code_commit_sha[:12],
            "generator_version": identity.generator_version,
            "feature_schema_version": identity.feature_schema_version,
            "recommendation_policy_version": identity.recommendation_policy_version,
            "model_version": identity.model_version,
        },
        "executive_summary": report.executive_summary.to_document(),
        "key_events": copy.deepcopy(list(report.key_events)),
        "market": _section_view(report.market),
        "capital_flows": _section_view(report.capital_flows),
        "industries": _section_view(report.industries),
        "securities": _section_view(report.securities),
        "quantitative_research": _section_view(report.quantitative_research),
        "validation": _section_view(report.validation),
        "next_session": _section_view(report.next_session),
        "governance": _section_view(report.governance),
        "ai_reference": _section_view(report.ai_reference),
        "pdf_download_url": pdf_download_url,
    }
