"""部署閘門的樣式必須對得上介面實際 emit 的 HTML。

2026-09-13 這一條是補票。ORDER 5 把報告頁改成三軌之後，每個報告入口的
href 都帶上了 `#track-overview` / `#track-table` / `#track-research`，
但 `deploy_observation_production.ps1` 的 cutover 驗證要求
`post-close` 後面**緊接著引號**。於是正式部署被自己的閘門擋住：

    Observation report link is unavailable: post-close

閘門沒有壞，程式也沒有壞 —— 是閘門只認得一種拼法，而拼法被改了。
這是同一個毛病在這個專案裡的第六次，而且是唯一一次跨語言：
規則寫在 PowerShell 裡，整套 Python 測試看不到它，所以一路綠燈到部署當下。

這個模組就是那道橋：把 .ps1 裡的規則抽出來，對著樣板真正 render 出來的
HTML 跑一次。樣板怎麼改都行，改到閘門認不得的時候這裡會先紅，
而不是等到要上線的那一刻。
"""

import pathlib
import re
import unittest

from jinja2 import DictLoader, Environment


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_observation_production.ps1"

# 與 stock_papi/web/routes/reports.py 的 add_url_rule 一致
CANONICAL_PATHS = {
    "post_close_report_page": "/reports/{trading_date}/post-close",
    "pre_market_report_page": "/reports/{trading_date}/pre-market",
    "us_post_close_report_page": "/reports/us/{trading_date}/post-close",
    "us_pre_market_report_page": "/reports/us/{trading_date}/pre-market",
}


def _deploy_link_pattern(report_type):
    """把 .ps1 裡那條連結樣式抽出來，翻成等價的 Python regex。

    刻意從檔案讀，不是在這裡複寫一份 —— 複寫的那份不會跟著 .ps1 一起改，
    那就等於沒有測到。
    """
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"\$Pattern = 'href=\"\(\?<path>/reports/(?P<date>[^']*?)/' \+\s*"
        r"\[regex\]::Escape\(\$ReportType\) \+ '(?P<tail>[^']*)'",
        source,
    )
    if match is None:
        raise AssertionError(
            "在 deploy_observation_production.ps1 裡找不到報告連結樣式；"
            "樣式改寫過的話，這個測試的抽取方式也要跟著改"
        )
    # tail 本身已經帶著具名群組的右括號，這裡不要再補一個
    date_part = match.group("date")
    tail = match.group("tail")
    # .NET 與 Python 在這段語法上等價：字元類、量詞、具名群組、非擷取群組。
    # 差別只有具名群組的寫法：.NET 是 (?<name>…)，Python 是 (?P<name>…)。
    return (
        'href="(?P<path>/reports/'
        + date_part
        + "/"
        + re.escape(report_type)
        + tail.replace("(?<", "(?P<")
    )


def _render_reports_page(reports_v2):
    template = (REPO_ROOT / "templates" / "reports.html").read_text(encoding="utf-8")
    env = Environment(
        loader=DictLoader({
            "reports.html": template,
            "base.html": (
                "{% block title %}{% endblock %}"
                "{% block nav_reports %}{% endblock %}"
                "{% block content %}{% endblock %}"
            ),
        })
    )

    def url_for(endpoint, **values):
        # 用真實的路徑形狀，不是 /{endpoint} —— 這個測試整個重點就是路徑形狀
        return CANONICAL_PATHS[endpoint].format(**values)

    env.globals["url_for"] = url_for
    return env.get_template("reports.html").render(
        reports_v2=reports_v2, reports=[], unavailable=False
    )


def _report(report_type, day="2026-09-11"):
    return {
        "report_type": report_type,
        "source_market_date": day,
        "applicable_trading_date": day,
        "title": f"{day} 報告",
        "summary": ["摘要一", "摘要二"],
        "has_professional_report": True,
        "available_section_count": 6,
        "total_section_count": 9,
    }


class DeployGateMatchesRenderedLinksTests(unittest.TestCase):
    def test_the_gate_finds_a_link_for_each_report_type(self):
        """兩種報告類型的入口都要被閘門認得。

        post_close 先炸，但 pre_market 的入口同樣帶 fragment，
        修好前者而漏掉後者只會換一道牆。
        """
        html = _render_reports_page([_report("post_close"), _report("pre_market")])
        for report_type in ("post-close", "pre-market"):
            with self.subTest(report_type=report_type):
                pattern = _deploy_link_pattern(report_type)
                match = re.search(pattern, html)
                self.assertIsNotNone(
                    match,
                    f"部署閘門認不得報告頁 emit 的 {report_type} 連結。\n"
                    f"樣式：{pattern}\n"
                    "改過 templates/reports.html 的連結寫法時，"
                    "deploy_observation_production.ps1 的樣式也要跟著改。",
                )

    def test_the_captured_path_is_fetchable_as_is(self):
        """擷取到的 path 會被直接接在 BaseUrl 後面送出去。

        所以它必須是乾淨的路徑：不能把 #fragment 一起吃進去
        （那會讓驗證去抓一個帶井字號的網址），也不能漏掉日期。
        """
        html = _render_reports_page([_report("post_close"), _report("pre_market")])
        for report_type in ("post-close", "pre-market"):
            with self.subTest(report_type=report_type):
                match = re.search(_deploy_link_pattern(report_type), html)
                path = match.group("path")
                self.assertNotIn("#", path)
                self.assertRegex(
                    path, r"^/reports/\d{4}-\d{2}-\d{2}/" + re.escape(report_type) + "$"
                )

    def test_a_link_without_a_fragment_still_matches(self):
        """修法是「fragment 可有可無」，不是「一定要有 fragment」。

        把樣式改成強制要求 #track-… 會在報告頁改回不帶 fragment 的
        寫法時再炸一次，而且是同一種炸法。
        """
        html = (
            '<a href="/reports/2026-09-11/post-close">30 秒大局觀</a>'
            '<a href="/reports/2026-09-11/pre-market">30 秒大局觀</a>'
        )
        for report_type in ("post-close", "pre-market"):
            with self.subTest(report_type=report_type):
                self.assertIsNotNone(
                    re.search(_deploy_link_pattern(report_type), html)
                )


class DeployGateContentAnchorsTests(unittest.TestCase):
    """閘門抓完連結之後，還會檢查報告內容裡的錨點。

    連結修好之後就輪到這些，所以一起釘住 —— 免得修完第一道牆
    直接撞上第二道。
    """

    def test_the_anchors_the_gate_looks_for_still_exist(self):
        observation = (REPO_ROOT / "templates" / "report_observation.html").read_text(
            encoding="utf-8"
        )
        professional = (
            REPO_ROOT / "templates" / "reports" / "post_close_professional.html"
        ).read_text(encoding="utf-8")

        # pre-market 走的是嚴格比對：閘門只認 overnight-title
        self.assertIn("overnight-title", observation)

        # post-close 走的是三選一，專業版樣板至少要命中其中一個
        self.assertTrue(
            any(
                anchor in professional
                for anchor in ("market-actuals-title", "professional-report", "report-masthead")
            ),
            "盤後報告樣板一個閘門錨點都沒命中",
        )

    def test_the_gate_still_declares_both_anchors(self):
        """.ps1 那份錨點清單改掉的話，上面那條測的就不是真的閘門了。"""
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("'post-close' = 'market-actuals-title'", source)
        self.assertIn("'pre-market' = 'overnight-title'", source)


if __name__ == "__main__":
    unittest.main()
