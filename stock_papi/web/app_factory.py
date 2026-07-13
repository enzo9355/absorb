from collections.abc import Mapping
from typing import Any

from flask import Flask

from stock_papi.web.route_registration import register_routes
from stock_papi.services.content import AI_QUANT_DISCLOSURE


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    from stock_papi import application

    flask_app = Flask("app", root_path=application.APPLICATION_ROOT)
    flask_app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    if config:
        flask_app.config.update(config)
    flask_app.jinja_env.globals["AI_QUANT_DISCLOSURE"] = AI_QUANT_DISCLOSURE
    register_routes(flask_app, application.route_dependencies())
    return flask_app
