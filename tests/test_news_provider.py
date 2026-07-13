import unittest

import app as stock_app
from stock_papi.integrations.news import provider


class NewsProviderTests(unittest.TestCase):
    def test_compatibility_exports_use_canonical_provider_functions(self):
        self.assertIs(stock_app.fetch_news_rss, provider.fetch_news_rss)
        self.assertIs(stock_app.parse_news_items, provider.parse_news_items)
        self.assertIs(stock_app.parse_marketaux_items, provider.parse_marketaux_items)
        self.assertIs(stock_app.normalize_and_dedupe, provider.normalize_and_dedupe)


if __name__ == "__main__":
    unittest.main()
