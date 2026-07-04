import datetime
import json
import os
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app


def sample_analysis_data(news=None):
    return {
        "name": "台積電",
        "code": "2330",
        "price": 100.0,
        "prob": 55,
        "bt": {
            "days": 30,
            "accuracy": 52.5,
            "brier": 0.24,
            "strat_cum": 1.0,
            "bh_cum": 0.5,
            "win_rate": 55.0,
            "trades": 4,
            "mdd": -2.0,
            "sharpe": 0.8,
            "conclusion": "test",
            "top_features": ["a", "b", "c"],
        },
        "news": news or [],
        "trend": "多頭",
        "rsi": 55.0,
        "ma20": 99.0,
        "macd_osc": 0.1,
        "k": 60.0,
        "d": 50.0,
        "s_score": 50.0,
        "s_status": "中性",
        "candles": "[]",
        "ma20_line": "[]",
        "prob_h": "[]",
        "pred": "[]",
    }


class PredictionPipelineTests(unittest.TestCase):
    def test_search_stock_code_accepts_standard_us_tickers(self):
        self.assertEqual(stock_app.search_stock_code("aapl"), ("AAPL", "美股 AAPL"))
        self.assertEqual(stock_app._resolve_postback_stock("AAPL"), ("AAPL", "美股 AAPL"))
        self.assertFalse(stock_app.is_us_ticker("TAIEX"))
        self.assertEqual(stock_app.search_stock_code("TOOLONG"), (None, None))

    @patch("app.fetch_option_context_history", return_value=(pd.DataFrame(),) * 3)
    @patch("app.fetch_yfinance_price_history")
    @patch("app.fetch_finmind_dataset")
    def test_get_data_uses_us_market_context_without_finmind(
        self, finmind, yf_history, _option_history
    ):
        dates = pd.date_range("2025-01-01", periods=220, freq="B")

        def frame(start):
            close = np.arange(start, start + len(dates), dtype=float)
            return pd.DataFrame({
                "Date": dates,
                "Open": close - 1,
                "High": close + 1,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(len(dates), 1_000_000),
            })

        yf_history.side_effect = [frame(100), frame(5000), frame(500)]

        result = stock_app.get_data("AAPL", days=400)

        finmind.assert_not_called()
        self.assertEqual([call.args[0] for call in yf_history.call_args_list], ["AAPL", "^GSPC", "SPY"])
        self.assertEqual(len(result), 220)
        self.assertTrue((result["ForeignNet"] == 0).all())
        self.assertIn("MARKET_RET_5", result)

    def test_broadcast_endpoint_is_disabled_without_token_configuration(self):
        previous = stock_app.BROADCAST_TOKEN
        self.addCleanup(setattr, stock_app, "BROADCAST_TOKEN", previous)
        stock_app.BROADCAST_TOKEN = None

        with patch.object(stock_app, "analyze") as analyze:
            response = stock_app.app.test_client().get("/broadcast_weekly")

        self.assertEqual(response.status_code, 503)
        analyze.assert_not_called()

    def test_last_five_rows_have_no_training_target(self):
        frame = pd.DataFrame({"Close": np.arange(1.0, 21.0)})

        result = stock_app.add_prediction_target(frame)

        horizon = stock_app.PREDICTION_HORIZON
        self.assertTrue(result["FUTURE_RET_5"].tail(horizon).isna().all())
        self.assertTrue(result["T"].tail(horizon).isna().all())
        self.assertEqual(int(result["T"].notna().sum()), 15)

    def test_walk_forward_splits_keep_five_row_gap(self):
        for train, test in stock_app.build_time_splits(120):
            self.assertLess(train[-1], test[0])
            self.assertGreaterEqual(
                test[0] - train[-1] - 1,
                stock_app.PREDICTION_HORIZON,
            )

    def test_backtest_uses_five_day_returns_and_cost(self):
        future = pd.Series([0.02] * 10)
        probabilities = pd.Series([0.7] * 10)

        metrics = stock_app.score_oos_predictions(future, probabilities)

        expected = (
            (1 + 0.02 - stock_app.ROUND_TRIP_COST) ** 2 - 1
        ) * 100
        self.assertAlmostEqual(metrics["strat_cum"], expected, places=8)
        self.assertEqual(metrics["trades"], 2)

    def test_missing_chip_data_falls_back_to_neutral_features(self):
        close = np.linspace(50, 80, 100) + np.sin(np.arange(100))
        frame = pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 0.5,
                "Low": close - 0.5,
                "Close": close,
                "Volume": np.linspace(1000, 2000, 100),
            }
        )

        result = stock_app.calc_all(frame)

        columns = ["VOL_RATIO", "INST_NET_RATIO", "MARGIN_CHG", "SHORT_CHG"]
        self.assertFalse(result[columns].isna().any().any())
        self.assertTrue(np.isfinite(result[columns].to_numpy()).all())
        self.assertTrue((result[["INST_NET_RATIO", "MARGIN_CHG", "SHORT_CHG"]] == 0).all().all())

    def test_add_market_context_features_aligns_by_date(self):
        dates = pd.to_datetime(
            ["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]
        )
        stock = pd.DataFrame(
            {
                "Date": dates,
                "Open": [100, 101, 102, 103, 104],
                "High": [101, 102, 103, 104, 105],
                "Low": [99, 100, 101, 102, 103],
                "Close": [100, 102, 101, 103, 106],
                "Volume": [1000, 1100, 1050, 1200, 1300],
            }
        )
        market = pd.DataFrame({"Date": dates, "Close": [200, 202, 204, 206, 208]})
        etf = pd.DataFrame({"Date": dates, "Close": [50, 51, 52, 51, 53]})

        result = stock_app.add_market_context_features(stock, market, etf)

        self.assertIn("MARKET_RET_1", result)
        self.assertIn("ETF50_RET_5", result)
        self.assertIn("STOCK_VS_MARKET_5", result)
        self.assertFalse(result[["MARKET_RET_1", "STOCK_VS_MARKET_5"]].isna().any().any())

    def test_add_market_context_features_is_neutral_without_market_data(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-03"])
        stock = pd.DataFrame(
            {
                "Date": dates,
                "Open": [100, 101],
                "High": [101, 102],
                "Low": [99, 100],
                "Close": [100, 102],
                "Volume": [1000, 1100],
            }
        )

        result = stock_app.add_market_context_features(stock, pd.DataFrame(), pd.DataFrame())

        for column in stock_app.MARKET_FEATURES:
            self.assertIn(column, result)
            self.assertEqual(result[column].tolist(), [0.0, 0.0])

    def test_option_context_uses_only_same_or_earlier_dates(self):
        price = pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "Close": [100.0, 101.0],
        })
        vix = pd.DataFrame({
            "Date": pd.Series(pd.to_datetime(["2026-01-02", "2026-01-07"])).astype(
                "datetime64[s]"
            ),
            "Close": [20.0, 99.0],
        })
        vix9d = pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-02"]),
            "Close": [24.0],
        })
        vix3m = pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-02"]),
            "Close": [18.0],
        })

        result = stock_app.add_option_context_features(price, vix, vix9d, vix3m)

        self.assertEqual(result["OPTION_IV_LEVEL"].tolist(), [0.2, 0.2])
        self.assertTrue(
            np.allclose(result["OPTION_IV_TERM_9D_3M"], (24.0 / 18.0) - 1.0)
        )
        self.assertEqual(result["OPTION_DATA_MISSING"].tolist(), [0.0, 0.0])

    def test_option_context_returns_neutral_values_when_missing(self):
        price = pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "Close": [100.0, 101.0],
        })

        result = stock_app.add_option_context_features(price)

        self.assertTrue((result[stock_app.OPTION_FEATURES[:-1]] == 0.0).all().all())
        self.assertEqual(result["OPTION_DATA_MISSING"].tolist(), [1.0, 1.0])

    @patch("app.fetch_yfinance_price_history")
    def test_fetch_option_context_history_requests_three_cboe_indexes(self, fetch):
        fetch.return_value = pd.DataFrame()

        result = stock_app.fetch_option_context_history("2025-01-01", "2026-01-01")

        self.assertEqual(len(result), 3)
        self.assertEqual(
            {call.args[0] for call in fetch.call_args_list},
            {"^VIX", "^VIX9D", "^VIX3M"},
        )

    def test_add_price_quality_features_flags_large_close_gap(self):
        dates = pd.to_datetime(
            ["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]
        )
        price = pd.DataFrame(
            {
                "Date": dates,
                "Open": [100, 100, 100, 100, 100],
                "High": [101, 101, 101, 101, 101],
                "Low": [99, 99, 99, 99, 99],
                "Close": [100, 100, 100, 100, 100],
                "Volume": [1000, 1000, 1000, 1000, 1000],
            }
        )
        yf_price = pd.DataFrame({"Date": dates, "Close": [110, 110, 110, 110, 110]})

        result = stock_app.add_price_quality_features(price, yf_price)

        self.assertEqual(result["DATA_PRICE_WARNING"].iloc[-1], 1.0)
        self.assertGreater(result["DATA_PRICE_DIFF_PCT"].iloc[-1], 0.09)
        self.assertEqual(result["YF_CLOSE"].iloc[-1], 110)

    def test_add_price_quality_features_is_neutral_without_yfinance(self):
        price = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-01-02"]),
                "Open": [100],
                "High": [101],
                "Low": [99],
                "Close": [100],
                "Volume": [1000],
            }
        )

        result = stock_app.add_price_quality_features(price, pd.DataFrame())

        self.assertEqual(result["DATA_PRICE_WARNING"].iloc[-1], 0.0)
        self.assertEqual(result["DATA_PRICE_DIFF_PCT"].iloc[-1], 0.0)

    def test_chip_data_is_aggregated_by_trading_date(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
        price = pd.DataFrame({"Date": dates, "Close": [100.0, 101.0]})
        institutional = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-02"],
                "buy": [1000, 500],
                "sell": [200, 100],
            }
        )
        margin = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-05"],
                "MarginPurchaseTodayBalance": [3000, 3300],
                "ShortSaleTodayBalance": [100, 120],
            }
        )

        result = stock_app.merge_chip_data(price, institutional, margin)

        self.assertEqual(result.loc[0, "InstitutionalNet"], 1200)
        self.assertEqual(result.loc[1, "InstitutionalNet"], 0)
        self.assertEqual(result.loc[1, "MarginBalance"], 3300)
        self.assertEqual(result.loc[1, "ShortBalance"], 120)

    def test_investment_projection_calculates_shares_profit_and_annualized_return(self):
        result = stock_app.calculate_investment_projection(
            100000,
            {"price": 100.0, "bt": {"strat_cum": 8.0, "bh_cum": 5.0, "days": 252}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["shares"], 1000)
        self.assertEqual(result["deployed_amount"], 100000)
        self.assertAlmostEqual(result["strategy_profit"], 8000)
        self.assertAlmostEqual(result["buy_hold_profit"], 5000)
        self.assertAlmostEqual(result["strategy_annualized"], 8.0)

    def test_investment_projection_rejects_amount_too_small_for_one_share(self):
        result = stock_app.calculate_investment_projection(
            50,
            {"price": 100.0, "bt": {"strat_cum": 8.0, "bh_cum": 5.0, "days": 252}},
        )

        self.assertFalse(result["ok"])

    def test_merge_chip_data_prefers_foreign_flow_when_available(self):
        price = pd.DataFrame({"Date": pd.to_datetime(["2026-01-02"]), "Close": [100.0]})
        institutional = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-02"],
                "name": ["Foreign_Dealer", "Investment_Trust"],
                "buy": [1000, 500],
                "sell": [200, 100],
            }
        )

        result = stock_app.merge_chip_data(price, institutional)

        self.assertEqual(result.loc[0, "InstitutionalNet"], 1200)
        self.assertEqual(result.loc[0, "ForeignNet"], 800)

    def test_foreign_flow_summary_reports_status_and_missing_data(self):
        positive = stock_app.summarize_foreign_flow(pd.DataFrame({"ForeignNet": [100.0] * 20}))
        missing = stock_app.summarize_foreign_flow(pd.DataFrame({"ForeignNet": [0.0] * 20}))

        self.assertEqual(positive["status"], "外資偏多")
        self.assertFalse(missing["available"])

    @patch("app.requests.get")
    def test_finmind_dataset_fetch_uses_existing_token(self, get):
        get.return_value = Mock(json=lambda: {"data": [{"value": 1}]})
        previous_token = stock_app.finmind_token
        stock_app.finmind_token = "token"
        self.addCleanup(setattr, stock_app, "finmind_token", previous_token)

        result = stock_app.fetch_finmind_dataset(
            "DatasetName",
            "2330",
            "2026-01-01",
            "2026-01-31",
        )

        self.assertEqual(result.to_dict("records"), [{"value": 1}])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["dataset"], "DatasetName")
        self.assertEqual(params["token"], "token")

    @patch("app.fetch_option_context_history", return_value=(pd.DataFrame(),) * 3)
    @patch("app.requests.get", side_effect=AssertionError("legacy request path"))
    @patch("app.fetch_yfinance_price_history")
    @patch("app.fetch_finmind_dataset")
    def test_get_data_preserves_volume_and_chip_columns(
        self, fetch, yf_history, _get, _option_history
    ):
        yf_history.return_value = pd.DataFrame()
        fetch.side_effect = [
            pd.DataFrame(
                {
                    "date": ["2026-01-02", "2026-01-05"],
                    "open": [100, 101],
                    "max": [102, 103],
                    "min": [99, 100],
                    "close": [101, 102],
                    "Trading_Volume": [10000, 12000],
                }
            ),
            pd.DataFrame(
                {
                    "date": ["2026-01-02"],
                    "buy": [2000],
                    "sell": [500],
                }
            ),
            pd.DataFrame(
                {
                    "date": ["2026-01-02", "2026-01-05"],
                    "MarginPurchaseTodayBalance": [3000, 3100],
                    "ShortSaleTodayBalance": [100, 90],
                }
            ),
        ]

        result = stock_app.get_data("2330", days=10)

        self.assertEqual(result["Volume"].tolist(), [10000, 12000])
        self.assertEqual(result["InstitutionalNet"].tolist(), [1500, 0])
        self.assertEqual(result["MarginBalance"].tolist(), [3000, 3100])

    @patch("app.fetch_option_context_history", return_value=(pd.DataFrame(),) * 3)
    @patch("app.fetch_yfinance_price_history")
    @patch("app.fetch_finmind_dataset")
    def test_get_data_adds_market_and_price_quality_columns(
        self, finmind, yf_history, _option_history
    ):
        dates = pd.to_datetime(
            ["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]
        )
        finmind.side_effect = [
            pd.DataFrame(
                {
                    "date": dates.strftime("%Y-%m-%d"),
                    "open": [100, 101, 102, 103, 104],
                    "max": [101, 102, 103, 104, 105],
                    "min": [99, 100, 101, 102, 103],
                    "close": [100, 102, 101, 103, 106],
                    "Trading_Volume": [1000, 1100, 1050, 1200, 1300],
                }
            ),
            pd.DataFrame(),
            pd.DataFrame(),
        ]
        yf_history.side_effect = [
            pd.DataFrame(
                {
                    "Date": dates,
                    "Open": [100] * 5,
                    "High": [101] * 5,
                    "Low": [99] * 5,
                    "Close": [100, 101, 102, 103, 104],
                    "Volume": [1] * 5,
                }
            ),
            pd.DataFrame(
                {
                    "Date": dates,
                    "Open": [200] * 5,
                    "High": [201] * 5,
                    "Low": [199] * 5,
                    "Close": [200, 202, 204, 206, 208],
                    "Volume": [1] * 5,
                }
            ),
            pd.DataFrame(
                {
                    "Date": dates,
                    "Open": [50] * 5,
                    "High": [51] * 5,
                    "Low": [49] * 5,
                    "Close": [50, 51, 52, 51, 53],
                    "Volume": [1] * 5,
                }
            ),
        ]

        result = stock_app.get_data("2330", days=10)

        for column in (
            stock_app.MARKET_FEATURES
            + stock_app.OPTION_FEATURES
            + stock_app.DATA_QUALITY_FEATURES
        ):
            self.assertIn(column, result.columns)
        self.assertIn("YF_CLOSE", result.columns)

    def test_model_features_include_market_and_data_quality_features(self):
        for column in (
            stock_app.MARKET_FEATURES
            + stock_app.OPTION_FEATURES
            + stock_app.DATA_QUALITY_FEATURES
        ):
            self.assertIn(column, stock_app.MODEL_FEATURES)

    def test_calc_all_preserves_market_and_data_quality_features(self):
        dates = pd.date_range("2026-01-01", periods=80, freq="D")
        raw = pd.DataFrame(
            {
                "Date": dates,
                "Open": np.linspace(100, 180, len(dates)),
                "High": np.linspace(101, 181, len(dates)),
                "Low": np.linspace(99, 179, len(dates)),
                "Close": np.linspace(100, 180, len(dates)),
                "Volume": np.linspace(1000, 2000, len(dates)),
            }
        )
        for column in (
            stock_app.MARKET_FEATURES
            + stock_app.OPTION_FEATURES
            + stock_app.DATA_QUALITY_FEATURES
        ):
            raw[column] = 0.1

        result = stock_app.calc_all(raw)

        for column in (
            stock_app.MARKET_FEATURES
            + stock_app.OPTION_FEATURES
            + stock_app.DATA_QUALITY_FEATURES
        ):
            self.assertIn(column, result.columns)

    def test_walk_forward_engine_returns_oos_metrics_and_current_probability(self):
        x = np.arange(260)
        close = 100 + x * 0.04 + np.sin(x / 4) * 4
        raw = pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 0.8,
                "Low": close - 0.8,
                "Close": close,
                "Volume": 1000 + (x % 30) * 20,
            }
        )
        enriched = stock_app.calc_all(raw)

        metrics = stock_app.run_ai_engine(enriched)

        self.assertIsNotNone(metrics)
        self.assertIn("accuracy", metrics)
        self.assertIn("brier", metrics)
        self.assertTrue(0 <= enriched["AI_P"].iloc[-1] <= 100)
        self.assertGreater(enriched["AI_P"].notna().sum(), 1)

    def test_news_sentiment_does_not_mutate_model_probability(self):
        index = pd.date_range("2025-01-01", periods=200, freq="B")
        frame = pd.DataFrame(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "MA20": 99.0,
                "RSI": 55.0,
                "Volat": 0.02,
                "MACD_OSC": 0.1,
                "K": 60.0,
                "D": 50.0,
                "AI_P": [np.nan] * 199 + [55.0],
            },
            index=index,
        )
        frame.index.name = "Date"
        backtest = {
            "days": 30,
            "accuracy": 50.0,
            "brier": 0.25,
            "strat_cum": 0.0,
            "bh_cum": 0.0,
            "win_rate": 0.0,
            "trades": 0,
            "mdd": 0.0,
            "sharpe": 0.0,
            "conclusion": "test",
            "top_features": ["a", "b", "c"],
        }
        with (
            patch.object(stock_app, "get_data", return_value=frame),
            patch.object(stock_app, "calc_all", return_value=frame),
            patch.object(stock_app, "run_ai_engine", return_value=backtest),
            patch.object(stock_app, "get_news", return_value=[{
                "title": "營收創新高",
                "link": "#",
                "source": "財經報",
                "published_at": "2026-06-27T00:00:00+00:00",
                "age_hours": 1,
            }]) as get_news,
            patch.object(stock_app, "analyze_sentiment", return_value=(80, "樂觀")),
        ):
            result = stock_app._do_analyze("2330")

        self.assertEqual(result["prob"], 55)
        self.assertEqual(len(json.loads(result["prob_h"])), 1)
        self.assertIn("news_neutral_ratio", result)
        self.assertIn("news_confidence", result)
        self.assertEqual(result["news"][0]["direction"], "positive")
        get_news.assert_called_once_with("台積電", "2330")

    def test_analyze_sentiment_returns_breakdown_without_model_side_effects(self):
        news = [
            {"title": "台積電營收創新高 外資看好", "link": "#"},
            {"title": "半導體需求保守 股價下修", "link": "#"},
        ]

        result = stock_app.analyze_sentiment_detail(news)

        self.assertEqual(result["count"], 2)
        self.assertIn("score", result)
        self.assertIn("negative_ratio", result)
        self.assertIn("positive_ratio", result)
        self.assertIn("status", result)

    def test_analyze_sentiment_keeps_legacy_tuple_api(self):
        score, status = stock_app.analyze_sentiment([])

        self.assertEqual(score, 50)
        self.assertEqual(status, "中性")

    def test_parse_news_items_preserves_metadata_and_missing_flags(self):
        xml = """<rss><channel>
          <item><title>台積電營收創新高 - 財經報</title><link>https://a</link><source>財經報</source><pubDate>Fri, 27 Jun 2026 00:00:00 GMT</pubDate></item>
          <item><title>台積電營收創新高</title><link>https://b</link></item>
        </channel></rss>"""
        now = datetime.datetime(2026, 6, 27, 8, tzinfo=datetime.timezone.utc)

        items = stock_app.parse_news_items(xml, now=now)
        deduped = stock_app.normalize_and_dedupe(items)

        self.assertEqual(items[0]["source"], "財經報")
        self.assertEqual(items[0]["published_at"], "2026-06-27T00:00:00+00:00")
        self.assertEqual(items[0]["age_hours"], 8.0)
        self.assertTrue(items[1]["parse_flags"]["missing_source"])
        self.assertTrue(items[1]["parse_flags"]["missing_published_at"])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["normalized_title"], "台積電營收創新高")
        self.assertEqual(deduped[0]["duplicate_count"], 1)

    def test_marketaux_news_is_optional_and_preserves_external_sentiment(self):
        previous = getattr(stock_app, "MARKETAUX_API_TOKEN", None)
        self.addCleanup(setattr, stock_app, "MARKETAUX_API_TOKEN", previous)
        stock_app.MARKETAUX_API_TOKEN = None

        with patch.object(stock_app.requests, "get") as get:
            self.assertEqual(stock_app.fetch_marketaux_news("台積電"), [])
        get.assert_not_called()

        stock_app.MARKETAUX_API_TOKEN = "test-token"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{
            "title": "台積電營收創新高",
            "url": "https://example.com/marketaux",
            "source": "測試財經報",
            "published_at": "2026-06-30T00:00:00.000000Z",
            "entities": [{"sentiment_score": 0.72}],
        }]}
        with patch.object(stock_app.requests, "get", return_value=response) as get:
            items = stock_app.fetch_marketaux_news("台積電")

        self.assertEqual(items[0]["source"], "測試財經報")
        self.assertEqual(items[0]["external_sentiment_score"], 0.72)
        self.assertEqual(items[0]["provider"], "marketaux")
        self.assertEqual(get.call_args.kwargs["timeout"], 5)
        self.assertNotIn("test-token", str(items))

    def test_marketaux_news_malformed_response_fails_closed(self):
        previous = getattr(stock_app, "MARKETAUX_API_TOKEN", None)
        self.addCleanup(setattr, stock_app, "MARKETAUX_API_TOKEN", previous)
        stock_app.MARKETAUX_API_TOKEN = "test-token"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = []

        with patch.object(stock_app.requests, "get", return_value=response):
            self.assertEqual(stock_app.fetch_marketaux_news("台積電"), [])

    def test_parse_stocktwits_sentiment_builds_anonymous_30_day_summary(self):
        now = datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc)
        payload = {"messages": [
            {
                "created_at": "2026-07-03T00:00:00Z",
                "entities": {"sentiment": {"basic": "Bullish"}},
                "user": {"username": "should-not-leak"},
                "body": "full post should not be retained",
            },
            {
                "created_at": "2026-07-02T00:00:00Z",
                "entities": {"sentiment": {"basic": "Bearish"}},
            },
            {
                "created_at": "2026-05-01T00:00:00Z",
                "entities": {"sentiment": {"basic": "Bullish"}},
            },
            {
                "created_at": "2026-07-01T00:00:00Z",
                "entities": {"sentiment": None},
            },
        ]}

        items = stock_app.parse_stocktwits_sentiment(payload, "AAPL", now=now)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["social_sample_size"], 2)
        self.assertEqual(items[0]["external_sentiment_score"], 0)
        self.assertEqual(items[0]["provider"], "stocktwits")
        self.assertNotIn("author", items[0])
        self.assertNotIn("body", items[0])

    def test_stocktwits_fetch_skips_non_us_ticker(self):
        with patch.object(stock_app.requests, "get") as get:
            result = stock_app.fetch_stocktwits_sentiment("2330")

        self.assertEqual(result, [])
        get.assert_not_called()

    def test_stocktwits_fetch_fails_closed_on_request_error(self):
        with patch.object(
            stock_app.requests,
            "get",
            side_effect=stock_app.requests.RequestException("offline"),
        ):
            result = stock_app.fetch_stocktwits_sentiment("AAPL")

        self.assertEqual(result, [])

    def test_get_news_merges_and_deduplicates_optional_marketaux_items(self):
        xml = """<rss><channel><item>
          <title>台積電營收創新高 - 財經報</title>
          <link>https://example.com/google</link><source>財經報</source>
        </item></channel></rss>"""
        marketaux_item = {
            "title": "台積電營收創新高",
            "normalized_title": "台積電營收創新高",
            "link": "https://example.com/marketaux",
            "source": "MarketAux",
            "published_at": None,
            "age_hours": None,
            "parse_flags": {"missing_source": False, "missing_published_at": True},
            "duplicate_count": 0,
            "provider": "marketaux",
        }

        with patch.object(stock_app, "fetch_news_rss", return_value=xml), \
             patch.object(stock_app, "fetch_marketaux_news", return_value=[marketaux_item]):
            items = stock_app.get_news("台積電")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["duplicate_count"], 1)

    def test_get_news_keeps_one_social_summary_and_filters_old_news(self):
        xml = """<rss><channel>
          <item><title>新消息一</title><link>https://example.com/1</link><source>財經報</source><pubDate>Fri, 03 Jul 2026 00:00:00 GMT</pubDate></item>
          <item><title>新消息二</title><link>https://example.com/2</link><source>財經報</source><pubDate>Thu, 02 Jul 2026 00:00:00 GMT</pubDate></item>
          <item><title>新消息三</title><link>https://example.com/3</link><source>財經報</source><pubDate>Wed, 01 Jul 2026 00:00:00 GMT</pubDate></item>
          <item><title>新消息四</title><link>https://example.com/4</link><source>財經報</source><pubDate>Tue, 30 Jun 2026 00:00:00 GMT</pubDate></item>
          <item><title>新消息五</title><link>https://example.com/5</link><source>財經報</source><pubDate>Mon, 29 Jun 2026 00:00:00 GMT</pubDate></item>
          <item><title>過期消息</title><link>https://example.com/old</link><source>財經報</source><pubDate>Fri, 01 May 2026 00:00:00 GMT</pubDate></item>
        </channel></rss>"""
        social = {
            "title": "AAPL StockTwits 近 30 日多方 8、空方 2",
            "normalized_title": "AAPL StockTwits 近 30 日多方 8、空方 2",
            "link": "https://stocktwits.com/symbol/AAPL",
            "source": "StockTwits",
            "published_at": "2026-07-03T00:00:00+00:00",
            "age_hours": 24,
            "parse_flags": {"missing_source": False, "missing_published_at": False},
            "duplicate_count": 0,
            "provider": "stocktwits",
            "external_sentiment_score": 0.6,
            "social_sample_size": 10,
        }

        with patch.object(stock_app, "fetch_news_rss", return_value=xml), \
             patch.object(stock_app, "fetch_marketaux_news", return_value=[]), \
             patch.object(stock_app, "fetch_stocktwits_sentiment", return_value=[social]), \
             patch.object(stock_app.datetime, "datetime", wraps=datetime.datetime) as dt:
            dt.now.return_value = datetime.datetime(
                2026, 7, 4, tzinfo=datetime.timezone.utc
            )
            items = stock_app.get_news("美股 AAPL", "AAPL")

        self.assertEqual(len(items), 5)
        self.assertEqual(sum(item.get("provider") == "stocktwits" for item in items), 1)
        self.assertNotIn("過期消息", [item["normalized_title"] for item in items])

    def test_score_news_item_handles_negation_and_weights(self):
        positive = stock_app.score_news_item({
            "title": "法人看好營收創新高",
            "source": "財經報",
            "age_hours": 2,
            "parse_flags": {},
        })
        negated = stock_app.score_news_item({
            "title": "法人不看好後市",
            "source": None,
            "age_hours": None,
            "parse_flags": {},
        })

        self.assertGreater(positive["raw_score"], 0)
        self.assertLessEqual(negated["raw_score"], 0)
        self.assertEqual(positive["event_type"], "major")
        self.assertIn("不看好", negated["matched_negations"])
        self.assertGreater(positive["final_weight"], negated["final_weight"])

    def test_stocktwits_direction_is_dampened_and_weight_capped(self):
        scored = stock_app.score_news_item({
            "title": "AAPL StockTwits 近 30 日多方 8、空方 2",
            "provider": "stocktwits",
            "source": "StockTwits",
            "external_sentiment_score": 0.6,
            "social_sample_size": 10,
            "age_hours": 1,
            "parse_flags": {},
        })

        self.assertAlmostEqual(scored["raw_score"], 0.36)
        self.assertEqual(scored["event_type"], "opinion")
        self.assertLess(scored["source_weight"], 1)
        self.assertLessEqual(scored["engagement_weight"], 1)
        self.assertGreaterEqual(scored["engagement_weight"], 0.7)

    def test_aggregate_reports_source_and_social_coverage(self):
        result = stock_app.analyze_sentiment_detail([
            {
                "title": "營收創新高",
                "source": "財經報",
                "provider": "news",
                "age_hours": 1,
            },
            {
                "title": "AAPL StockTwits 近 30 日多方 8、空方 2",
                "source": "StockTwits",
                "provider": "stocktwits",
                "external_sentiment_score": 0.6,
                "social_sample_size": 10,
                "age_hours": 1,
            },
        ])

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["social_sample_size"], 10)
        self.assertEqual(result["window_days"], 30)

    def test_aggregate_news_sentiment_returns_five_levels_and_confidence(self):
        result = stock_app.aggregate_news_sentiment([
            {
                "raw_score": 1.0,
                "final_weight": 1.0,
                "direction": "positive",
                "source": "財經報",
                "age_hours": 1,
            }
            for _ in range(5)
        ])
        empty = stock_app.aggregate_news_sentiment([])

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["status"], "極度偏多")
        self.assertEqual(result["positive_ratio"], 1)
        self.assertEqual(result["neutral_ratio"], 0)
        self.assertEqual(result["confidence"], "高")
        self.assertEqual(empty["score"], 50)
        self.assertEqual(empty["status"], "中性")
        self.assertEqual(empty["confidence"], "低")

    def test_web_and_line_messages_name_the_five_day_probability(self):
        data = sample_analysis_data()

        with stock_app.app.app_context():
            html = stock_app.render_web(data)
        flex = stock_app.build_stock_flex_message(
            "2330", "台積電", data, "https://example.com"
        )
        rendered = html + json.dumps(flex, ensure_ascii=False)

        self.assertIn("五日上漲機率", rendered)
        self.assertIn("五日方向準確率", html)
        self.assertIn("Brier Score", html)
        self.assertNotIn("AI 勝率", rendered)

    def test_line_and_web_render_sentiment_breakdown(self):
        data = sample_analysis_data([{
            "title": "台積電營收創新高 - 財經報",
            "normalized_title": "台積電營收創新高",
            "link": "https://example.com/news",
            "source": "財經報",
            "published_at": "2026-06-27T00:00:00+00:00",
            "direction": "positive",
            "matched_positive_terms": ["新高"],
        }])
        data.update({
            "s_score": 68.0,
            "s_status": "偏多",
            "news_count": 12,
            "news_positive_ratio": 0.58,
            "news_negative_ratio": 0.17,
            "news_neutral_ratio": 0.25,
            "news_confidence": "中",
            "news_confidence_score": 64.0,
            "news_source_count": 2,
            "social_sample_size": 10,
            "sentiment_window_days": 30,
            "projection": {"ok": False},
            "foreign_flow": {
                "status": "資料不足",
                "available": False,
                "source": "無資料",
                "net_5": 0,
                "net_20": 0,
            },
        })

        with stock_app.app.test_request_context("/stock/2330"):
            html = stock_app.render_web(data)
            template_html = stock_app.render_template("stock_detail.html", d=data)
        flex = stock_app.build_stock_flex_message(
            "2330", "台積電", data, "https://example.com"
        )
        rendered = html + template_html + json.dumps(flex, ensure_ascii=False)

        self.assertIn("新聞／輿論情緒", rendered)
        self.assertIn("12 則｜2 個來源｜社群 10 則", rendered)
        self.assertIn("近期新聞與輿論", template_html)
        self.assertIn("財經報", html)
        self.assertIn("2026-06-27", html)
        self.assertIn("正向", html)
        self.assertNotIn("matched_positive_terms", html)

    def test_external_news_is_escaped_without_template_evaluation(self):
        data = sample_analysis_data(
            [{"title": "{{ 7 * 7 }}<script>", "link": 'https://example.com/\" onmouseover=\"bad'}]
        )

        with stock_app.app.app_context():
            html = stock_app.render_web(data)

        self.assertIn("{{ 7 * 7 }}&lt;script&gt;", html)
        self.assertIn("&quot; onmouseover=&quot;bad", html)
        self.assertNotIn("49<script>", html)

    @patch("app.analyze", return_value=None)
    def test_stock_route_rejects_unknown_code_before_analysis(self, analyze):
        response = stock_app.app.test_client().get("/stock/not-a-stock")

        self.assertEqual(response.status_code, 404)
        analyze.assert_not_called()

    @patch("app.requests.get")
    def test_news_rejects_xml_entity_expansion(self, get):
        get.return_value.text = """<!DOCTYPE rss [<!ENTITY payload "expanded">]>
        <rss><channel><item><title>&payload;</title><link>https://example.com</link></item></channel></rss>"""

        self.assertEqual(stock_app.get_news("台積電"), [])

    def test_local_development_server_defaults_to_loopback(self):
        self.assertEqual(getattr(stock_app, "LOCAL_HOST", None), "127.0.0.1")

    def test_callback_rejects_oversized_payload(self):
        response = stock_app.app.test_client().post(
            "/callback",
            data=b"x" * 1_000_001,
            headers={"X-Line-Signature": "invalid"},
        )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
