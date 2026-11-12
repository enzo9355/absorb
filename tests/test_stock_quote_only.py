import unittest
from unittest.mock import patch

from tests.test_web_product import stock_app


class QuoteOnlyPageTests(unittest.TestCase):
    def setUp(self):
        self.client = stock_app.app.test_client()
        self.snapshot = patch.object(stock_app, 'fetch_published_quant_snapshot', return_value=None)
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.quote = {'status': 'available', 'symbol': 'GGLL', 'price': 72.61,
                      'change_pct': 4.2648, 'currency': 'USD',
                      'quoted_at': '2026-11-12T20:38:03Z', 'source': 'Yahoo Finance',
                      'refresh_seconds': 60}

    def test_search_for_uncovered_us_symbol_opens_quote_page(self):
        with patch('stock_papi.web.routes.market.QuoteCache.get', return_value=self.quote) as get:
            response = self.client.get('/search?market=US&q=ggll', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for expected in ('GGLL', '72.61', 'USD', 'Yahoo Finance', '完整觀察資料尚未提供',
                         'data-market="US"', 'data-stock-quote', 'stock-quote.js'):
            self.assertIn(expected, html)
        for excluded in ('查無資料', 'stock-chart-data', 'data-trade-plan', 'MA20'):
            self.assertNotIn(excluded, html)
        get.assert_called_once_with('GGLL')

    def test_provider_failure_has_retryable_page_without_invented_price(self):
        with patch('stock_papi.web.routes.market.QuoteCache.get',
                   return_value={'status': 'unavailable', 'refresh_seconds': 300}):
            response = self.client.get('/stock/GGLL')
        self.assertEqual(response.status_code, 503)
        html = response.get_data(as_text=True)
        self.assertIn('暫時無法取得報價', html)
        self.assertNotIn('72.61', html)
        self.assertIn('data-quote-price>—', html)
        self.assertEqual(response.headers['Retry-After'], '300')

    def test_invalid_symbol_does_not_fetch_quote(self):
        with patch('stock_papi.web.routes.market.QuoteCache.get') as get:
            response = self.client.get('/stock/GGLL%3Fx')
        self.assertEqual(response.status_code, 404)
        get.assert_not_called()
