"""公開 HTML 日報與舊 PDF 路由相容轉址。"""

import datetime
import re

from flask import abort, make_response, redirect, render_template, url_for

from reporting.exceptions import ReportWebError
from reporting.web import find_report


def _valid_report_date(report_date):
    try:
        parsed = datetime.date.fromisoformat(report_date)
    except ValueError:
        return False
    return parsed.isoformat() == report_date


def register_report_routes(
    app, *, load_index, load_metadata, load_index_v2, load_metadata_v2,
    prediction_capability=None,
):
    observation_mode = (
        prediction_capability is not None
        and prediction_capability.mode == "research"
    )

    def _v2_reports():
        try:
            reports = load_index_v2()
        except ReportWebError:
            return None
        if observation_mode and isinstance(reports, list):
            return [
                item for item in reports
                if item.get("product_mode") == "observation"
            ]
        return reports

    def _v2_page(items, heading):
        bundles = []
        for item in items:
            try:
                metadata = load_metadata_v2(item)
            except ReportWebError:
                return "報告內容暫時無法使用", 503
            if metadata is None:
                return "報告內容暫時無法使用", 503
            bundles.append({"item": item, "metadata": metadata})
        response = make_response(
            render_template("report_trading_day.html", heading=heading, bundles=bundles)
        )
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def reports_page():
        if observation_mode:
            reports = []
        else:
            try:
                reports = load_index()
            except ReportWebError:
                reports = None
        reports_v2 = _v2_reports()
        response = make_response(render_template(
            "reports.html", reports=reports or [], reports_v2=reports_v2 or [],
            unavailable=reports is None and reports_v2 is None
        ))
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def legacy_report_redirect(report_date):
        if not _valid_report_date(report_date):
            abort(404)
        return redirect(url_for("report_page", report_date=report_date), code=302)

    def sample_report_download():
        return redirect(url_for("reports_page"), code=302)

    def trading_day_report_page(trading_date):
        if not _valid_report_date(trading_date):
            abort(404)
        reports = _v2_reports()
        if reports is None:
            return "報告服務暫時無法使用", 503
        items = [
            item
            for item in reports
            if item.get("applicable_trading_date") == trading_date
            and item.get("report_type") in {"post_close", "pre_market"}
        ]
        if not items:
            abort(404)
        return _v2_page(items, f"{trading_date} 今日市場準備")

    def pre_market_report_page(trading_date):
        if not _valid_report_date(trading_date):
            abort(404)
        reports = _v2_reports()
        if reports is None:
            return "報告服務暫時無法使用", 503
        items = [
            item
            for item in reports
            if item.get("applicable_trading_date") == trading_date
            and item.get("report_type") == "pre_market"
        ]
        if not items:
            abort(404)
        return _v2_page(items[:1], f"{trading_date} 盤前風險更新")

    def weekly_report_page(week_id):
        if observation_mode:
            abort(404)
        if not isinstance(week_id, str) or re.fullmatch(r"[0-9]{4}-W[0-9]{2}", week_id) is None:
            abort(404)
        reports = _v2_reports()
        if reports is None:
            return "報告服務暫時無法使用", 503
        items = [
            item
            for item in reports
            if item.get("report_type") == "weekly_model" and item.get("week_id") == week_id
        ]
        if not items:
            abort(404)
        return _v2_page(items[:1], f"{week_id} 模型驗證週報")

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
        "/reports/<trading_date>/pre-market",
        "pre_market_report_page",
        pre_market_report_page,
    )
    app.add_url_rule(
        "/reports/weekly/<week_id>", "weekly_report_page", weekly_report_page
    )
