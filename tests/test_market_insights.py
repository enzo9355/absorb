import unittest

from market_insights import (
    build_industries,
    build_supply_chains,
    normalize_etf_holdings,
    parse_mops_items,
)


class MarketInsightsTests(unittest.TestCase):
    def test_parse_mops_normalizes_twse_tpex_and_deduplicates(self):
        rows = [
            {
                "發言日期": "1150706", "發言時間": "093001",
                "公司代號": "2330", "公司名稱": "台積電",
                "主旨 ": " 公告重大投資\r\n案 ", "符合條款": "第10款",
            },
            {
                "發言日期": "1150706", "發言時間": "093001",
                "SecuritiesCompanyCode": "2330", "CompanyName": "台積電",
                "主旨": "公告重大投資 案", "符合條款": "第10款",
            },
        ]

        result = parse_mops_items(rows, "MOPS")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "2330")
        self.assertEqual(result[0]["published_at"], "2026-07-06T09:30:01+08:00")
        self.assertEqual(result[0]["title"], "公告重大投資 案")

    def test_normalize_etf_holdings_sorts_and_bounds_weights(self):
        result = normalize_etf_holdings(
            [
                {"symbol": "2454", "name": "聯發科", "weight": 0.08},
                {"symbol": "2330", "name": "台積電", "weight": 0.52},
                {"symbol": "bad", "name": "錯誤", "weight": 2.0},
            ],
            {"ticker": "0050.TW", "name": "元大台灣50", "market": "TW"},
        )

        self.assertEqual(result["ticker"], "0050.TW")
        self.assertEqual([item["symbol"] for item in result["holdings"]], ["2330", "2454"])
        self.assertEqual(result["holdings"][0]["weight"], 52.0)

    def test_industries_and_supply_chains_attach_local_metrics(self):
        metrics = {
            "2330": {
                "name": "台積電", "prob": 68, "trend": "多頭", "as_of": "2026-07-06",
                "close": 100, "return_1d": 1.8, "inst_ratio": 1.0,
                "margin_change": 0.1, "volume_ratio": 1.5,
            },
            "2454": {
                "name": "聯發科", "prob": 52, "trend": "空頭", "as_of": "2026-07-06",
                "close": 80, "return_1d": -0.6, "inst_ratio": 0.0,
                "margin_change": 0.0, "volume_ratio": 1.1,
            },
        }

        industries = build_industries({"半導體": ["2454", "2330"]}, metrics)
        chains = build_supply_chains(metrics)

        self.assertEqual(industries[0]["leaders"][0]["symbol"], "2330")
        self.assertEqual(industries[0]["average_prob"], 60.0)
        self.assertEqual(industries[0]["average_return"], 0.6)
        self.assertEqual(industries[0]["bullish_ratio"], 50.0)
        self.assertEqual(industries[0]["coverage"], 2)
        self.assertEqual(industries[0]["heat_tone"], "rise")
        self.assertEqual(industries[0]["heat_size"], "sm")
        self.assertEqual(
            [(item["label"], item["score"]) for item in industries[0]["chips"]],
            [("法人", 6), ("融資", 8), ("量能", 6)],
        )
        semiconductor = next(item for item in chains if item["id"] == "semiconductor")
        tsmc = next(node for stage in semiconductor["stages"] for node in stage["nodes"] if node["symbol"] == "2330")
        self.assertEqual(tsmc["prob"], 68)
        self.assertEqual(tsmc["market"], "TW")
        self.assertEqual(tsmc["return_1d"], 1.8)
        self.assertIn("法人偏多", tsmc["signals"])

    def test_industry_tolerates_missing_probability(self):
        result = build_industries(
            {"半導體": ["2330"]},
            {"2330": {"name": "台積電", "prob": None, "trend": "多頭"}},
        )

        self.assertEqual(result[0]["average_prob"], 0.0)

    def test_industry_lists_five_candidates_but_counts_only_valid_metrics(self):
        symbols = ["1001", "1002", "1003", "1004", "1005"]
        metrics = {
            symbol: {
                "name": f"公司{index}",
                "prob": 60 if index == 1 else None,
                "trend": "多頭" if index == 1 else "資料待更新",
            }
            for index, symbol in enumerate(symbols, 1)
        }

        result = build_industries({"測試產業": symbols}, metrics)

        self.assertEqual(len(result[0]["leaders"]), 5)
        self.assertEqual(result[0]["coverage"], 1)
        self.assertEqual(result[0]["candidate_count"], 5)
        no_data = build_industries(
            {"測試產業": symbols},
            {symbol: {"name": symbol, "prob": None, "trend": "資料待更新"} for symbol in symbols},
        )
        self.assertEqual([item["score"] for item in no_data[0]["chips"]], [None, None, None])


if __name__ == "__main__":
    unittest.main()
