"""指標白話解讀（規格書 §5.3 第 3 層）。

這一組測試守的是一件事：**解讀必須是數值的函式**。
規格書禁止把解讀寫死在模板裡，理由就是「數值變了解讀不會變，
會產生錯誤陳述」。所以這裡不驗字面文案，驗的是對應關係。
"""

import inspect
import unittest

from stock_papi.batch import observation_products
from stock_papi.services import metric_reading
from stock_papi.services.metric_reading import market_metric_readings


class MetricReadingTests(unittest.TestCase):
    def test_missing_values_produce_no_reading_at_all(self):
        """缺值不得生出解讀。憑空解釋一個不存在的數值比不解釋更糟。"""
        self.assertEqual(market_metric_readings({}), {})
        self.assertEqual(market_metric_readings(None), {})
        self.assertEqual(
            market_metric_readings(
                {
                    "ma20_breadth_pct": None,
                    "median_volume_ratio": None,
                    "realized_volatility_20d_pct": None,
                    "risk_state": None,
                }
            ),
            {},
        )

    def test_reading_always_restates_the_number_it_describes(self):
        """解讀裡必須出現它所描述的那個數字。

        這是「解讀與數值不會分家」最直接的檢查：只要解讀退化成一句
        與數值無關的通用文案，這條就會紅。
        """
        for breadth in (12.3, 39.9, 50.0, 60.1, 88.8):
            with self.subTest(breadth=breadth):
                text = market_metric_readings({"ma20_breadth_pct": breadth})[
                    "ma20_breadth_pct"
                ]
                self.assertIn(f"{breadth:.1f}%", text)
        for ratio in (0.42, 1.00, 2.75):
            with self.subTest(ratio=ratio):
                text = market_metric_readings({"median_volume_ratio": ratio})[
                    "median_volume_ratio"
                ]
                self.assertIn(f"{ratio:.2f}", text)

    def test_breadth_reading_changes_across_its_thresholds(self):
        readings = [
            market_metric_readings({"ma20_breadth_pct": v})["ma20_breadth_pct"]
            for v in (20.0, 50.0, 80.0)
        ]
        self.assertEqual(len(set(readings)), 3)
        self.assertIn("偏少", readings[0])
        self.assertIn("均衡", readings[1])
        self.assertIn("偏多", readings[2])

    def test_volatility_reading_uses_the_same_thresholds_as_risk_state(self):
        """解讀與風險狀態不得各用一組門檻。

        兩邊各寫各的，畫面就會出現「波動程度：一般」配「風險狀態：升高」
        這種自我矛盾的組合。這裡直接檢查批次產生器 import 的是同一組常數。
        """
        self.assertIs(
            observation_products.VOLATILITY_ELEVATED_PCT,
            metric_reading.VOLATILITY_ELEVATED_PCT,
        )
        self.assertIs(
            observation_products.VOLATILITY_CAUTIOUS_PCT,
            metric_reading.VOLATILITY_CAUTIOUS_PCT,
        )

        # assertIs 只證明「現在是同一個物件」，擋不住有人把字面值寫回產生器
        # （那會讓兩邊各用一組門檻，而 import 仍然存在）。掃原始碼補上這一層。
        source = inspect.getsource(observation_products._market_observation)
        # 條件判斷在 `risk_state =` 之前，不能從賦值那一行往後切
        risk_block = source[source.index("if declining > advancing"):]
        self.assertNotRegex(
            risk_block,
            r"volatility\s*>=\s*[0-9]",
            "risk_state 的波動門檻必須用共用常數，不得寫字面值",
        )

        below = market_metric_readings(
            {"realized_volatility_20d_pct": metric_reading.VOLATILITY_CAUTIOUS_PCT - 0.1}
        )["realized_volatility_20d_pct"]
        cautious = market_metric_readings(
            {"realized_volatility_20d_pct": metric_reading.VOLATILITY_CAUTIOUS_PCT}
        )["realized_volatility_20d_pct"]
        elevated = market_metric_readings(
            {"realized_volatility_20d_pct": metric_reading.VOLATILITY_ELEVATED_PCT}
        )["realized_volatility_20d_pct"]
        self.assertEqual(len({below, cautious, elevated}), 3)

    def test_risk_reading_names_the_conditions_that_triggered_it(self):
        """升高／謹慎必須說出是被什麼推動的，而不是重複狀態名稱。"""
        text = market_metric_readings(
            {
                "risk_state": "elevated",
                "advancing_count": 700,
                "declining_count": 1200,
                "new_high_20d_count": 12,
                "new_low_20d_count": 88,
                "realized_volatility_20d_pct": 26.4,
            }
        )["risk_state"]
        self.assertIn("1200", text)
        self.assertIn("700", text)
        self.assertIn("88", text)
        self.assertIn("26.4", text)

    def test_risk_reading_is_omitted_when_it_cannot_be_explained(self):
        """狀態與可見欄位對不上時，寧可不解釋，也不要編一個理由。"""
        readings = market_metric_readings(
            {
                "risk_state": "elevated",
                "advancing_count": 1200,
                "declining_count": 700,
                "new_high_20d_count": 87,
                "new_low_20d_count": 22,
                "realized_volatility_20d_pct": 10.0,
            }
        )
        self.assertNotIn("risk_state", readings)

    def test_readings_never_predict(self):
        """§5.3：解讀只描述已發生的資料，不做方向性推論。"""
        banned = ("將", "會漲", "會跌", "預期", "建議", "應該", "看好", "看壞", "進場", "出場")
        samples = [
            {"ma20_breadth_pct": v} for v in (5.0, 45.0, 95.0)
        ] + [
            {"median_volume_ratio": v} for v in (0.3, 1.0, 3.0)
        ] + [
            {"realized_volatility_20d_pct": v} for v in (5.0, 22.0, 40.0)
        ] + [
            {
                "risk_state": state,
                "advancing_count": 700,
                "declining_count": 1200,
                "new_high_20d_count": 12,
                "new_low_20d_count": 88,
                "realized_volatility_20d_pct": 26.4,
            }
            for state in ("normal", "cautious", "elevated")
        ]
        for sample in samples:
            for key, text in market_metric_readings(sample).items():
                for word in banned:
                    with self.subTest(sample=sample, word=word):
                        self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
