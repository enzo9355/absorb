"""Gunicorn entry point and temporary legacy compatibility facade."""

import sys

from stock_papi import application as _compatibility_module
from stock_papi.web.app_factory import create_app


_compatibility_module.app = create_app()
sys.modules[__name__] = _compatibility_module
