from collections.abc import Mapping
from typing import Any

from flask import Flask

from stock_papi.web.route_registration import register_routes


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    from stock_papi import application

    flask_app = Flask("app", root_path=application.APPLICATION_ROOT)
    flask_app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    if config:
        flask_app.config.update(config)
    register_routes(flask_app, application.route_dependencies())
    return flask_app
