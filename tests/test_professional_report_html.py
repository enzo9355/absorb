import pathlib
import unittest

from jinja2 import DictLoader, Environment

from reporting.professional_builder import build_professional_post_close_artifact
from reporting.professional_html import build_professional_report_view


class ProfessionalReportHtmlTests(unittest.TestCase):
    def _metadata(self):
        return {
            "schema_version": 2,
            "report_type": "post_close",
            "product_mode": "observation",
            "market": "TW",
            "source_market_date": "2026-07-17",
            "applicable_trading_date": "2026-07-20",
            "published_at": "2026-07-17T10:30:00Z",
            "source_manifest": "quant/v1/manifests/TW-20260717T091000Z-123456789abc.json",
            "source_manifest_sha256": "a" * 64,
            "prediction_capability": {
                "mode": "research",
                "observation_enabled": True,
                "probability_allowed": False,
                "ranking_allowed": False,
                "strong_action_allowed": False,
                "performance_endorsement_allowed": False,
            },
            "content": {
                "market_observation": {
                    "return_1d_pct": -0.72,
                    "advancing_count": 520,
                    "declining_count": 812,
                    "ma20_breadth_pct": 39.7,
                    "realized_volatility_20d_pct": 18.2,
                },
                "industry_observations": [
                    {"name": "半導體製造", "available_count": 6, "component_count": 6, "relative_return_5d_pct": 4.31},
                    {"name": "航運", "available_count": 8, "component_count": 9, "relative_return_5d_pct": -3.20},
                ],
                "heatmap": [],
                "stock_events": [],
                "trading_status_observations": [
                    {
                        "symbol": "2303",
                        "name": "測試股票 2303",
                        "status": "official_no_regular_trade",
                        "label": "當日無正常交易",
                        "observation_as_of": "2026-07-17",
                        "latest_regular_price_date": "2026-07-16",
                        "evidence_sha256": "c" * 64,
                        "last_regular_close": 100.0,
                    }
                ],
                "etf_observations": [],
                "daily_focus": ["市場廣度降至四成以下"],
                "data_quality": {"coverage": 0.982, "symbol_count": 1332, "failure_count": 24},
            },
        }

    def _view(self):
        report = build_professional_post_close_artifact(
            self._metadata(), code_commit_sha="b" * 40
        )
        return build_professional_report_view(
            report, pdf_download_url="/reports/2026-07-17/post-close/download"
        )

    def test_view_model_does_not_expose_internal_manifest_path(self):
        view = self._view()
        self.assertNotIn("source_manifest", view["identity"])
        self.assertEqual(view["identity"]["source_manifest_sha256_short"], "aaaaaaaaaaaa")
        self.assertEqual(view["pdf_download_url"], "/reports/2026-07-17/post-close/download")

    def test_template_renders_single_h1_and_professional_sections(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        output = env.get_template("reports/post_close_professional.html").render(
            report=self._view()
        )
        self.assertEqual(output.count("<h1"), 1)
        for anchor in (
            "executive-summary",
            "market-analysis",
            "capital-flows",
            "industry-analysis",
            "security-analysis",
            "quantitative-research",
            "model-validation",
            "next-session",
            "data-governance",
            "ai-reference",
        ):
            self.assertIn(f'id="{anchor}"', output)
        self.assertIn("下載完整 PDF", output)
        self.assertIn("法人流向尚未納入", output)
        self.assertIn("當日無正常交易", output)
        self.assertIn("最後正常交易收盤 100.00（2026-07-16）", output)
        self.assertNotIn("quant/v1/manifests/", output)

    def _render(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}"
                    "{% block nav_reports %}{% endblock %}"
                    "{% block content %}{% endblock %}",
                }
            )
        )
        return env.get_template("reports/post_close_professional.html").render(
            report=self._view()
        )

    def test_order5_every_chapter_and_subsection_is_addressable(self):
        """A-7：每個 <h2>／<h3> 都要有穩定 id，才能貼連結引用某一章。

        稽核基準點其實已經有常駐章節索引與 <section> id —— 規格書 A-7
        寫「無目錄、無錨點」是錯的，這一點已回報。真正缺的是：
        子章節（4 個 subsection-title）完全無法引用，索引沒有位置回饋，
        沒有回到頂端。
        """
        output = self._render()

        # ORDER 5（§6.2）異常個股資料表、ORDER 6（§2）反對證據與失效條件
        # 各自成章，h2 因此是 12 個
        self.assertEqual(output.count("<h2 id="), 12)
        for anchor in (
            "executive-summary-title",
            "quantitative-research-title",
            "data-governance-title",
            "exec-highlights",
            "security-anomalies",
            "security-etf",
            "security-trading-status",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(f'id="{anchor}"', output)

        # 索引本身：可收合、有當前章節槽位、有回到頂端
        self.assertIn("data-chapter-nav", output)
        self.assertIn("data-chapter-current", output)
        self.assertIn('href="#top-of-report"', output)
        self.assertIn('id="top-of-report"', output)

    def test_order6_opposing_evidence_is_its_own_chapter_with_failure_conditions(self):
        """§2 Evidence first：結論、依據、反對證據、限制。

        反對證據原本只在「投資決策摘要」的雙欄裡出現一次（那是給 30 秒
        讀者的），研究版讀者一路往下看不會再遇到它；而
        next_session_watch_conditions —— 真正的失效條件 —— 在整份報告裡
        從來沒有被繪出過。
        """
        output = self._render()

        self.assertIn('id="opposing-evidence"', output)
        self.assertIn("反對證據與失效條件", output)
        self.assertIn("這個結論在什麼情況下不成立", output)
        for anchor in ("opposing-points", "invalidation-conditions", "largest-risk"):
            with self.subTest(anchor=anchor):
                self.assertIn(f'id="{anchor}"', output)

        # 失效條件必須真的繪出資料，不是空殼
        view = self._view()
        for condition in view["executive_summary"]["next_session_watch_conditions"]:
            with self.subTest(condition=condition):
                self.assertIn(condition, output)

        # 章節索引要收錄它，否則等於沒有這一章
        nav = output[output.index('aria-label="報告章節導覽"'):]
        nav = nav[: nav.index("</nav>")]
        self.assertIn('href="#opposing-evidence"', nav)

        # 排在「依據」之後（§2 的順序）
        self.assertLess(
            output.index('id="market-analysis"'), output.index('id="opposing-evidence"')
        )

        # §0.4：不得用 emoji 當區塊標記
        self.assertNotIn("⚠️", output)

    def test_order5_model_sections_link_to_the_methodology_chapter(self):
        """§6.3：看到 R²、Brier Score、Gate 時，下一個問題是「怎麼算的」。"""
        output = self._render()

        self.assertEqual(output.count('class="method-link" href="#data-governance"'), 4)
        # 方法論章節本身不該連向自己
        governance = output[output.index('id="data-governance"'):]
        governance = governance[: governance.index("</section>")]
        self.assertNotIn("method-link", governance)

    def test_professional_report_visualizes_verified_market_industry_and_event_data(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        metadata = self._metadata()
        metadata["content"]["stock_events"] = [
            {
                "symbol": "3313",
                "name": "斐成",
                "event_type": "price_move",
                "severity": "high",
                "observation": "單日漲幅異常",
                "metric_value": 10.0,
                "unit": "pct",
                "as_of": "2026-07-17",
            },
            {
                "symbol": "6955",
                "name": "邦睿生技-創",
                "event_type": "price_move",
                "severity": "high",
                "observation": "單日跌幅異常",
                "metric_value": -10.83,
                "unit": "pct",
                "as_of": "2026-07-17",
            },
        ]
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        output = env.get_template("reports/post_close_professional.html").render(
            report=build_professional_report_view(report)
        )

        self.assertIn('aria-label="市場視覺摘要"', output)
        self.assertIn('aria-label="產業相對強弱視覺"', output)
        self.assertIn('class="industry-strength-bar', output)
        self.assertIn('data-report-event-group="up"', output)
        self.assertIn('data-report-event-group="down"', output)
        self.assertLess(output.index("斐成"), output.index("邦睿生技-創"))

    def test_us_view_uses_us_title_and_market_disclosure(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        metadata = self._metadata()
        metadata["market"] = "US"
        metadata["source_manifest"] = (
            "quant/v1/manifests/US-20260717T091000Z-123456789abc.json"
        )
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view = build_professional_report_view(report)
        # Existing production artifacts can carry the legacy TW fallback reason;
        # the US reader must normalize that copy without rebuilding the artifact.
        view["capital_flows"]["reason"] = "法人流向尚未納入目前的已驗證 Observation Artifact"
        output = env.get_template("reports/post_close_professional.html").render(
            report=view
        )

        self.assertEqual(view["identity"]["market"], "US")
        self.assertEqual(view["title"], "ABSORB 美股市場、產業與量化研究日報")
        self.assertIn("美國公開市場資料", output)
        self.assertIn("市場指數表現", output)
        self.assertIn("資金流向與市場資料", output)
        self.assertIn("單位：百萬美元", output)
        self.assertIn("機構資金流向尚未納入", output)
        self.assertIn("官方交易狀態觀察（停牌、終止上市等）", output)
        self.assertNotIn("ABSORB 台股市場、產業與量化研究日報", output)
        self.assertNotIn("加權指數表現", output)
        self.assertNotIn("新台幣", output)
        self.assertNotIn("三大法人", output)
        self.assertNotIn("法人流向", output)
        self.assertNotIn("減資", output)
        self.assertNotIn("處置", output)
        self.assertNotIn("TWSE", output)
        self.assertNotIn("TPEx", output)

    def test_template_uses_csp_safe_classes_instead_of_inline_styles(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("style=", template_text)
        for css_class in (
            "col-rank",
            "align-right",
            "align-center",
            "report-meta-spaced",
            "governance-note",
        ):
            self.assertIn(css_class, template_text)

    def test_etf_observations_render_verified_fields_and_safe_fallback(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        metadata = self._metadata()
        metadata["content"]["etf_observations"] = [
            {
                "symbol": "0050",
                "name": "元大台灣50",
                "price": 106.4,
                "return_1d_pct": -0.28,
                "return_5d_pct": 3.45,
                "volume_ratio": 0.4,
                "trend_observation": "above_ma20",
                "as_of": "2026-07-17",
            },
            {
                "symbol": "0056",
                "name": "元大高股息",
                "price": None,
                "return_1d_pct": None,
                "return_5d_pct": None,
                "volume_ratio": None,
                "trend_observation": None,
                "as_of": "2026-07-17",
            },
        ]
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view = build_professional_report_view(report)
        output = env.get_template("reports/post_close_professional.html").render(
            report=view
        )
        # Verify 0050 full fields
        self.assertIn("元大台灣50", output)
        self.assertIn("0050", output)
        self.assertIn("106.40", output)
        self.assertIn("-0.28%", output)
        self.assertIn("+3.45%", output)
        self.assertIn("站上 MA20", output)
        self.assertIn("0.40", output)

        # Verify 0056 fallback
        self.assertIn("元大高股息", output)
        self.assertIn("0056", output)

    def test_etf_observations_survive_zero_missing_and_malformed_fields(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        metadata = self._metadata()
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view = build_professional_report_view(report)
        view["securities"]["data"]["etf_observations"] = [
            {
                "symbol": "0050",
                "name": "零值標的",
                "price": 0.0,
                "return_1d_pct": 0.0,
                "return_5d_pct": 0.0,
                "volume_ratio": 0.0,
                "trend_observation": "insufficient",
                "as_of": "2026-07-17",
            },
            {
                "symbol": "0056",
                "name": "缺鍵標的",
                "as_of": "2026-07-17",
            },
            {
                "symbol": "0057",
                "name": "型別異常標的",
                "price": "abc",
                "return_1d_pct": "x",
                "return_5d_pct": None,
                "volume_ratio": None,
                "trend_observation": None,
                "as_of": "2026-07-17",
            },
        ]
        output = env.get_template("reports/post_close_professional.html").render(
            report=view
        )
        self.assertIn("零值標的", output)
        self.assertIn("0.00", output)
        self.assertIn("+0.00%", output)
        self.assertIn("資料不足", output)
        self.assertIn("缺鍵標的", output)
        self.assertIn("型別異常標的", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("Undefined", output)

    def test_scenario_empty_and_non_empty_states(self):
        template_text = pathlib.Path(
            "templates/reports/post_close_professional.html"
        ).read_text(encoding="utf-8")
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": template_text,
                    "base.html": "{% block title %}{% endblock %}{% block nav_reports %}{% endblock %}{% block content %}{% endblock %}",
                }
            )
        )
        view = self._view()
        # View generated with breadth=39.7 has negative scenario populated, positive scenario empty
        self.assertEqual(len(view["next_session"]["data"]["positive"]), 0)
        self.assertGreater(len(view["next_session"]["data"]["negative"]), 0)

        output = env.get_template("reports/post_close_professional.html").render(
            report=view
        )
        self.assertIn("目前沒有符合此情境的已驗證條件", output)
        self.assertIn("站上 MA20 比例 <= 40%", output)

        # Invert: positive populated, negative empty
        metadata = self._metadata()
        metadata["content"]["market_observation"]["ma20_breadth_pct"] = 72.0
        metadata["content"]["market_observation"]["realized_volatility_20d_pct"] = 12.0
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view_pos = build_professional_report_view(report)
        self.assertGreater(len(view_pos["next_session"]["data"]["positive"]), 0)
        self.assertEqual(len(view_pos["next_session"]["data"]["negative"]), 0)

        output_pos = env.get_template("reports/post_close_professional.html").render(
            report=view_pos
        )
        self.assertIn("站上 MA20 比例 >= 60%", output_pos)
        self.assertIn("目前沒有符合此情境的已驗證條件", output_pos)


if __name__ == "__main__":
    unittest.main()
