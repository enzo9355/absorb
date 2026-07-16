"""Dashboard page route registration."""

from flask import abort, render_template, request

from reporting.exceptions import ReportWebError


def register_dashboard_page(app, *, load_report_index_v2, load_dashboard_snapshot):
    def dashboard_page():
        try:
            reports = load_report_index_v2() or []
        except ReportWebError:
            reports = []
        daily_cards = {
            report_type: next(
                (item for item in reports if item.get("report_type") == report_type),
                None,
            )
            for report_type in ("post_close", "pre_market")
        }
        snapshot = load_dashboard_snapshot() or {}
        return render_template(
            "dashboard.html",
            search_query=request.args.get("q", "").strip(),
            search_error=request.args.get("error") == "not-found",
            daily_cards=daily_cards,
            model_presentation=snapshot.get("presentation") or {},
        )

    def preview_report_page():
        snapshot = load_dashboard_snapshot()
        if not isinstance(snapshot, dict):
            abort(404)
        return render_template("preview_report.html", snapshot=snapshot)

    app.add_url_rule("/", "dashboard_page", dashboard_page)
    app.add_url_rule("/dashboard", "dashboard_page", dashboard_page)
    app.add_url_rule("/preview/report", "preview_report_page", preview_report_page)
