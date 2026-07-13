"""TWSE and TPEx market-activity adapters."""

import requests

from stock_papi.shared.formatting import safe_float as _safe_float


def fetch_market_activity():
    sources = (
        (
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            "Code", "TradeValue", "TradeVolume",
        ),
        (
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
            "SecuritiesCompanyCode", "TransactionAmount", "TradingShares",
        ),
    )
    activity = {}
    for url, code_field, value_field, volume_field in sources:
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get(code_field) or "").strip()
                if not code:
                    continue
                activity[code] = {
                    "trade_value": _safe_float(
                        str(row.get(value_field) or "0").replace(",", "")
                    ),
                    "trade_volume": _safe_float(
                        str(row.get(volume_field) or "0").replace(",", "")
                    ),
                }
        except (requests.RequestException, AttributeError, TypeError, ValueError):
            continue
    return activity
