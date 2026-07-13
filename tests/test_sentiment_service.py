import unittest

import app as stock_app
from stock_papi.services import sentiment


class SentimentServiceTests(unittest.TestCase):
    def test_root_exports_use_canonical_sentiment_functions(self):
        for name in (
            "score_news_item",
            "aggregate_news_sentiment",
            "analyze_sentiment_detail",
            "analyze_sentiment",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(stock_app, name), getattr(sentiment, name))

    def test_full_result_contract_is_stable(self):
        self.assertEqual(
            sentiment.analyze_sentiment_detail([]),
            {
                "score": 50.0,
                "status": "中性",
                "count": 0,
                "positive_ratio": 0.0,
                "negative_ratio": 0.0,
                "neutral_ratio": 0.0,
                "confidence_score": 0.0,
                "confidence": "低",
                "source_count": 0,
                "publisher_count": 0,
                "social_sample_size": 0,
                "weighted_volatility": 0.0,
                "momentum": 0.0,
                "momentum_data_sufficient": False,
                "disagreement": 0.0,
                "effective_sample_size": 0.0,
                "missing_metadata_ratio": 0.0,
                "extreme_score_flag": False,
                "window_days": 30,
                "items": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
