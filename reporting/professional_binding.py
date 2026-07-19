"""Validation module for binding professional post-close report with metadata and routes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .professional_schema import ProfessionalPostCloseReport, compute_content_sha256
from .schemas import ReportMetadataV2


def validate_professional_report_binding(
    *,
    route_source_date: dt.date | str | None = None,
    metadata: ReportMetadataV2 | dict[str, Any],
    pointer: dict[str, Any] | None = None,
    report: ProfessionalPostCloseReport | dict[str, Any],
) -> None:
    """Cross-check professional post-close report against metadata, pointer, and optional route parameters."""

    if isinstance(report, ProfessionalPostCloseReport):
        report_obj = report
        report_doc = report.to_document()
    elif isinstance(report, dict):
        report_obj = ProfessionalPostCloseReport.from_document(report)
        report_doc = dict(report)
    else:
        raise ValueError("report must be a ProfessionalPostCloseReport instance or document dict")

    identity = report_obj.identity

    if isinstance(metadata, ReportMetadataV2):
        meta_obj = metadata
    elif isinstance(metadata, dict):
        meta_obj = ReportMetadataV2.from_document(metadata)
    else:
        raise ValueError("metadata must be a ReportMetadataV2 instance or document dict")

    # 1. Identity static field constraints
    if identity.report_type != "post_close":
        raise ValueError("report_type must be post_close")
    if identity.market != "TW":
        raise ValueError("market must be TW")
    if identity.product_mode != "observation_with_research":
        raise ValueError("product_mode must be observation_with_research")
    if identity.product_tier != "institutional":
        raise ValueError("product_tier must be institutional")

    expected_report_id = f"TW-{identity.source_market_date.strftime('%Y%m%d')}-post-close-institutional"
    if identity.report_id != expected_report_id:
        raise ValueError(f"report_id '{identity.report_id}' does not match expected '{expected_report_id}'")
    # 2. Metadata cross-checks
    if meta_obj.report_type != "post_close":
        raise ValueError("metadata report_type must be post_close")
    if meta_obj.market != "TW":
        raise ValueError("metadata market must be TW")
    if identity.source_market_date != meta_obj.source_market_date:
        raise ValueError("source_market_date mismatch between report identity and metadata")
    if identity.applicable_trading_date != meta_obj.applicable_trading_date:
        raise ValueError("applicable_trading_date mismatch between report identity and metadata")
    if identity.source_manifest != meta_obj.source_manifest:
        raise ValueError("source_manifest mismatch between report identity and metadata")
    if identity.source_manifest_sha256 != meta_obj.source_manifest_sha256:
        raise ValueError("source_manifest_sha256 mismatch between report identity and metadata")

    # 3. Route source date cross-check
    if route_source_date is not None:
        if isinstance(route_source_date, str):
            parsed_route_date = dt.date.fromisoformat(route_source_date)
        elif isinstance(route_source_date, dt.date):
            parsed_route_date = route_source_date
        else:
            raise ValueError("route_source_date must be a date or ISO string")

        if identity.source_market_date != parsed_route_date:
            raise ValueError("route_source_date does not match report source_market_date")

    # 4. Content SHA255 re-calculation check
    recalculated_sha = compute_content_sha256(report_doc)
    if identity.content_sha256 != recalculated_sha:
        raise ValueError("content_sha256 does not match recalculated content hash")

    # 5. Pointer cross-checks
    pointer_to_check = pointer if pointer is not None else meta_obj.professional_report
    if pointer_to_check is not None:
        if isinstance(pointer_to_check, dict):
            ptr_content_sha = pointer_to_check.get("content_sha256")
            ptr_gen_ver = pointer_to_check.get("generator_version")
            ptr_commit_sha = pointer_to_check.get("code_commit_sha")
        else:
            ptr_content_sha = getattr(pointer_to_check, "content_sha256", None)
            ptr_gen_ver = getattr(pointer_to_check, "generator_version", None)
            ptr_commit_sha = getattr(pointer_to_check, "code_commit_sha", None)

        if ptr_content_sha != identity.content_sha256:
            raise ValueError("pointer content_sha256 does not match report identity content_sha256")
        if ptr_gen_ver is not None and ptr_gen_ver != identity.generator_version:
            raise ValueError("pointer generator_version does not match report identity generator_version")
        if ptr_commit_sha is not None and ptr_commit_sha != identity.code_commit_sha:
            raise ValueError("pointer code_commit_sha does not match report identity code_commit_sha")
