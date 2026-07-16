from collections.abc import Mapping
from typing import Any

from flask import Flask, jsonify, render_template, request

from stock_papi.web.route_registration import register_routes
from stock_papi.services.content import AI_QUANT_DISCLOSURE
from stock_papi.shared.validation import safe_external_https_url


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    from stock_papi import application

    flask_app = Flask("app", root_path=application.APPLICATION_ROOT)
    flask_app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    if config:
        flask_app.config.update(config)
    flask_app.jinja_env.globals["AI_QUANT_DISCLOSURE"] = AI_QUANT_DISCLOSURE
    flask_app.jinja_env.filters["safe_external_url"] = safe_external_https_url

    @flask_app.after_request
    def security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://unpkg.com "
            "'sha256-1HFbWstPdqx9AZ4hK2pfVq5fe4kCRQO5zJaodvFXeJ4='; "
            "style-src 'self'; img-src 'self' https: data:; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @flask_app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith(("/api/", "/callback", "/tasks/", "/broadcast")):
            return jsonify({"error": "not found"}), 404
        return render_template("404.html"), 404

    @flask_app.errorhandler(500)
    def internal_error(_error):
        if request.path.startswith(("/api/", "/callback", "/tasks/", "/broadcast")):
            return jsonify({"error": "internal error"}), 500
        return render_template("500.html"), 500

    register_routes(flask_app, application.route_dependencies())
    return flask_app
