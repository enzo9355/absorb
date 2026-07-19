"""Public HTML report routes and legacy compatibility redirects."""

import datetime
import os
import re
import uuid

from flask import abort, make_response, redirect, render_template, url_for

from reporting.exceptions import ReportWebError
from reporting.web import find_report
from reporting.professional_html import build_professional_report_view
from stock_papi.services.report_view import build_observation_report_view
from werkzeug.exceptions import HTTPException


def _valid_report_date(report_date):
    try:
        parsed = datetime.date.fromisoformat(report_date)
    except ValueError:
        return False
    return parsed.isoformat() == report_date


def register_report_routes(
    app, *, load_index, load_metadata, load_index_v2, load_metadata_v2,
    load_canonical_object=None, prediction_capability=None,
):
    observation_mode = (
        prediction_capability is not None
        and prediction_capability.mode == "research"
    )

    def _secure_response(response, *, cache="public, max-age=300"):
        response.headers["Cache-Control"] = cache
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def _report_error(status, *, report_type=None, report_date=None, exc=None):
        correlation_id = uuid.uuid4().hex[:16]
        if exc is not None:
            app.logger.exception(
                "report_render_failed correlation_id=%s report_type=%s report_date=%s error_type=%s",
                correlation_id,
                report_type,
                report_date,
                type(exc).__name__,
            )
        response = make_response(
            render_template(
                "report_unavailable.html",
                status=status,
                correlation_id=correlation_id,
            ),
            status,
        )
        response.headers["X-Correlation-ID"] = correlation_id
        if status == 503:
            response.headers["Retry-After"] = "60"
        return _secure_response(response, cache="no-store")

    def _v2_reports(*, required=False):
        reports = load_index_v2()
        if reports is None:
            if required:
                raise ReportWebError("報告索引暫時無法使用")
            return []
        if observation_mode:
            return [
                item for item in reports
                if item.get("product_mode") == "observation"
            ]
        return reports

    def _daily_items(trading_date):
        reports = _v2_reports(required=True)
        return [
            item
            for item in reports
            if item.get("applicable_trading_date") == trading_date
            and item.get("report_type") in {"post_close", "pre_market"}
        ]

    def _observation_page(date_param: str, report_type: str):
        try:
            reports = _v2_reports(required=True)
            if report_type == "post_close":
                # For post_close, date_param is source_market_date
                item = next(
                    (value for value in reports
                     if value.get("report_type") == report_type
                     and value.get("source_market_date") == date_param),
                    None,
                )
            else:
                # For pre_market, date_param is applicable_trading_date
                item = next(
                    (value for value in reports
                     if value.get("report_type") == report_type
                     and value.get("applicable_trading_date") == date_param),
                    None,
                )

            if item is None:
                abort(404)
            metadata = load_metadata_v2(item)
            if metadata is None:
                raise ReportWebError("報告內容暫時無法使用")
            
            if report_type == "pre_market":
                expected_base_metadata_sha256 = None
                post_close_item = next(
                    (
                        value for value in reports
                        if value.get("report_type") == "post_close"
                        and value.get("applicable_trading_date") == date_param
                    ),
                    None,
                )
                if post_close_item is None:
                    raise ReportWebError("盤前報告缺少盤後基底")
                expected_base_metadata_sha256 = post_close_item.get(
                    "metadata_sha256"
                )
                report = build_observation_report_view(
                    metadata,
                    expected_base_metadata_sha256=expected_base_metadata_sha256,
                )
                response = make_response(
                    render_template("report_observation.html", report=report)
                )
            elif report_type == "post_close":
                canonical_ptr = metadata.get("professional_report")
                if not isinstance(canonical_ptr, dict) or not canonical_ptr.get("object"):
                    raise ReportWebError("報告 Canonical Object 指標遺失")
                if load_canonical_object is None:
                    raise ReportWebError("系統未提供 load_canonical_object")
                
                import hashlib
                try:
                    canonical_doc = load_canonical_object(canonical_ptr["object"])
                except Exception as exc:
                    raise ReportWebError("無法讀取 Canonical Object") from exc
                
                from reporting.professional_schema import ProfessionalPostCloseReport
                try:
                    prof_report = ProfessionalPostCloseReport.from_document(canonical_doc)
                except ValueError as exc:
                    raise ReportWebError("Canonical Object 驗證失敗") from exc

                pdf_download_url = None
                view_model = build_professional_report_view(
                    prof_report, pdf_download_url=pdf_download_url
                )
                response = make_response(
                    render_template("reports/post_close_professional.html", report=view_model)
                )
            else:
                abort(404)
            return _secure_response(response)
        except ReportWebError as exc:
            return _report_error(
                503,
                report_type=report_type,
                report_date=date_param,
                exc=exc,
            )
        except HTTPException:
            raise
        except Exception as exc:
            return _report_error(
                500,
                report_type=report_type,
                report_date=date_param,
                exc=exc,
            )

    def reports_page():
        if observation_mode:
            reports = []
        else:
            try:
                reports = load_index()
            except ReportWebError:
                reports = None
        try:
            reports_v2 = _v2_reports(required=observation_mode)
        except ReportWebError as exc:
            if observation_mode:
                return _report_error(503, exc=exc)
            reports_v2 = None
        response = make_response(render_template(
            "reports.html", reports=reports or [], reports_v2=reports_v2 or [],
            unavailable=reports is None and reports_v2 is None
        ))
        return _secure_response(response)

    def report_page(report_date):
        if observation_mode:
            abort(404)
        if not _valid_report_date(report_date):
            abort(404)
        try:
            reports = load_index()
        except ReportWebError:
            return "報告服務暫時無法使用", 503
        if reports is None:
            return "報告服務暫時無法使用", 503
        item = find_report(reports, report_date)
        if item is None:
            abort(404)
        try:
            metadata = load_metadata(item)
        except ReportWebError:
            return "報告內容暫時無法使用", 503
        if metadata is None:
            return "報告內容暫時無法使用", 503
        response = make_response(render_template(
            "report_detail.html",
            report=item,
            metadata=metadata,
            public_report=metadata.get("public_report"),
        ))
        return _secure_response(response)

    def legacy_report_redirect(report_date):
        if not _valid_report_date(report_date):
            abort(404)
        return redirect(url_for("report_page", report_date=report_date), code=302)

    def sample_report_download():
        return redirect(url_for("reports_page"), code=302)

    def trading_day_report_page(trading_date):
        if not _valid_report_date(trading_date):
            abort(404)
        try:
            items = _daily_items(trading_date)
            if not items:
                abort(404)
            response = make_response(render_template(
                "report_day_index.html",
                trading_date=trading_date,
                reports=items,
            ))
            return _secure_response(response)
        except ReportWebError as exc:
            return _report_error(503, report_date=trading_date, exc=exc)
        except HTTPException:
            raise
        except Exception as exc:
            return _report_error(500, report_date=trading_date, exc=exc)

    def post_close_report_page(trading_date):
        if not _valid_report_date(trading_date):
            abort(404)
        return _observation_page(trading_date, "post_close")

    def pre_market_report_page(trading_date):
        if not _valid_report_date(trading_date):
            abort(404)
        return _observation_page(trading_date, "pre_market")

    def weekly_report_page(week_id):
        if observation_mode:
            abort(404)
        if not isinstance(week_id, str) or re.fullmatch(r"[0-9]{4}-W[0-9]{2}", week_id) is None:
            abort(404)
        return _report_error(503)

    app.add_url_rule("/reports", "reports_page", reports_page)
    app.add_url_rule("/reports/<report_date>", "report_page", report_page)
    app.add_url_rule(
        "/reports/<report_date>/preview", "report_preview", legacy_report_redirect
    )
    app.add_url_rule(
        "/reports/<report_date>/download", "report_download", legacy_report_redirect
    )
    app.add_url_rule(
        "/reports/sample/download", "sample_report_download", sample_report_download
    )
    app.add_url_rule(
        "/reports/trading-day/<trading_date>",
        "trading_day_report_page",
        trading_day_report_page,
    )
    app.add_url_rule(
        "/reports/<trading_date>/post-close",
        "post_close_report_page",
        post_close_report_page,
    )
    app.add_url_rule(
        "/reports/<trading_date>/pre-market",
        "pre_market_report_page",
        pre_market_report_page,
    )
    app.add_url_rule(
        "/reports/weekly/<week_id>", "weekly_report_page", weekly_report_page
    )
