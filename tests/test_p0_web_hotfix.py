import copy
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import DictLoader, Environment

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

import app as stock_app
from reporting.professional_builder import build_professional_post_close_artifact
from reporting.professional_html import build_professional_report_view
from tests.test_observation_public_surfaces import (
    observation_dashboard,
    quant_snapshot,
)
from tests.test_professional_report_html import ProfessionalReportHtmlTests


ROOT = Path(__file__).resolve().parents[1]


class P0WebHotfixTests(unittest.TestCase):
    def test_mobile_more_menu_starts_collapsed_and_marks_summary_active(self):
        client = stock_app.app.test_client()
        for path in ("/ask", "/industries", "/learn", "/events"):
            with self.subTest(path=path):
                html = client.get(path).get_data(as_text=True)
                self.assertIn('<details class="mobile-more-menu">', html)
                self.assertNotIn('<details class="mobile-more-menu" open>', html)
                self.assertIn('<summary class="active" aria-label="開啟更多功能">', html)

        home_html = client.get("/").get_data(as_text=True)
        self.assertIn('<details class="mobile-more-menu">', home_html)
        self.assertIn('<summary class="" aria-label="開啟更多功能">', home_html)

    def test_quick_ask_dialog_starts_hidden_and_inert(self):
        html = stock_app.app.test_client().get("/").get_data(as_text=True)
        self.assertRegex(
            html,
            r'<div class="quick-ask-backdrop"[^>]*id="quick-ask-dialog"[^>]*hidden[^>]*inert',
        )

    @patch.object(stock_app, "_published_report_index_v2", return_value=[])
    def test_reports_page_uses_tw_market_eyebrow(self, _mock_index):
        html = stock_app.app.test_client().get("/reports").get_data(as_text=True)
        self.assertIn("TW MARKET", html)
        self.assertNotIn("TW INDUSTRY", html)

    @patch.object(stock_app, "fetch_published_quant_snapshot")
    def test_stock_detail_demotes_ai_disclaimer_and_hides_tw_chips_for_us(self, fetch):
        tw_snap = quant_snapshot()
        fetch.return_value = tw_snap
        tw_html = stock_app.app.test_client().get("/stock/2330").get_data(as_text=True)
        self.assertIn('<div class="notice-banner" role="status">', tw_html)
        self.assertNotIn('<div class="error-banner" role="status">', tw_html)
        self.assertIn("外資近 5 日（股）", tw_html)

        us_snap = copy.deepcopy(tw_snap)
        us_snap["market"] = "US"
        us_snap["symbol"] = "AAPL"
        us_snap["name"] = "Apple Inc."
        for row in us_snap["daily"]:
            row.pop("ForeignNet", None)
            row.pop("InstitutionalNet", None)
            row.pop("INST_NET_RATIO", None)
        fetch.return_value = us_snap
        us_html = stock_app.app.test_client().get("/stock/AAPL").get_data(as_text=True)
        chips_section = us_html.split('id="chips"', 1)[1].split('id="technicals"', 1)[0]
        self.assertIn("美股不適用", chips_section)
        self.assertNotIn("外資近 5 日（股）", chips_section)
        self.assertNotIn("外資近 20 日（股）", chips_section)
        self.assertNotIn("機構淨流量比", chips_section)

    @patch.object(stock_app, "_published_dashboard_snapshot")
    def test_dashboard_disambiguates_ma20_and_advance_decline_breadth(self, load_snapshot):
        load_snapshot.return_value = observation_dashboard()
        html = stock_app.app.test_client().get("/").get_data(as_text=True)
        self.assertIn("<span>MA20 市場廣度</span>", html)
        self.assertIn('<h3 id="breadth-title">漲跌家數市場廣度</h3>', html)

    def test_stock_compare_formats_prices_and_foreign_net_shares(self):
        rows = [
            {
                "code": "2330",
                "name": "台積電",
                "observation_as_of": "2026-11-24",
                "price": 1085.5,
                "return_5d_pct": 2.5,
                "return_20d_pct": -1.2,
                "trend_observation": "above_ma20",
                "volume_ratio": 1.15,
                "foreign_net_5": 1250000.0,
            },
            {
                "code": "2303",
                "name": "聯電",
                "observation_as_of": "2026-11-24",
                "price": 45.2,
                "return_5d_pct": 0.0,
                "return_20d_pct": 0.0,
                "trend_observation": "mixed",
                "volume_ratio": 0.9,
                "foreign_net_5": 0.0,
            },
        ]
        html = stock_app.app.test_client().get("/learn").get_data(as_text=True)
        self.assertIn("指標辭典", html)
        with stock_app.app.test_request_context("/compare?symbols=2330,2303"):
            rendered = stock_app.app.jinja_env.get_template("stock_compare.html").render(
                rows=rows, symbols=["2330", "2303"]
            )
        self.assertIn("1,085.50", rendered)
        self.assertIn("+1,250,000 股", rendered)
        self.assertIn("0 股", rendered)

    def test_professional_report_rounds_event_floats_and_keeps_zero_neutral(self):
        metadata = ProfessionalReportHtmlTests()._metadata()
        metadata["content"]["market_observation"]["return_1d_pct"] = 0.0
        metadata["content"]["industry_observations"][0]["relative_return_5d_pct"] = 0.0
        metadata["content"]["stock_events"] = [
            {
                "symbol": "3227",
                "name": "原相",
                "event_type": "price_move",
                "severity": "high",
                "observation": "單日漲幅異常",
                "metric_value": 61.19842802798847,
                "unit": "pct",
                "as_of": "2026-07-17",
            },
            {
                "symbol": "0050",
                "name": "元大台灣50",
                "event_type": "data_warning",
                "severity": "high",
                "observation": "價差警示",
                "metric_value": 1,
                "unit": "flag",
                "as_of": "2026-07-17",
            },
        ]
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view = build_professional_report_view(report)
        env = Environment(
            loader=DictLoader(
                {
                    "reports/post_close_professional.html": (
                        ROOT / "templates" / "reports" / "post_close_professional.html"
                    ).read_text(encoding="utf-8"),
                    "base.html": (ROOT / "templates" / "base.html").read_text(
                        encoding="utf-8"
                    ),
                }
            )
        )
        with stock_app.app.test_request_context("/reports/tw/2026-07-17/post-close"):
            html = stock_app.app.jinja_env.get_template(
                "reports/post_close_professional.html"
            ).render(report=view, market="TW")

        self.assertIn('data-market="TW"', html)
        self.assertIn("數值：61.20%", html)
        self.assertNotIn("61.198428", html)
        self.assertIn("數值：1<", html)
        self.assertIn('<strong class="kpi-value ">\n            +0.00%', html)
        self.assertNotIn('<strong class="kpi-value negative">\n            +0.00%', html)
        self.assertIn('<strong class="return ">+0.00%</strong>', html)
        self.assertIn("badge-market-down", html)

    def test_professional_report_renders_etf_flows_governance_and_quant_diagnostics(
        self,
    ):
        metadata = ProfessionalReportHtmlTests()._metadata()
        report = build_professional_post_close_artifact(
            metadata, code_commit_sha="b" * 40
        )
        view = build_professional_report_view(report)
        view["identity"]["source_manifest_sha256_short"] = "ac57a92ab819"
        view["capital_flows"] = {
            "status": "available",
            "data_as_of": "2026-11-25",
            "reason": None,
            "data": {
                "scope": "TWSE",
                "source": "https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                "foreign_net": -123654.8,
                "investment_trust_net": 55034.7,
                "dealer_net": -12833.2,
                "total_institutional_net": -81453.3,
            },
        }
        view["securities"]["data"]["etf_observations"] = [
            {
                "symbol": "0050",
                "name": "元大台灣50",
                "price": 90.3,
                "return_1d_pct": -5.64,
                "return_5d_pct": -12.01,
                "volume_ratio": 1.88,
                "trend_observation": "above_ma20_ma60",
            },
            {
                "symbol": "0056",
                "name": "元大高股息",
                "price": 45.66,
                "return_1d_pct": -8.57,
                "return_5d_pct": -7.72,
                "volume_ratio": 1.45,
                "trend_observation": "mixed",
            },
            {
                "symbol": "0051",
                "name": "元大中型100",
                "price": 109.85,
                "return_1d_pct": -5.71,
                "return_5d_pct": -12.01,
                "volume_ratio": 1.54,
                "trend_observation": "above_ma20",
            },
            {
                "symbol": "0052",
                "name": "富邦科技",
                "price": 52.15,
                "return_1d_pct": -5.44,
                "return_5d_pct": -4.14,
                "volume_ratio": 1.14,
                "trend_observation": "mixed",
            },
        ]
        view["quantitative_research"] = {
            "status": "available",
            "reason": None,
            "data": {},
            "ai_label": "AI 模型參考建議",
            "output_name": "模型方向參考",
            "headline": "市場廣度與波動率因子解釋型回歸",
            "summary": "採用 Newey-West HAC 調整。",
            "sample_count": 240,
            "first_feature_session": "2025-01-02",
            "last_feature_session": "2026-11-25",
            "dependent_variable": "forward_5d_median_return_pct",
            "hac_max_lags": 5,
            "confidence_level_pct": 95,
            "factors": [
                {
                    "display_label": "MA20 廣度",
                    "coefficient": 0.012345,
                    "standard_error": 0.004567,
                    "t_statistic": 2.7031,
                    "p_value": 0.0074,
                    "confidence_interval_low": 0.003345,
                    "confidence_interval_high": 0.021345,
                    "direction": "正向",
                }
            ],
            "fit_statistics": {
                "r_squared": 0.1421,
                "adjusted_r_squared": 0.1288,
                "residual_standard_error": 0.021543,
                "f_p_value": 0.0012,
            },
            "diagnostics": {
                "multicollinearity": {"max_vif": 1.85},
                "heteroskedasticity": {"p_value": 0.241},
                "autocorrelation": {"durbin_watson": 1.94},
                "residual_normality": {"jarque_bera_p_value": 0.083},
            },
            "warnings": [],
            "limitations": "歷史樣本不等於未來結果。",
            "disclosure": "僅供研究參考。",
        }
        with stock_app.app.test_request_context("/reports/tw/2026-11-25/post-close"):
            html = stock_app.app.jinja_env.get_template(
                "reports/post_close_professional.html"
            ).render(report=view, market="TW")

        self.assertIn('class="kpi-card etf-card"', html)
        self.assertIn('class="etf-metrics"', html)
        self.assertIn("-123,654.8", html)
        self.assertIn("-5.64%", html)
        self.assertIn("-12.01%", html)
        self.assertIn("站上 MA20 與 MA60", html)
        self.assertIn("<code>ac57a92ab819</code>", html)
        self.assertIn('id="quantitative-research"', html)
        self.assertIn('class="diagnostics-grid"', html)
        self.assertIn('class="diag-card"', html)
        self.assertIn("<code>forward_5d_median_return_pct</code>", html)
        self.assertIn("<code>1.85</code>", html)
        self.assertIn("<code>p=0.241</code>", html)
        self.assertIn("<code>1.94</code>", html)
        self.assertIn("<code>p=0.083</code>", html)

    def test_app_js_and_css_enforce_market_colors_and_session_guard(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")

        self.assertIn('document.body.dataset.accountSession !== "present"', js)
        self.assertIn("--market-chart-up", js)
        self.assertIn("--market-chart-down", js)
        self.assertNotIn("#7c1f31", js)
        self.assertNotIn("#3f8060", js)
        self.assertIn("dialog.inert = false", js)
        self.assertIn("dialog.inert = true", js)

        self.assertIn('body[data-market="US"]', css)
        self.assertIn("--market-up:#18704a", css)
        self.assertIn("--market-down:#b53a4c", css)
        self.assertIn("--market-up-on-dark:#a9dbc3", css)
        self.assertIn("--market-down-on-dark:#f2aaa3", css)
        self.assertNotIn(".positive{color:var(--command-sage)", css)
        self.assertNotIn(".negative{color:var(--command-coral)", css)
        self.assertIn(".notice-banner{", css)
        self.assertIn("white-space:nowrap", css)
        after_900 = css[css.rfind("@media(max-width:900px)") :]
        self.assertIn("@media(max-width:760px)", after_900)
        self.assertIn("background:var(--command-paper)", after_900)
        self.assertIn("box-shadow:none", after_900)
        self.assertIn("padding:18px 14px 116px", after_900)
        self.assertIn("minmax(min(180px,100%),1fr)", css)
        self.assertIn("repeat(auto-fit,minmax(min(220px,100%),1fr))", css)


if __name__ == "__main__":
    unittest.main()
