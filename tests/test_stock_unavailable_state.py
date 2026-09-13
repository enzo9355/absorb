"""個股快照缺漏時的缺席狀態。

在這之前 /stock/<code> 在快照缺漏時回的是裸字串「查無資料」，
而且是 HTTP 200：沒有頁面外框、沒有導覽、沒有回去的路，
而且會被當成一個「成功」的頁面快取與索引。這是整輪改版裡
唯一沒有被設計過的缺席狀態 —— 報告層早就有 report_unavailable.html。

實際會走到：掛牌代號 ≠ 有快照。manifest 本來就帶 unavailable_symbols，
覆蓋率不是 100%，所以正式站按到這條路只是遲早的事。

這裡守三件事：
1 不能退回裸字串 —— 必須是完整頁面，而且有路可以回去。
2 狀態碼不能是 200 —— 缺席被當成成功會被快取與索引。
3 文案不能說「查無此股」—— 代號是掛牌的（不是的話前面就 404 了），
  缺的是今天通過驗證的觀察。兩件事混在一起會讓人以為自己打錯代號。
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app


class StockUnavailableStateTests(unittest.TestCase):
    def setUp(self):
        self.client = stock_app.app.test_client()

    def _get_with_no_snapshot(self, code="2330"):
        # 觀察層拿不到快照就是回 None，直接模擬那個狀態
        with patch.object(stock_app, "build_stock_observation", return_value=None):
            return self.client.get(f"/stock/{code}")

    def test_it_is_not_a_bare_string_any_more(self):
        response = self._get_with_no_snapshot()
        body = response.get_data(as_text=True)
        self.assertNotEqual(body.strip(), "查無資料")
        # 完整頁面 = 有外框。裸字串沒有這些。
        self.assertIn("<html", body)
        self.assertIn("main-content", body)

    def test_it_offers_a_way_back(self):
        """缺席狀態把人留在死路上，比顯示錯的數字好不了多少。"""
        body = self._get_with_no_snapshot().get_data(as_text=True)
        self.assertIn("回到個股與 ETF", body)
        self.assertIn("回到今天市場", body)

    def test_the_status_code_says_unavailable_not_success(self):
        """200 會讓這個缺席狀態被快取、被索引成一個正常頁面。"""
        response = self._get_with_no_snapshot()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("Retry-After"), "300")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_it_does_not_claim_the_symbol_does_not_exist(self):
        """代號是掛牌的 —— 不是的話前面就 abort(404) 了。

        講成「查無此股」會讓人以為自己打錯，然後一直重打。
        """
        body = self._get_with_no_snapshot().get_data(as_text=True)
        self.assertNotIn("查無此股", body)
        self.assertIn("沒有已驗證的觀察", body)
        self.assertIn("不是你打錯", body)

    def test_it_does_not_fill_the_gap_with_estimates(self):
        """缺值就是缺值。這一頁不得出現任何推估數字或機率。"""
        body = self._get_with_no_snapshot().get_data(as_text=True)
        self.assertIn("不會用推估值補位", body)
        for forbidden in ("預測價", "上漲機率", "勝率"):
            self.assertNotIn(forbidden, body)

    def test_an_unlisted_symbol_still_gets_404(self):
        """缺席狀態不能把「真的沒這支」也吃掉 —— 那是不同的事。"""
        response = self.client.get("/stock/NOTAREALCODE1234")
        self.assertEqual(response.status_code, 404)

    def test_the_page_keeps_the_market_context(self):
        """美股代號要停在美股，不能被丟回台股。"""
        with patch.object(stock_app, "build_stock_observation", return_value=None):
            body = self.client.get("/stock/AAPL").get_data(as_text=True)
        self.assertIn('data-market="US"', body)


if __name__ == "__main__":
    unittest.main()
