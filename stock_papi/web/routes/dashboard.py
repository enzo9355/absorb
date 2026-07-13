"""Dashboard page route registration."""

from flask import render_template, request


def register_dashboard_page(app):
    def dashboard_page():
        return render_template(
            "dashboard.html",
            search_query=request.args.get("q", "").strip(),
            search_error=request.args.get("error") == "not-found",
        )

    app.add_url_rule("/", "dashboard_page", dashboard_page)
    app.add_url_rule("/dashboard", "dashboard_page", dashboard_page)
