"""Daily report page, preview, and download routes."""

import datetime

from flask import Response, abort, render_template

from reporting.exceptions import ReportWebError
from reporting.web import find_report


def register_report_routes(
    app,
    *,
    load_index,
    load_pdf,
    sample_report_path,
    sample_report_filename,
    max_pdf_bytes,
):
    def reports_page():
        try:
            reports = load_index()
        except ReportWebError:
            reports = None
        return render_template(
            "reports.html", reports=reports or [], unavailable=reports is None
        )

    def report_pdf_response(report_date, disposition):
        try:
            parsed = datetime.date.fromisoformat(report_date)
        except ValueError:
            abort(404)
        if parsed.isoformat() != report_date:
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
        content = load_pdf(item)
        if content is None:
            return "報告檔案暫時無法使用", 503
        filename = f"stock-papi-tw-industry-daily-{report_date}.pdf"
        response = Response(content, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'{disposition}; filename="{filename}"'
        )
        response.headers["ETag"] = f'"{item["pdf_sha256"]}"'
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def sample_report_response():
        try:
            with open(sample_report_path, "rb") as stream:
                content = stream.read(max_pdf_bytes + 1)
        except OSError:
            return "SAMPLE 報告暫時無法使用", 503
        if not content.startswith(b"%PDF") or len(content) > max_pdf_bytes:
            return "SAMPLE 報告暫時無法使用", 503
        response = Response(content, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{sample_report_filename}"'
        )
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def report_preview(report_date):
        return report_pdf_response(report_date, "inline")

    def report_download(report_date):
        return report_pdf_response(report_date, "attachment")

    def sample_report_download():
        return sample_report_response()

    app.add_url_rule("/reports", "reports_page", reports_page)
    app.add_url_rule(
        "/reports/<report_date>/preview", "report_preview", report_preview
    )
    app.add_url_rule(
        "/reports/<report_date>/download", "report_download", report_download
    )
    app.add_url_rule(
        "/reports/sample/download", "sample_report_download", sample_report_download
    )
