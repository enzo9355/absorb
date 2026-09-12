import pathlib
import re
import unittest

from jinja2 import DictLoader, Environment


class ReportsTemplateTests(unittest.TestCase):
    def _render(self, *, reports_v2, reports, unavailable=False):
        template_text = pathlib.Path("templates/reports.html").read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        env.globals["url_for"] = lambda endpoint, **values: f"/{endpoint}"
        return env.get_template("reports.html").render(
            reports_v2=reports_v2,
            reports=reports,
            unavailable=unavailable,
        )

    def test_v2_reports_do_not_render_false_empty_state(self):
        output = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": "盤後研究報告",
                    "summary": ["摘要"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                }
            ],
            reports=[],
        )
        self.assertIn("盤後研究報告", output)
        self.assertNotIn("目前沒有可用的每日報告", output)

    def test_v2_reports_are_grouped_into_filterable_premarket_and_postclose_lanes(self):
        output = self._render(
            reports_v2=[
                {
                    "report_type": "pre_market",
                    "title": "盤前研究報告",
                    "summary": ["盤前摘要"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                },
                {
                    "report_type": "post_close",
                    "title": "盤後研究報告",
                    "summary": ["盤後摘要"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                },
            ],
            reports=[],
        )

        self.assertIn('data-report-filters', output)
        self.assertIn('data-report-filter="all"', output)
        self.assertIn('data-report-filter="pre_market"', output)
        self.assertIn('data-report-filter="post_close"', output)
        self.assertEqual(output.count('class="report-lane"'), 2)
        self.assertIn('data-report-type="pre_market"', output)
        self.assertIn('data-report-type="post_close"', output)
        self.assertIn("盤前研究報告", output)
        self.assertIn("盤後研究報告", output)

    def test_order5_index_splits_by_reader_then_type_with_a_trading_day_timeline(self):
        """A-5：兩層篩選。第一層是讀者，第二層才是報告類型。

        原本只有類型一層，兩種讀者的入口混在同一份清單裡，731 行的研究版
        沒有直達路徑。這裡的作法是：三個門一直都在每張卡片上，讀者層切換
        的是「哪一個是主要按鈕」—— 不把同一份報告在清單裡列兩次。
        """
        output = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": "盤後研究報告",
                    "summary": ["一句話結論", "第二條摘要"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                },
                {
                    "report_type": "pre_market",
                    "title": "盤前研究報告",
                    "summary": ["盤前一句話"],
                    "source_market_date": "2026-07-16",
                    "applicable_trading_date": "2026-07-17",
                },
            ],
            reports=[],
        )

        # 第一層：讀者
        self.assertIn("data-report-readers", output)
        for reader in ("overview", "table", "research"):
            self.assertIn(f'data-report-reader="{reader}"', output)
        # 第二層：類型（沿用既有機制）
        self.assertIn('data-report-filter="post_close"', output)

        # 三個門都在，且指向報告內頁的對應分頁
        # （這個測試環境把 url_for 換成回傳 endpoint 名稱，比對錨點即可）
        for track in ("overview", "table", "research"):
            with self.subTest(track=track):
                self.assertIn(f'#track-{track}" data-report-door="{track}"', output)
        # 盤前沒有異常個股資料表，不得憑空給一個會落空的入口
        pre_market_card = output[output.index("盤前研究報告"):]
        pre_market_card = pre_market_card[: pre_market_card.index("</article>")]
        self.assertNotIn("#track-table", pre_market_card)

        # 沒有 JS 時也要看得出先讀哪一個
        self.assertIn('class="button is-primary-door"', output)

        # 時間軸：只列出真的有報告的交易日
        self.assertIn("data-report-timeline", output)
        self.assertIn('data-report-day="2026-07-20"', output)
        self.assertIn('data-report-day="2026-07-17"', output)
        self.assertNotIn('data-report-day="2026-07-18"', output)

        # 免點即覽：第一條摘要抬到卡片上
        self.assertIn('<p class="report-lead">一句話結論</p>', output)

    def test_order5_lanes_are_ordered_newest_first_as_the_copy_promises(self):
        """頁面文案寫「由新到舊閱讀」，就必須真的由新到舊。

        索引本身的順序不保證，模板不能把排序假設外包給後端然後在畫面上
        對讀者做一個沒有根據的承諾。
        """
        output = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": f"{day} 盤後",
                    "summary": ["摘要"],
                    "source_market_date": day,
                    "applicable_trading_date": day,
                }
                for day in ("2026-07-15", "2026-07-17", "2026-07-16")
            ],
            reports=[],
        )
        self.assertIn("由新到舊", output)
        order = re.findall(r'<p class="report-date">(\d{4}-\d{2}-\d{2})</p>', output)
        self.assertEqual(order, sorted(order, reverse=True))

    def test_order7_track_and_length_only_shown_when_the_index_says_so(self):
        """§6.1：軌道與篇幅只能來自索引欄位，不得憑報告類型猜。

        索引在這次改動之前沒有這三個欄位。舊報告必須照樣顯示，
        只是不標軌道 —— 缺值就是缺值，猜的話會在沒有研究版時說謊。
        """
        with_track = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": "盤後研究報告",
                    "summary": ["一句話結論"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                    "has_professional_report": True,
                    "available_section_count": 6,
                    "total_section_count": 9,
                }
            ],
            reports=[],
        )
        self.assertIn("研究版", with_track)
        self.assertIn("6／9 章有內容", with_track)

        # 舊索引（沒有欄位）：不得出現任何軌道標示，但報告本身照樣列出
        legacy = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": "盤後研究報告",
                    "summary": ["一句話結論"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                }
            ],
            reports=[],
        )
        self.assertIn("盤後研究報告", legacy)
        self.assertNotIn("report-track-badge", legacy)
        self.assertNotIn("章有內容", legacy)

        # 明確標示沒有研究版：不給一個點了會落空的入口
        no_professional = self._render(
            reports_v2=[
                {
                    "report_type": "post_close",
                    "title": "盤後觀察報告",
                    "summary": ["一句話結論"],
                    "source_market_date": "2026-07-17",
                    "applicable_trading_date": "2026-07-20",
                    "has_professional_report": False,
                }
            ],
            reports=[],
        )
        self.assertNotIn("report-track-badge", no_professional)
        self.assertNotIn("#track-research", no_professional)
        self.assertIn("#track-overview", no_professional)

    def test_empty_state_only_when_both_collections_are_empty(self):
        output = self._render(reports_v2=[], reports=[])
        self.assertIn("目前沒有可用的每日報告", output)

    def test_unavailable_empty_state_uses_service_error_copy(self):
        output = self._render(reports_v2=[], reports=[], unavailable=True)
        self.assertIn("報告服務暫時無法讀取", output)
        self.assertNotIn("本地量化流程完成發布後", output)


if __name__ == "__main__":
    unittest.main()
