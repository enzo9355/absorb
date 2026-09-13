"""部署閘門的樣式必須對得上介面實際 emit 的 HTML。

2026-09-13 這一條是補票，而且補了兩次。

ORDER 5 把報告頁改成三軌之後，每個報告入口的 href 都帶上了
`#track-overview` / `#track-table` / `#track-research`，但
`deploy_observation_production.ps1` 的 cutover 驗證要求 `post-close`
後面**緊接著引號**。於是正式部署被自己的閘門擋住：

    Observation report link is unavailable: post-close      (line 370)

閘門沒有壞，程式也沒有壞 —— 是閘門只認得一種拼法，而拼法被改了。

修完第一條之後，部署又被擋在：

    US canonical report link is unavailable                 (line 408)

因為那支腳本裡有**兩份**寫死的連結樣式，第一次只修了錯誤訊息指名的那一條。
修「這個實例」而不是「這一類」，就是再跑一次、再失敗一次。

所以這個模組不挑特定行號，而是把 .ps1 裡**每一條**報告連結樣式都掃出來，
逐一對樣板真正 render 的 HTML 驗證。之後有人再加第三條、或改寫樣板，
都會先在這裡紅，而不是等到要上線的那一刻。
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


def _dotnet_to_python(pattern):
    """.NET 與 Python 在這些樣式上等價，差別只有具名群組的寫法。"""
    return pattern.replace("(?<", "(?P<")


def _gate_link_patterns():
    """把 .ps1 裡**所有**報告連結樣式抽出來。

    刻意從檔案讀而不是在這裡複寫 —— 複寫的那份不會跟著 .ps1 一起改，
    等於沒測到。回傳 [(來源說明, python regex, 是否美股)]。
    """
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    found = []

    # 形式一：字串相接，$ReportType 在中間（台股，兩種報告類型共用）
    joined = re.search(
        r"\$Pattern = '(?P<head>href=\"\(\?<path>/reports/[^']*?)'\s*\+\s*"
        r"\[regex\]::Escape\(\$ReportType\) \+ '(?P<tail>[^']*)'",
        source,
    )
    if joined is not None:
        for report_type in ("post-close", "pre-market"):
            found.append((
                f"$Pattern（{report_type}）",
                _dotnet_to_python(
                    joined.group("head") + re.escape(report_type) + joined.group("tail")
                ),
                False,
            ))

    # 形式二：整條寫死的字串字面值（目前是美股那條）。
    # 只收「完整」的樣式：完整的樣式會一路寫到收尾的引號，
    # 形式一被相接切斷的前半段則是以 / 結尾，要排除掉，
    # 否則會拿一個殘缺的 regex 去編譯而炸掉。
    for literal in re.findall(r"'(href=\"\(\?<path>/reports/[^']*)'", source):
        if not literal.endswith('"'):
            continue
        found.append((
            f"字面值 {literal[:48]}…",
            _dotnet_to_python(literal),
            "/reports/us/" in literal,
        ))

    if not found:
        raise AssertionError(
            "在 deploy_observation_production.ps1 裡找不到任何報告連結樣式；"
            "樣式的寫法改過的話，這裡的抽取方式也要跟著改，"
            "否則這個測試會變成永遠通過的裝飾品"
        )
    return found


def _render_reports_page(reports_v2, *, market="TW"):
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
    # 用真實的路徑形狀，不是 /{endpoint} —— 這個測試整個重點就是路徑形狀
    env.globals["url_for"] = lambda endpoint, **values: (
        CANONICAL_PATHS[endpoint].format(**values)
    )
    # 樣板是從 market 自己推導 is_us 的（reports.html 第 5-6 行），
    # 直接塞 is_us 會被覆蓋掉 —— 要傳 market
    return env.get_template("reports.html").render(
        reports_v2=reports_v2, reports=[], unavailable=False, market=market
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


def _both_lanes():
    return [_report("post_close"), _report("pre_market")]


class EveryGatePatternMatchesRenderedLinksTests(unittest.TestCase):
    def test_every_link_pattern_in_the_deploy_script_matches(self):
        """.ps1 裡每一條樣式都要認得對應頁面 emit 的連結。

        掃全部而不是挑一條，是因為第一次修的時候就是只修了錯誤訊息
        指名的那條，結果換一道牆再擋一次。
        """
        pages = {
            False: _render_reports_page(_both_lanes()),
            True: _render_reports_page(_both_lanes(), market="US"),
        }
        patterns = _gate_link_patterns()
        self.assertGreaterEqual(
            len(patterns), 3,
            "抽到的樣式比預期少 —— 抽取方式可能失效了，"
            "那會讓這個測試變成永遠通過"
        )
        for label, pattern, is_us in patterns:
            with self.subTest(pattern=label):
                match = re.search(pattern, pages[is_us])
                self.assertIsNotNone(
                    match,
                    f"部署閘門認不得 {'美股' if is_us else '台股'}報告頁 emit 的連結。\n"
                    f"樣式來源：{label}\n"
                    f"樣式：{pattern}\n"
                    "改過 templates/reports.html 的連結寫法時，"
                    "deploy_observation_production.ps1 裡的**每一條**樣式都要跟著改。",
                )

    def test_every_captured_path_is_fetchable_as_is(self):
        """擷取到的 path 會被直接接在 BaseUrl 後面送出去。

        所以必須是乾淨的路徑：不能把 #fragment 一起吃進去。
        """
        pages = {
            False: _render_reports_page(_both_lanes()),
            True: _render_reports_page(_both_lanes(), market="US"),
        }
        for label, pattern, is_us in _gate_link_patterns():
            with self.subTest(pattern=label):
                match = re.search(pattern, pages[is_us])
                path = match.group("path")
                self.assertNotIn("#", path)
                self.assertRegex(
                    path,
                    r"^/reports/(us/)?\d{4}-\d{2}-\d{2}/(post-close|pre-market)$",
                )

    def test_links_without_a_fragment_still_match(self):
        """修法是「fragment 可有可無」，不是「一定要有 fragment」。

        改成強制要求 #track-… 會在報告頁改回不帶 fragment 時再炸一次，
        而且是同一種炸法。
        """
        html = (
            '<a href="/reports/2026-09-11/post-close">x</a>'
            '<a href="/reports/2026-09-11/pre-market">x</a>'
            '<a href="/reports/us/2026-09-11/post-close">x</a>'
            '<a href="/reports/us/2026-09-11/pre-market">x</a>'
        )
        for label, pattern, _is_us in _gate_link_patterns():
            with self.subTest(pattern=label):
                self.assertIsNotNone(re.search(pattern, html))


class DeployGateContentChecksTests(unittest.TestCase):
    """連結抓到之後閘門還會檢查內容，一起釘住免得修完又撞牆。"""

    def test_the_report_anchors_the_gate_looks_for_still_exist(self):
        observation = (REPO_ROOT / "templates" / "report_observation.html").read_text(
            encoding="utf-8"
        )
        professional = (
            REPO_ROOT / "templates" / "reports" / "post_close_professional.html"
        ).read_text(encoding="utf-8")

        # pre-market 走嚴格比對：閘門只認 overnight-title
        self.assertIn("overnight-title", observation)
        # post-close 走三選一，專業版樣板至少要命中一個
        self.assertTrue(
            any(
                anchor in professional
                for anchor in (
                    "market-actuals-title", "professional-report", "report-masthead",
                )
            ),
            "盤後報告樣板一個閘門錨點都沒命中",
        )

    def test_the_gate_still_declares_both_anchors(self):
        """.ps1 那份錨點清單改掉的話，上面那條測的就不是真的閘門了。"""
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("'post-close' = 'market-actuals-title'", source)
        self.assertIn("'pre-market' = 'overnight-title'", source)

    def test_the_us_market_identity_check_has_something_to_match(self):
        """閘門要求美股報告帶 data-market="US" 且不得出現 data-market="TW"。"""
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('data-market="US"', source)
        markup = "".join(
            path.read_text(encoding="utf-8")
            for path in (REPO_ROOT / "templates").rglob("*.html")
        )
        self.assertIn('data-market="', markup, "樣板已經不再標示市場身分")


if __name__ == "__main__":
    unittest.main()
