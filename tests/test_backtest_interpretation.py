import unittest

from reporting.interpretation import interpret_backtest
from stock_papi.quant.backtest import summarize_trade_returns


class TradeSummaryTests(unittest.TestCase):
    def test_average_profit_loss_expectancy_profit_factor_and_streaks(self):
        summary = summarize_trade_returns(
            [0.10, 0.20, -0.05, -0.10, 0.03],
            gross_period_returns=[0.10585, 0.20585, -0.04415, -0.09415, 0.03585],
            round_trip_cost=0.00585,
            total_periods=8,
        )

        self.assertAlmostEqual(summary["average_profit"], 0.11)
        self.assertAlmostEqual(summary["average_loss"], -0.075)
        self.assertAlmostEqual(summary["expected_return"], 0.036)
        self.assertAlmostEqual(summary["payoff_ratio"], 0.11 / 0.075)
        self.assertAlmostEqual(summary["profit_factor"], 0.33 / 0.15)
        self.assertEqual(summary["longest_winning_streak"], 2)
        self.assertEqual(summary["longest_losing_streak"], 2)
        self.assertAlmostEqual(summary["cash_period_ratio"], 3 / 8)

    def test_cost_sensitivity_uses_existing_cost_without_changing_entries(self):
        summary = summarize_trade_returns(
            [0.09415, -0.02585],
            gross_period_returns=[0.10, None, -0.02],
            round_trip_cost=0.00585,
            total_periods=3,
        )

        expected_no_cost = (1.10 * 0.98) - 1
        expected_current = ((1 + 0.10 - 0.00585) * (1 - 0.02 - 0.00585)) - 1
        expected_double = ((1 + 0.10 - 0.0117) * (1 - 0.02 - 0.0117)) - 1
        self.assertAlmostEqual(summary["cost_sensitivity"]["zero_cost"], expected_no_cost)
        self.assertAlmostEqual(summary["cost_sensitivity"]["current_cost"], expected_current)
        self.assertAlmostEqual(summary["cost_sensitivity"]["double_cost"], expected_double)

    def test_all_cash_and_zero_trade_do_not_publish_fake_zero_metrics(self):
        summary = summarize_trade_returns(
            [], gross_period_returns=[None, None, None], round_trip_cost=0.00585,
            total_periods=3,
        )

        for key in (
            "average_profit", "average_loss", "expected_return", "payoff_ratio",
            "profit_factor",
        ):
            self.assertIsNone(summary[key])
        self.assertEqual(summary["cash_period_ratio"], 1.0)
        self.assertEqual(summary["longest_winning_streak"], 0)
        self.assertEqual(summary["longest_losing_streak"], 0)


class BacktestInterpretationTests(unittest.TestCase):
    def test_plain_language_keeps_probability_accuracy_and_win_rate_distinct(self):
        result = interpret_backtest({
            "strat_cum": 20.0,
            "bh_cum": 8.0,
            "mdd": -16.0,
            "win_rate": 62.5,
            "cash_period_ratio": 0.4,
            "sharpe": 1.2,
            "brier": 0.19,
            "trades": 40,
        })

        self.assertIn("優於單純買進持有", result["advantage"])
        self.assertIn("約變成 12 萬元", result["cumulative_return"])
        self.assertIn("一度剩下約 8.4 萬元", result["maximum_drawdown"])
        self.assertIn("每 100 次進場約有 62 次獲利", result["win_rate"])
        self.assertIn("不代表每次盈虧相同", result["win_rate"])
        self.assertIn("約 40% 的再平衡期間沒有進場", result["cash_ratio"])
        self.assertIn("報酬效率", result["sharpe"])
        self.assertIn("模型說 60%", result["brier"])

    def test_missing_metrics_are_explicit_not_zero_filled(self):
        result = interpret_backtest({})

        self.assertTrue(all("資料不足" in text for text in result.values()))


if __name__ == "__main__":
    unittest.main()
