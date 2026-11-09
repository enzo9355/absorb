import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from stock_papi.services.stock_quote import QuoteCache, parse_quote, quote_symbol, refresh_seconds


NOW = dt.datetime(2026, 11, 6, 2, 30, tzinfo=dt.timezone.utc).timestamp()


def document(symbol="2330.TW"):
    return {"chart": {"error": None, "result": [{"meta": {
        "symbol": symbol, "currency": "TWD" if symbol.endswith((".TW", ".TWO")) else "USD",
        "regularMarketPrice": 100.5, "regularMarketTime": NOW - 30,
        "chartPreviousClose": 100,
    }}]}}


class StockQuoteTests(unittest.TestCase):
    def test_symbol_mapping_requires_known_exchange(self):
        self.assertEqual(quote_symbol("2330", SimpleNamespace(exchange="TWSE")), "2330.TW")
        self.assertEqual(quote_symbol("6488", SimpleNamespace(data_source="tpex")), "6488.TWO")
        self.assertEqual(quote_symbol("AAPL"), "AAPL")
        self.assertEqual(quote_symbol("BRK-B"), "BRK-B")
        for symbol in ("2330", "../AAPL", "AAPL?x=1", "TAIEX", "A" * 11):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                quote_symbol(symbol)

    def test_quote_preserves_provider_time_and_change(self):
        result = parse_quote(document(), "2330.TW", NOW)
        self.assertEqual(result["price"], 100.5)
        self.assertAlmostEqual(result["change_pct"], 0.5)
        self.assertEqual(result["quoted_at"], "2026-11-06T02:29:30Z")
        self.assertEqual(result["currency"], "TWD")

    def test_rejects_invalid_quote(self):
        for field, value in [
            ("symbol", "AAPL"), ("currency", "USD"), ("regularMarketPrice", float("nan")),
            ("regularMarketPrice", -1), ("regularMarketPrice", True),
            ("regularMarketTime", NOW + 3600), ("regularMarketTime", 0),
            ("chartPreviousClose", 0),
        ]:
            payload = document()
            payload["chart"]["result"][0]["meta"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                parse_quote(payload, "2330.TW", NOW)

    def test_rejects_malformed_document(self):
        for payload in [None, {}, {"chart": {"result": []}}, {"chart": {"error": {"code": "bad"}}}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_quote(payload, "2330.TW", NOW)

    def test_market_hours_include_dst_and_weekends(self):
        stamp = lambda value: dt.datetime.fromisoformat(value).timestamp()
        self.assertEqual(refresh_seconds("2330.TW", NOW), 60)
        self.assertEqual(refresh_seconds("2330.TW", stamp("2026-11-07T02:30:00+00:00")), 900)
        self.assertEqual(refresh_seconds("AAPL", stamp("2026-11-06T14:35:00+00:00")), 60)
        self.assertEqual(refresh_seconds("AAPL", stamp("2026-07-06T13:35:00+00:00")), 60)
        self.assertEqual(refresh_seconds("AAPL", NOW), 900)

    def test_cache_reuses_quote_and_expires_without_mutating_previous_result(self):
        clock = Mock(return_value=NOW)
        fetch = Mock(side_effect=lambda symbol: document(symbol))
        cache = QuoteCache(fetch=fetch, now=clock)
        first = cache.get("2330.TW")
        first["price"] = -1
        self.assertEqual(cache.get("2330.TW")["price"], 100.5)
        fetch.assert_called_once()
        clock.return_value += 61
        self.assertEqual(cache.get("2330.TW")["status"], "available")
        self.assertEqual(fetch.call_count, 2)

    def test_failure_is_cached_and_does_not_expose_upstream_error(self):
        clock = Mock(return_value=NOW)
        fetch = Mock(side_effect=RuntimeError("private upstream URL"))
        cache = QuoteCache(fetch=fetch, now=clock)
        result = cache.get("AAPL")
        self.assertEqual(result, {"status": "unavailable", "refresh_seconds": 300})
        clock.return_value += 61
        self.assertEqual(cache.get("AAPL"), result)
        fetch.assert_called_once()

    def test_busy_worker_does_not_queue_upstream_requests(self):
        fetch = Mock()
        cache = QuoteCache(fetch=fetch, now=lambda: NOW)
        with cache.lock:
            self.assertEqual(cache.get("AAPL")["status"], "unavailable")
        fetch.assert_not_called()

    def test_cold_symbol_burst_is_limited(self):
        fetch = Mock(side_effect=lambda symbol: document(symbol))
        cache = QuoteCache(fetch=fetch, now=lambda: NOW)
        self.assertEqual(cache.get("AAPL")["status"], "available")
        self.assertEqual(cache.get("MSFT")["status"], "unavailable")
        self.assertEqual(fetch.call_count, 1)

    def test_valid_cache_remains_available_while_another_quote_is_fetching(self):
        fetch = Mock(side_effect=lambda symbol: document(symbol))
        cache = QuoteCache(fetch=fetch, now=lambda: NOW)
        cache.get("AAPL")
        with cache.lock:
            self.assertEqual(cache.get("AAPL")["status"], "available")
        fetch.assert_called_once()

    def test_cache_has_a_fixed_memory_bound(self):
        clock = Mock(return_value=NOW)
        cache = QuoteCache(fetch=lambda symbol: document(symbol), now=clock)
        for number in range(300):
            cache.get(f"A{number}")
            clock.return_value += 2
        self.assertEqual(len(cache.entries), 256)
