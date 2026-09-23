import unittest
from flask import render_template
from tests.test_web_product import stock_app


class DualMarketLayoutTests(unittest.TestCase):
    def test_us_pages_share_tw_layout_and_preserve_missing_and_stale_data(self):
        summary = {
            'market': 'US', 'source_market_date': '2026-09-11',
            'applicable_trading_date': '2026-09-14', 'key_events': [],
            'executive_summary': {'one_line_conclusion': '已驗證摘要', 'largest_risk': '風險',
                                  'supporting_evidence': [], 'opposing_evidence': []},
            'market_observation': {'status': 'available', 'data': {
                'advancing_count': 0, 'declining_count': 10, 'unchanged_count': 0,
                'ma20_breadth_pct': 0, 'return_1d_pct': 0, 'return_5d_pct': -2.5}},
            'industries': {'status': 'available', 'data': {'ranking': [
                {'name': '科技', 'relative_return_5d_pct': 0, 'coverage': 0,
                 'available_count': 0, 'component_count': 10},
                {'name': '缺值產業', 'relative_return_5d_pct': None}]}},
            'securities': {'status': 'available', 'data': {}},
            'validation': {'status': 'unavailable', 'reason': '尚未驗證'},
        }
        for path, template, marker in (
            ('/us', 'us_dashboard.html', 'command-grid'),
            ('/us/market', 'us_market.html', 'market-grid'),
            ('/us/industries', 'us_industries.html', 'industry-disclosure'),
        ):
            with self.subTest(path=path), stock_app.app.test_request_context(path):
                html = render_template(template, summary=summary, market='US', index_predictions=[],
                    data_freshness={'US': {'status': 'stale', 'source_market_date': '2026-09-11'}})
                self.assertIn('data-theme="press-block"', html)
                self.assertIn(marker, html)
                self.assertIn('2026-09-11', html)
                self.assertIn('資料過期', html)
                self.assertNotIn('data-dashboard-endpoint="/api/dashboard"', html)
                self.assertNotIn('None', html)
                self.assertIn('0.0%', html)
                self.assertIn('尚未驗證', html)
                self.assertIn('href="/us/stocks"', html)
                self.assertIn('href="/reports/us"', html)
