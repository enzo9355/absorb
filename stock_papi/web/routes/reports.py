"""公開 HTML 日報與舊 PDF 路由相容轉址。"""

import datetime

from flask import abort, make_response, redirect, render_template, url_for

from reporting.exceptions import ReportWebError
from reporting.web import find_report


def _valid_report_date(report_date):
    try:
        parsed = datetime.date.fromisoformat(report_date)
    except ValueError:
        return False
    return parsed.isoformat() == report_date


def register_report_routes(app, *, load_index, load_metadata):
    def reports_page():
        try:
            reports = load_index()
        except ReportWebError:
            reports = None
        response = make_response(render_template(
            "reports.html", reports=reports or [], unavailable=reports is None
        ))
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def report_page(report_date):
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
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def legacy_report_redirect(report_date):
        if not _valid_report_date(report_date):
            abort(404)
        return redirect(url_for("report_page", report_date=report_date), code=302)

    def sample_report_download():
        return redirect(url_for("reports_page"), code=302)

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
