"""Gunicorn entry point and temporary legacy compatibility facade."""

import sys

from stock_papi import application as _compatibility_module
from stock_papi.web.app_factory import create_app


_compatibility_module.app = create_app()
_compatibility_module.create_app = create_app
sys.modules[__name__] = _compatibility_module


if __name__ == "__main__":
    _compatibility_module.app.run(
        host=_compatibility_module.LOCAL_HOST,
        port=int(_compatibility_module.os.environ.get("PORT", 5000)),
    )
