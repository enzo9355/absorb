"""Small, on-demand quote reads; never replace verified analysis inputs."""

import datetime as dt
import json
import math
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from zoneinfo import ZoneInfo

from stock_papi.shared.validation import is_us_ticker


def quote_symbol(code, info=None):
    if re.fullmatch(r"[0-9]{4,5}[0-9A-Z]?", code):
        exchange = getattr(info, "exchange", "") or getattr(info, "data_source", "")
        suffix = {"twse": ".TW", "tpex": ".TWO"}.get(str(exchange).lower())
        if suffix:
            return code + suffix
    elif is_us_ticker(code):
        return code
    raise ValueError("Unknown quote symbol or exchange")


def refresh_seconds(symbol, now):
    taiwan = symbol.endswith((".TW", ".TWO"))
    local = dt.datetime.fromtimestamp(now, ZoneInfo("Asia/Taipei" if taiwan else "America/New_York"))
    opening, closing = (540, 810) if taiwan else (570, 960)
    minute = local.hour * 60 + local.minute
    # shortcut: weekday sessions omit exchange holidays; add the official calendar if holiday traffic warrants it.
    if local.weekday() < 5:
        if opening <= minute < closing:
            return 60
        if minute < opening:
            return max(60, min(900, (opening - minute) * 60 - local.second))
    return 900


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Invalid quote number")
    return value


def parse_quote(payload, symbol, now):
    try:
        chart = payload["chart"]
        rows = chart["result"]
        if chart.get("error") or not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Invalid quote result")
        meta = rows[0]["meta"]
        currency = "TWD" if symbol.endswith((".TW", ".TWO")) else "USD"
        if meta["symbol"] != symbol or meta["currency"] != currency:
            raise ValueError("Quote identity mismatch")
        price = _positive(meta["regularMarketPrice"])
        previous = _positive(meta["chartPreviousClose"])
        timestamp = _positive(meta["regularMarketTime"])
        if timestamp > now + 300:
            raise ValueError("Future quote timestamp")
        quoted_at = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat().replace("+00:00", "Z")
        change_pct = (price / previous - 1) * 100
        if not math.isfinite(change_pct):
            raise ValueError("Invalid quote change")
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError, OSError) as exc:
        raise ValueError("Invalid quote document") from exc
    return {
        "status": "available", "symbol": symbol, "price": price,
        "change_pct": round(change_pct, 4), "currency": currency,
        "quoted_at": quoted_at, "source": "Yahoo Finance",
        "refresh_seconds": refresh_seconds(symbol, now),
    }


def fetch_quote(symbol):
    if not (is_us_ticker(symbol) or re.fullmatch(r"[0-9]{4,5}[0-9A-Z]?\.TW[O]?", symbol)):
        raise ValueError("Invalid provider symbol")
    request = urllib.request.Request(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("Quote response too large")
    return json.loads(raw)


class QuoteCache:
    def __init__(self, *, fetch=fetch_quote, now=time.time):
        self.fetch = fetch
        self.now = now
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.next_fetch = 0

    def get(self, symbol):
        unavailable = {"status": "unavailable", "refresh_seconds": 300}
        with self.cache_lock:
            entry = self.entries.get(symbol)
            if entry and self.now() < entry[0]:
                self.entries.move_to_end(symbol)
                return dict(entry[1])
        if not self.lock.acquire(blocking=False):
            return unavailable
        try:
            now = self.now()
            with self.cache_lock:
                entry = self.entries.get(symbol)
                if entry and now < entry[0]:
                    return dict(entry[1])
            # shortcut: deduplication and the upstream cap are per worker; use shared storage only if measured load requires it.
            if now < self.next_fetch:
                return unavailable
            self.next_fetch = now + 1
            try:
                result = parse_quote(self.fetch(symbol), symbol, self.now())
            except Exception:
                result = unavailable
            ttl = 60 if result["status"] == "available" else 300
            with self.cache_lock:
                self.entries[symbol] = (self.now() + ttl, dict(result))
                self.entries.move_to_end(symbol)
                while len(self.entries) > 256:
                    self.entries.popitem(last=False)
            return result
        finally:
            self.lock.release()
