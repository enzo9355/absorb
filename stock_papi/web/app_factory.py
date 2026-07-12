from collections.abc import Mapping
from typing import Any

from flask import Flask


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    from stock_papi import application

    if config:
        application.app.config.update(config)
    return application.app
