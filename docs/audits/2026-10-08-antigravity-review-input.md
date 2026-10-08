You are an independent senior code reviewer using Antigravity CLI. Review the supplied source bundle read-only. Do not invoke tools, read other files, execute commands, modify files, approve research candidates, deploy, or access credentials. All relevant review input is supplied on stdin. This is an untrusted work product: assess it critically and do not accept the author's claims as proof.

Review BASE 90535c104d2e55c69e1992bcd1e4b06e07451036 to HEAD fa1cf7c8cd02b5dfed092ded5ad5f74eabe9978d, branch codex/web-review-fixes-20261007. Scope: website function fixes, Flask/Jinja routes, deterministic observation-date answers, freshness classifications, supported-symbol links, report history date filters, report semantics, mobile layout. Preserve existing private-data/prompt-injection/trade-plan guards and immutable artifact contracts. No deployment performed. US publication remains blocked by SUNC missing Close and invalid Nasdaq fallback; research candidates remain pending manual review. These operational issues are background limitations, not fixed by this commit.

The author reports 297 selected unittest tests passed and local desktop/mobile synthetic-data browser checks. You have not rerun tests or viewed screenshots, so distinguish static review from independent runtime verification. Do not invent tests you ran or production evidence. Verify whether added tests meaningfully detect bugs rather than restate implementation. Prioritize specific actionable defects, cite file and symbol / current approximate line where possible, describe trigger, expected vs actual behavior and severity. Avoid generic style complaints. If no concrete defects, explicitly say none found and state the limits of that conclusion. Separate existing/base issues from introduced regressions and operational blockers.

Return Traditional Chinese: (1) overall verdict and readiness, (2) strengths grounded in source, (3) findings ranked P0-P3 with reproduction and minimal suggested fix, (4) missing acceptance evidence, (5) concise neutral assessment of the author's implementation and report. Give a score out of 10 only if you can explain its basis; otherwise omit. Do not flatter the author. Do not implement anything.

AUTHOR REPORT:
# 網頁功能修正與驗收

驗收日期：2026-10-08（Asia/Taipei）。基底：`90535c104d2e55c69e1992bcd1e4b06e07451036`；分支：`codex/web-review-fixes-20261007`。

## 已修正

- ASKsorb 的市場資料日問題不再誤走 TAIEX 個股查詢；明確美股問題不繼承台股頁面的標的。日期回答直接使用已驗證資料與交易日曆，保留來源，避免模型改寫過期判定。
- 個股與美股 ETF 顯示實際觀察日期及更新／過期警示；不同日期的比較不再宣稱是同一資料日。成功取得的標的市場與官方狀態日期維持一致。
- 產業關係保留證據，移除未支援韓股的個股與比較連結；既有支援的美股與台股可以比較。
- 報告新增原生日期篩選，較舊報告與長公告可展開閱讀；中立事件不再預設正面，沒有量化章節時不宣稱採用量化模型。既有事件用語轉換只作用於呈現副本。
- 首頁區分指數與全市場股票中位報酬，時間採台北格式；修正手機報告寬度、圖表順序與主要操作的觸控區。
- 研究頁清楚區分候選擷取時間與已審核資料日期；候選仍須人工審核。

## 驗收證據

- 相關 unittest：**297 項通過**，exit code 0；完整輸出：[回歸紀錄](2026-10-07-web-regression.log)。未宣稱已執行整個儲存庫測試集。
- 獨立程式複核完成；先前指出的日期比較、回答過期狀態與成功標的市場問題已修正，無新增可操作 P1／P2。
- 本機使用 `tests.visual_qa_server` 的合成資料，完成 1280×720 桌面與 390×844 手機驗收。首頁、關係頁、台美股專業報告、AAPL 等受檢頁面沒有整頁水平溢出；原始資料日問句、日期篩選、公告展開及過期提示均已實測。
- 手機首頁圖表起點約 713px；受檢來源連結、摘要展開及登入操作的觸控高度至少 44px。
- 畫面：[手機首頁](2026-10-07-web-mobile-home.jpg)、[手機專業報告](2026-10-07-web-mobile-report.jpg)、[手機 ASKsorb](2026-10-07-web-mobile-asksorb.jpg)、[桌面首頁](2026-10-07-web-desktop-home.jpg)。畫面中的價格與日期為本機合成驗收資料，不代表正式資料已更新。

## 仍待處理

- **正式站尚未部署本分支。** 本次未修改正式流量、排程、發布指標或研究審核狀態。
- 美股 PostClose 的 2026-10-07 排程結果為 1；目標資料日 2026-10-06 的 SUNC 缺少 Close，觸發既有發布門檻。唯讀備援診斷亦回報 Nasdaq 歷史資料格式無效。須取得可信價格或官方交易狀態，再重跑及發布；未降低驗證門檻或任意排除標的。
- 研究候選仍待人工核准，頁面說明修正不等於研究內容已發布。

原始問題與正式站審查範圍：[功能審查](2026-10-07-web-function-review.md)。


COMMITTED DIFF WITH CONTEXT:
diff --git a/reporting/professional_html.py b/reporting/professional_html.py
index 63bab43..42a12a4 100644
--- a/reporting/professional_html.py
+++ b/reporting/professional_html.py
@@ -1,36 +1,37 @@
 """Safe HTML view-model adapter for canonical professional reports."""
 
 from __future__ import annotations
 
 import copy
 import datetime
 from typing import Any
 import zoneinfo
 
 from .professional_schema import ProfessionalPostCloseReport, ProfessionalSection
 from .regression_schema import RegressionResearchArtifact
+from stock_papi.services.us_presentation import localize_us_key_event
 
 
 REGRESSION_UNAVAILABLE_REASON = "量化回歸研究目前無法安全顯示。"
 REGRESSION_ARTIFACT_UNAVAILABLE_REASON = "量化回歸研究尚未提供。"
 REGRESSION_UNAVAILABLE_REASONS = frozenset(
     {
         REGRESSION_UNAVAILABLE_REASON,
         REGRESSION_ARTIFACT_UNAVAILABLE_REASON,
     }
 )
 
 
 def _section_view(section: ProfessionalSection) -> dict[str, Any]:
     return {
         "status": section.status,
         "data_as_of": section.data_as_of.isoformat() if section.data_as_of else None,
         "reason": section.reason,
         "data": copy.deepcopy(section.data),
     }
 
 
 def build_professional_report_view(
     report: ProfessionalPostCloseReport,
     *,
     regression_artifact: RegressionResearchArtifact | None = None,
@@ -110,37 +111,37 @@ def build_professional_report_view(
         ]
         if valid_items:
             flows["total_institutional_net"] = sum(valid_items)
 
     return {
         "title": (
             "ABSORB "
             f"{'美股' if identity.market == 'US' else '台股'}市場、產業與量化研究日報"
         ),
         "identity": {
             "report_id": identity.report_id,
             "market": identity.market,
             "source_market_date": identity.source_market_date.isoformat(),
             "applicable_trading_date": identity.applicable_trading_date.isoformat(),
             "published_at": identity.published_at.isoformat(),
             "published_at_taipei": published_taipei,
             "content_sha256_short": identity.content_sha256[:12],
             "source_manifest_sha256_short": identity.source_manifest_sha256[:12],
             "code_commit_sha_short": identity.code_commit_sha[:12],
             "generator_version": identity.generator_version,
             "feature_schema_version": identity.feature_schema_version,
             "recommendation_policy_version": identity.recommendation_policy_version,
             "model_version": identity.model_version,
         },
         "executive_summary": report.executive_summary.to_document(),
-        "key_events": copy.deepcopy(list(report.key_events)),
+        "key_events": [localize_us_key_event(item) for item in copy.deepcopy(list(report.key_events))],
         "market": _section_view(report.market),
         "capital_flows": capital_flows_view,
         "industries": _section_view(report.industries),
         "securities": _section_view(report.securities),
         "quantitative_research": quantitative_research,
         "validation": _section_view(report.validation),
         "next_session": _section_view(report.next_session),
         "governance": _section_view(report.governance),
         "ai_reference": _section_view(report.ai_reference),
         "pdf_download_url": pdf_download_url,
     }
diff --git a/static/app.css b/static/app.css
index 7a6c745..f2bb848 100644
--- a/static/app.css
+++ b/static/app.css
@@ -692,50 +692,52 @@ a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,su
   .report-card{display:grid}
   .report-card-grid,.report-professional-grid{grid-template-columns:1fr}
   .account-action-grid{grid-template-columns:1fr}
   .report-meta{grid-template-columns:repeat(2,minmax(0,1fr))}
   .report-actions .button{flex:1;text-align:center}
 }
 @media(max-width:600px){
   .page{padding-inline:14px}
   .panel{padding:18px}
   .page-header h1,.hero-copy h1,.stock-hero h1{font-size:27px}
   .section-heading h2{font-size:20px}
   .search-control{display:grid}
   .search-control button{width:100%}
 }
 @media(prefers-reduced-motion:reduce){
   html{scroll-behavior:auto}
   .skeleton{animation:none}
   .button,.nav-link,.signal-row,.mobile-nav a,.hero-shortcuts a,.forecast-card,.pick-card,.news-list a{transition:none}
 }
 
 /* ==========================================================================
    ABSORB Institutional Research Report Styling
    ========================================================================== */
 .professional-report {
   max-width: 1120px;
+  width: 100%;
+  min-width: 0;
   margin: 0 auto;
   display: grid;
   gap: 24px;
 }
 
 .report-masthead {
   padding: 28px 32px;
   background: var(--surface);
   border: 1px solid var(--line);
   border-radius: 12px;
 }
 
 .masthead-title-row {
   display: flex;
   justify-content: space-between;
   align-items: flex-start;
   gap: 20px;
   flex-wrap: wrap;
 }
 
 .masthead-title-row h1 {
   margin: 6px 0 10px;
   font: 800 28px/1.3 var(--font-display);
   color: var(--text);
   letter-spacing: -0.02em;
@@ -1456,25 +1458,45 @@ body.sidebar-collapsed .sidebar-nav .nav-link{justify-content:center;padding-inl
  .mobile-primary-nav>a,.mobile-more-menu>summary{display:grid;min-width:0;min-height:44px;place-items:center;padding:0 4px;border:1px solid var(--command-line);border-radius:8px;color:var(--command-muted);font-size:11px;font-weight:750;text-decoration:none;white-space:nowrap}
  .mobile-primary-nav>a.active,.mobile-more-menu[open]>summary{border-color:var(--command-blue);background:var(--command-accent-surface);color:var(--command-ink)}
  .mobile-more-menu{position:relative;min-width:0}
  .mobile-more-menu>summary{cursor:pointer;list-style:none}
  .mobile-more-menu>summary::-webkit-details-marker{display:none}
  .mobile-more-menu>div{position:absolute;right:0;bottom:52px;display:grid;min-width:150px;gap:5px;padding:8px;border:1px solid var(--command-line);border-radius:10px;background:var(--command-paper);box-shadow:0 12px 28px rgb(24 49 71 / 18%)}
  .mobile-more-menu:not([open])>div{display:none}
  .mobile-more-menu>div a{padding:8px 9px;border-radius:6px;color:var(--command-ink);font-size:12px;text-decoration:none;white-space:nowrap}
  .mobile-more-menu>div a:hover,.mobile-more-menu>div a[aria-current="page"]{background:var(--command-accent-surface)}
  /* 手機不顯示右下角浮動 ASKsorb，避免遮住正文與底部導覽；ASKsorb 改由「更多」選單進入。 */
  .quick-ask-trigger{display:none}
  .quick-ask-backdrop{place-items:end center}
  .conversation-panel{min-width:0}
  .conversation-control{display:grid;grid-template-columns:1fr}
  .conversation-control input,.conversation-control button{width:100%;min-width:0}
  .page,.content-column,.main-content{min-width:0}
  .market-action-state{align-items:start;display:grid;gap:3px}
  .freshness-warning{grid-column:auto}
 }
 
 .activity-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.activity-tabs a{display:inline-flex;align-items:center;min-height:44px;padding:8px 18px;border:1px solid var(--command-line);border-radius:999px;background:var(--command-paper);color:var(--command-muted);font-size:13px;font-weight:750;text-decoration:none;transition:all .16s ease}.activity-tabs a.active{background:var(--command-navy);color:#fff;border-color:var(--command-navy);box-shadow:0 4px 12px rgba(18, 38, 67, .12)}.activity-tabs a:hover:not(.active){background:#fff;color:var(--command-ink);border-color:#b9c8cf}.activity-card{display:grid;gap:12px;padding:22px;border:1px solid var(--command-line);border-radius:12px;background:var(--command-paper);box-shadow:0 2px 8px rgba(18, 38, 67, .03);margin:12px 0}.activity-card>div{display:grid;gap:4px}.activity-card h2{margin:0;font-size:19px;font-weight:750;letter-spacing:-.02em;color:var(--command-navy)}.activity-card dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px 16px;margin:12px 0;padding:14px;border-radius:10px;background:var(--command-accent-surface)}.activity-card dt{color:var(--command-muted);font-size:11px;font-weight:700}.activity-card dd{margin:0;font-size:12.5px;font-weight:750}.activity-actions{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-top:6px}.activity-card button,.activity-card .source-link{display:inline-flex;align-items:center;justify-self:start;width:fit-content;min-height:40px;padding:6px 16px;border:1px solid var(--command-line);border-radius:999px;background:#fff;color:var(--command-navy);font-size:12.5px;font-weight:750;text-decoration:none;cursor:pointer;transition:all .15s ease}.activity-card button:hover,.activity-card .source-link:hover{border-color:var(--command-navy);background:#edf2f6}.activity-card .source-link{overflow-wrap:anywhere;word-break:break-all}.activity-list .empty-state{padding:20px;text-align:center}@media(max-width:480px){.activity-card{padding:14px}.research-filters{display:grid;grid-template-columns:1fr;gap:8px}}
 .trading-page{display:grid;gap:18px;max-width:1280px}.trading-page .panel{padding:22px 24px;border:1px solid var(--command-line);border-radius:12px;background:rgb(247 246 242 / 74%);box-shadow:0 2px 8px rgba(18, 38, 67, .03)}.trading-page form[data-preference-form]{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:10px}.trading-page form[data-preference-form] label{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:8px 18px;border:1px solid var(--command-line);border-radius:999px;background:#fff;font-size:13px;font-weight:750;cursor:pointer;transition:all .15s ease}.trading-page form[data-preference-form] label:has(input:checked){border-color:var(--command-navy);background:var(--command-navy);color:#fff}.trading-page form[data-preference-form] label:hover{border-color:var(--command-navy)}.trading-page form[data-preference-form] button{min-height:44px;padding:0 22px;border-radius:8px;margin-left:auto}.trading-page button,.trade-plan-panel button{min-height:44px;padding:0 20px;border-radius:8px;width:auto;justify-self:start}.trading-page form[data-notify-form]{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-top:14px}.trading-page form[data-notify-form] label{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:8px 12px;font-size:13.5px;font-weight:650;cursor:pointer}.trading-page form[data-feedback-form]{display:grid;grid-template-columns:minmax(180px,1fr) minmax(180px,1fr);gap:14px;margin-top:14px}.trading-page form[data-feedback-form] label{display:grid;gap:6px;font-size:12px;font-weight:700;color:var(--command-muted)}.trading-page form[data-feedback-form] label:nth-child(3){grid-column:1/-1}.trading-page form[data-feedback-form] select,.trading-page form[data-feedback-form] textarea{width:100%;padding:10px 14px;border:1px solid var(--command-line);border-radius:8px;background:#fff;font:inherit;color:var(--command-ink)}.trading-page form[data-feedback-form] select:focus,.trading-page form[data-feedback-form] textarea:focus{outline:0;border-color:var(--command-navy);box-shadow:0 0 0 3px rgba(18, 38, 67, .08)}.trading-page form[data-feedback-form] button{grid-column:1/-1;justify-self:start}.trade-plan-panel{border:1px solid var(--command-line);border-radius:12px;padding:20px;margin:12px 0;background:var(--command-paper)}.trade-plan-card{border:1px solid var(--command-line);border-radius:10px;padding:16px;margin:10px 0;background:#fff}.trading-page a,.trade-plan-panel a{overflow-wrap:anywhere;word-break:break-all}@media(max-width:760px){.trading-page form[data-preference-form]{display:grid;grid-template-columns:1fr}.trading-page form[data-preference-form] button{margin-left:0;width:100%}.trading-page form[data-preference-form] label{justify-content:center}}@media(max-width:480px){.trade-plan-panel{padding:14px}.trading-page form[data-feedback-form]{grid-template-columns:1fr}}
 .learn-page{display:grid;gap:20px}.learn-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:18px}.learn-grid article{display:flex;gap:18px;align-items:start;padding:24px;border:1px solid var(--command-line);border-radius:14px;background:var(--command-paper);box-shadow:0 2px 8px rgba(18, 38, 67, .03);transition:all .18s ease}.learn-grid article:hover{border-color:var(--command-navy);transform:translateY(-2px);box-shadow:0 8px 24px rgba(18, 38, 67, .06)}.learn-index{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:8px;background:var(--command-accent-surface);color:var(--command-navy);font-family:var(--font-display);font-size:15px;font-weight:800;flex-shrink:0}.learn-grid article strong{display:block;font-size:18px;font-weight:750;color:var(--command-navy);margin-bottom:6px}.learn-grid article p{margin:0;color:var(--command-muted);font-size:13.5px;line-height:1.65}.learn-page .risk-panel{padding:22px 24px;border:1px solid var(--command-line);border-radius:12px;background:rgb(247 246 242 / 80%)}@media(max-width:760px){.learn-grid{grid-template-columns:1fr}}
 .research-page .research-filters select{min-height:42px;max-width:100%;padding:0 12px;border:1px solid var(--command-line);border-radius:8px;background:#fff;color:var(--command-ink);font:inherit}.research-page .research-filters select:focus-visible{outline:2px solid var(--command-navy);outline-offset:2px}
 
+/* Functional review: disclosure controls and shrinkable report layout. */
+.professional-report > * { min-width: 0; }
+.event-group-heading,
+.report-filters button,
+.topbar-account { min-height: 44px; }
+.relationship-card details summary,
+.research-page details summary,
+.report-history-older > summary,
+.report-technical > summary { min-height: 44px; padding: 10px 0; cursor: pointer; }
+.research-page .source-link { display: inline-flex; align-items: center; min-height: 44px; }
+.report-history-older { display: grid; gap: 12px; }
+.report-history-older > summary { font-weight: 700; }
+.report-date-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 16px 0; }
+.report-date-filter input { min-height: 44px; max-width: 100%; padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; }
+@media (max-width: 760px) {
+  .research-dashboard .market-index-canvas { grid-row: 1; }
+  .research-summary { padding: 12px 2px; }
+  .report-date-filter label { flex-basis: 100%; }
+}
+
diff --git a/static/app.js b/static/app.js
index 1a408cf..7143e42 100644
--- a/static/app.js
+++ b/static/app.js
@@ -1,26 +1,27 @@
 const bySelector = (selector, root = document) => root.querySelector(selector);
+const riskStateLabels = {normal: "一般", cautious: "謹慎", elevated: "升高", defensive: "防守"};
 
 function migrateLegacyHashRoute() {
   if (!["/", "/dashboard"].includes(window.location.pathname)) return;
   const target = {
     "#market-pulse": "/market",
     "#daily-focus": "/",
     "#market-heatmap": "/industries",
     "#industry-observations": "/industries",
     "#stock-search": "/stocks",
     "#stock-events": "/stocks",
     "#etf-observations": "/stocks?tab=etf",
     "#learn": "/learn",
   }[window.location.hash];
   if (target) window.location.replace(target);
 }
 
 function element(tag, className, text) {
   const item = document.createElement(tag);
   if (className) item.className = className;
   if (text !== undefined && text !== null) item.textContent = String(text);
   return item;
 }
 
 function replaceContent(container, items) {
   container.replaceChildren(...items);
@@ -81,79 +82,75 @@ function displayNumber(value, digits = 2, suffix = "") {
 }
 
 function displaySigned(value, digits = 2, suffix = "%") {
   const number = Number(value);
   if (!Number.isFinite(number)) return "資料不足";
   return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}${suffix}`;
 }
 
 function observationTrend(value) {
   return {
     above_ma20_ma60: "站上 MA20 與 MA60",
     above_ma20: "站上 MA20",
     below_ma60: "低於 MA60",
     mixed: "均線交錯",
     insufficient: "資料不足",
   }[value] || "資料不足";
 }
 
 function renderDashboard(data) {
   if (!data || data.product_mode !== "observation") {
     throw new Error("observation dashboard required");
   }
   const marketData = data.market_observation || {};
   const hero = bySelector("[data-market-hero]");
   if (hero) {
-    const riskState = {
-      normal: "一般",
-      cautious: "謹慎",
-      elevated: "升高",
-    }[marketData.risk_state] || "資料不足";
+    const riskState = riskStateLabels[marketData.risk_state] || "資料不足";
     replaceContent(hero, [
       element("p", "action-label action-insufficient", `市場風險狀態：${riskState}`),
       element("h1", "market-headline", `上漲 ${marketData.advancing_count ?? "—"} 檔、下跌 ${marketData.declining_count ?? "—"} 檔`),
       element("p", "hero-risk", `近 5 日市場中位報酬 ${displaySigned(marketData.return_5d_pct)}`),
       element("p", "muted small", `資料日 ${data.observation_as_of || "待更新"} · 覆蓋率 ${data.data_quality?.coverage != null ? displayNumber(data.data_quality.coverage * 100, 1, "%") : "資料不足"}`),
     ]);
   }
 
   const market = bySelector("[data-market-summary]");
   if (market) {
     replaceContent(market, [
       card("article", "pulse-card", [["span", "", "單日中位報酬"], ["strong", "", displaySigned(marketData.return_1d_pct)], ["small", "muted", "全市場有效樣本"]]),
       card("article", "pulse-card", [["span", "", "站上 MA20"], ["strong", "", displayNumber(marketData.ma20_breadth_pct, 1, "%")], ["small", "muted", "市場均線廣度"]]),
       card("article", "pulse-card", [["span", "", "20 日已實現波動"], ["strong", "", displayNumber(marketData.realized_volatility_20d_pct, 1, "%")], ["small", "muted", `20 日新高 ${marketData.new_high_20d_count ?? "—"}／新低 ${marketData.new_low_20d_count ?? "—"}`]]),
     ]);
   }
   const status = bySelector(".status-dot");
   if (status) status.textContent = data.observation_as_of ? `資料日 ${data.observation_as_of}` : "資料不足";
 
   const focus = bySelector("[data-daily-focus]");
   if (focus) {
     const items = Array.isArray(data.daily_focus) ? data.daily_focus : [];
     replaceContent(focus, items.length ? items.map((text, index) =>
-      card("article", "focus-card", [["span", "", `焦點 ${index + 1}`], ["strong", "", text]])
+      card("article", "focus-card", [["span", "", `焦點 ${index + 1}`], ["strong", "", text.replace(/^市場風險狀態[:：]\s*(normal|cautious|elevated|defensive)$/, (_, state) => `市場風險狀態：${riskStateLabels[state]}`)]])
     ) : [emptyState("今日焦點資料不足。")]);
   }
 
   const heatmap = bySelector("[data-market-heatmap]");
   if (heatmap) {
     const cells = data.heatmap || [];
     if (cells.length > 0 && cells.length < 3) {
       heatmap.style.gridTemplateColumns = `repeat(${cells.length}, minmax(0, 1fr))`;
     } else {
       heatmap.style.gridTemplateColumns = "";
     }
     replaceContent(heatmap, cells.length ? cells.map((item) =>
       card("a", `heatmap-cell ${["hot", "cold", "steady"].includes(item.tone) ? item.tone : "steady"}`, [
         ["span", "", item.name],
         ["strong", "", displaySigned(item.metric_value_pct)],
         ["small", "", `${item.available_count ?? "—"} 檔 · 覆蓋 ${item.coverage != null ? displayNumber(item.coverage * 100, 1, "%") : "資料不足"}`],
       ], "/industries")
     ) : [emptyState("產業相對報酬資料不足。")]);
   }
 
   const industries = bySelector("[data-industry-observations]");
   if (industries) {
     const items = Array.isArray(data.industry_observations) ? data.industry_observations : [];
     replaceContent(industries, items.length ? items.map((item) =>
       card("article", "forecast-card", [
@@ -191,50 +188,51 @@ function renderDashboard(data) {
         const severity = item.official ? "官方" : ({ high: "極端", medium: "顯著", low: "注意" }[item.severity] || "注意");
         const unit = ({ pct: "%", ratio: "倍", index: "", price: "", flag: "" })[item.unit] ?? item.unit ?? "";
         return card("a", `pick-card event-card severity-${item.severity || "low"}`, [
           ["span", "badge-stock", `${item.name} · ${item.symbol}`],
           ["strong", "", item.observation],
           ["p", Number(item.metric_value) > 0 ? "positive" : Number(item.metric_value) < 0 ? "negative" : "", `${item.metric_value ?? "—"}${unit}`],
           ["b", "event-severity", severity],
           ["small", "", `${item.official ? "驗證日" : "資料日"} ${item.as_of || data.observation_as_of}`],
         ], stockHref(item.symbol));
       }
       ) : [emptyState(`目前沒有${title}事件。`)]);
       section.append(heading, list);
       return section;
     }));
   }
 
   const etfs = bySelector("[data-etf-observations]");
   if (etfs) {
     const items = Array.isArray(data.etf_observations) ? data.etf_observations : [];
     replaceContent(etfs, items.length ? items.map((item) =>
       card("a", "pick-card", [
         ["span", "badge-etf", `${item.name} · ${item.symbol}`],
         ["strong", "", `收盤 ${displayNumber(item.price)}`],
         ["p", "", `單日 ${displaySigned(item.return_1d_pct)} · 5 日 ${displaySigned(item.return_5d_pct)}`],
         ["small", "", `${observationTrend(item.trend_observation)} · 量比 ${displayNumber(item.volume_ratio)}`],
+        ["small", "", `資料日 ${item.as_of || data.observation_as_of || "未提供"}`],
       ], stockHref(item.symbol))
     ) : [emptyState("ETF 觀察資料不足。")]);
   }
 }
 
 function loginLocation() {
   const returnTo = `${window.location.pathname}${window.location.search}`;
   return `/auth/line/login?return_to=${encodeURIComponent(returnTo)}`;
 }
 
 function updateAccountInterface(data) {
   window.absorbAccount = data;
   const account = bySelector("[data-account-nav]");
   if (account) {
     const profile = element("a", "account-profile-link");
     profile.href = "/account";
     if (data.user.picture_url) {
       const picture = element("img", "account-avatar");
       picture.src = data.user.picture_url;
       picture.alt = "";
       picture.referrerPolicy = "no-referrer";
       profile.append(picture);
     }
     const label = element("span", "");
     label.append(element("strong", "", data.user.display_name));
diff --git a/stock_papi/application.py b/stock_papi/application.py
index e4ead8a..1335b0c 100644
--- a/stock_papi/application.py
+++ b/stock_papi/application.py
@@ -624,50 +624,51 @@ def _published_us_securities_observation():
         or hashlib.sha256(raw).hexdigest() != pointer.get("sha256")
     ):
         raise ReportWebError("美股個股觀察來源驗證失敗")
     try:
         report = ProfessionalPostCloseReport.from_document(json.loads(raw))
         validate_professional_report_binding(
             route_source_date=item.get("source_market_date"),
             metadata=metadata,
             pointer=pointer,
             report=report,
         )
     except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
         raise ReportWebError("美股個股觀察來源驗證失敗") from exc
     if report.identity.market != "US" or report.securities.status != "available":
         raise ReportWebError("美股個股觀察市場或狀態不符")
     data = report.securities.data
     if (
         not isinstance(data, dict)
         or not isinstance(data.get("stock_events"), list)
         or not isinstance(data.get("etf_observations"), list)
     ):
         raise ReportWebError("美股個股觀察格式不合法")
     return {
         "stock_events": list(data.get("stock_events") or []),
         "etf_observations": list(data.get("etf_observations") or []),
+        "observation_as_of": report.identity.source_market_date.isoformat(),
     }
 
 
 
 def _gcs_get_dashboard_object(object_name, max_bytes):
     return _gcs_get_allowed_object(object_name, max_bytes, "dashboard/v1/")
 
 
 def _gcs_get_preview_object(object_name, max_bytes):
     return _gcs_get_allowed_object(object_name, max_bytes, "previews/")
 
 
 def _gcs_get_prediction_object(object_name, max_bytes):
     return _gcs_get_allowed_object(object_name, max_bytes, "predictions/v1/")
 
 
 def _published_dashboard_snapshot(today=None):
     if PREVIEW_CANDIDATE_PREFIX:
         return load_preview_dashboard_snapshot(
             PREVIEW_CANDIDATE_PREFIX,
             load_object=_gcs_get_preview_object,
             cache=_DASHBOARD_CACHE,
         )
     return load_dashboard_snapshot(
         today=today,
@@ -2169,217 +2170,269 @@ def _asksorb_grounded_answer(question, evidence, *, data_as_of, tools_used, cita
         response = asksorb_model.generate_content(
             prompt,
             request_options={"timeout": 8},
             generation_config={"max_output_tokens": 512, "temperature": 0.1},
         )
         text = str(getattr(response, "text", "") or "").strip()
     except Exception:
         return None
     forbidden = ("建議買入", "建議賣出", "可以買", "適合進場", "可以追高", "上漲機率")
     grounding = [{"data": evidence}, {"data": {"metric_period_days": [1, 5, 20, 60]}}]
     if not text or any(term in text for term in forbidden):
         return None
     if not numbers_are_grounded(text, question, grounding):
         return None
     if data_as_of:
         text += f"\n\n資料截至：{data_as_of}｜內容只描述已發布資料。"
     return ConversationAnswer(
         text,
         data_as_of=data_as_of,
         data_quality="available",
         tools_used=tools_used,
         citations=tuple(citations),
     )
 
 
+def _observation_date_answer(question, *, market, data_as_of, tools_used, citations, subject=None):
+    if not any(term in question for term in ("資料日", "資料截至", "過期", "最新資料", "更新時間")):
+        return None
+    from stock_papi.web.routes.system import create_data_freshness_loader
+
+    freshness = create_data_freshness_loader(
+        load_dashboard_snapshot=_published_dashboard_snapshot,
+        load_report_index_v2=_published_report_index_v2,
+    )(market, observation_as_of=data_as_of)
+    status = freshness["status"]
+    label = {"current": "資料最新", "updating": "更新中", "stale": "資料過期",
+             "unavailable": "暫時無法核對新鮮度"}[status]
+    date = freshness.get("source_market_date")
+    return ConversationAnswer(
+        f"{subject or ('美股' if market == 'US' else '台股')}最近一次已驗證資料日：{date or '未提供'}。"
+        f"資料狀態：{label}。資料日依市場交易日曆核對，不代表今日即時行情。",
+        data_as_of=date, data_quality="available" if status == "current" else "unavailable" if status == "unavailable" else "stale",
+        stale=status in {"stale", "updating"},
+        tools_used=tools_used + ("verified_data_freshness",), citations=tuple(citations),
+    )
+
+
 def _observation_conversation(
     *, question, access, market_context="TW", page_context="home",
     symbol_context=None, principal=None,
 ):
     try:
         question = validate_question(question)
     except InputRejected as exc:
         return ConversationAnswer(str(exc))
     if looks_like_prompt_injection(question):
         return ConversationAnswer(
             "無法執行要求：ABSORB 不會忽略系統規則、揭露提示或讀取未授權資料。"
         )
     if access == "public" and any(
         term in question for term in ("我的自選", "我的關注", "我的提醒", "我的警示")
     ):
         return ConversationAnswer(
             "這項查詢需要先使用 LINE 登入；目前未讀取任何私人資料。"
         )
     research_kind = _research_query_kind(question)
     try:
         from absorb.conversation.policies import is_probability_request as _is_prob
         from absorb.conversation.policies import is_trade_plan_request as _is_trade
     except Exception:
         _is_prob = lambda q: False
         _is_trade = lambda q: False
     if _is_prob(question):
         return ConversationAnswer(
             "AI 預測研究中。正式服務目前只呈現已驗證的市場實況，"
             "不提供上漲機率、排名、強行動或績效背書。"
         )
     if any(
         term in question
         for term in (
             "預測", "機率", "模型", "回測", "勝率", "績效",
             "推薦", "可以買", "能買", "追高", "進場",
         )
     ) and research_kind != "opinions":
         if not _is_trade(question):
             return ConversationAnswer(
                 "AI 預測研究中。正式服務目前只呈現已驗證的市場實況，"
                 "不提供操作判斷或研究結果。"
             )
 
     entities = resolve_entities(question, _conversation_search_stock)
-    if not entities and page_context == "stock" and symbol_context:
+    explicit_us_market = not entities and any(term in question for term in ("美股", "美國股市"))
+    if explicit_us_market:
+        market_context = "US"
+    if not entities and not explicit_us_market and page_context == "stock" and symbol_context:
         code, name = _conversation_search_stock(symbol_context.strip())
         if code:
             code = str(code).upper()
             canonical_market = "TW" if code == "TAIEX" or is_taiwan_symbol(code) else "US"
             if market_context in (None, canonical_market):
                 entities = [{"market": canonical_market, "symbol": code, "name": name or code}]
 
     try:
         from absorb.conversation.policies import is_trade_plan_request as _is_trade2
         from absorb.conversation.policies import mentions_person_or_holdings as _mentions
     except Exception:
         _is_trade2 = lambda q: False
         _mentions = lambda q: False
     if _is_trade2(question) or (_mentions(question) and entities):
         if _trade_plan_beta_allowed(principal):
             return _answer_trade_plan(question=question, principal=principal,
                                       entities=entities, market_context=market_context)
         if _is_trade2(question):
             return ConversationAnswer(
                 "交易計畫為受邀試用功能，目前帳號尚未受邀；未讀取任何私人計畫或跟隨清單。"
                 "公開大咖動態仍可查看，對應頁面：/perspectives。"
             )
     structured_answer = _research_catalog_answer(
         question, access=access, principal=principal, entities=entities,
         market_context=market_context,
     )
     if structured_answer is not None:
         return structured_answer
 
+    # Market aliases are not stock snapshots. Explicit market questions also
+    # override the page's market rather than inheriting a stock-page context.
+    if any(entity["symbol"] == "TAIEX" for entity in entities):
+        entities = [entity for entity in entities if entity["symbol"] != "TAIEX"]
+        if not entities:
+            market_context = "TW"
+
     if entities:
         observations = []
         for entity in entities:
             data = build_stock_observation(
                 fetch_published_quant_snapshot(entity["symbol"]),
                 get_stock_name=get_stock_name,
             )
             if isinstance(data, dict):
                 observations.append(data)
         if not observations:
             return ConversationAnswer("已驗證的個股觀察資料暫時無法取得。")
         data = observations[0]
+        stock_as_of = data.get("observation_as_of") or data.get("as_of")
         stock_citations = []
         symbol_text = re.fullmatch(r"[A-Z0-9.-]{1,16}", str(data.get("code") or ""))
         if symbol_text:
             stock_citations.append(
                 {
                     "label": f"{data.get('name') or data.get('code')}（{data.get('code')}）個股觀察",
                     "url": f"/stock/{data.get('code')}",
-                    "date": data.get("as_of"),
-                    "chapters": ["價格與均線", "籌碼觀察", "風險事件"],
+                    "date": stock_as_of,
+                    "chapters": ["官方交易狀態"] if data.get("observation_kind") != "regular_price" else ["價格與均線", "籌碼觀察", "風險事件"],
                 }
             )
+        date_answer = _observation_date_answer(
+            question, market=data.get("market"), data_as_of=stock_as_of,
+            tools_used=("verified_observation_snapshot",), citations=stock_citations,
+            subject=f"{data.get('name') or data.get('code')}（{data.get('code')}）",
+        )
+        if date_answer is not None:
+            return date_answer
         generated = _asksorb_grounded_answer(
             question,
             {"stocks": observations},
-            data_as_of=data.get("as_of"),
+            data_as_of=stock_as_of,
             tools_used=("verified_observation_snapshot",),
             citations=stock_citations,
         )
         if generated is not None:
             return generated
         trend = {
             "above_ma20_ma60": "站上 MA20 與 MA60",
             "above_ma20": "站上 MA20",
             "below_ma60": "低於 MA60",
             "mixed": "均線交錯",
         }.get(data.get("trend_observation"), "資料不足")
         events = "；".join(data.get("risk_events", [])[:3]) or "未觸發額外事件"
         text = (
             f"{data['name']}（{data['code']}）市場觀察："
             f"最新收盤 {_observation_number(data.get('price'))}，"
             f"均線狀態為{trend}，"
             f"RSI {_observation_number(data.get('rsi'), 1)}，"
             f"量比 {_observation_number(data.get('volume_ratio'))}。"
             f"已觸發事件：{events}。\n\n"
-            f"資料截至：{data.get('as_of') or '未提供'}｜"
+            f"資料截至：{stock_as_of or '未提供'}｜"
             "內容只描述已發生資料。"
         )
         return ConversationAnswer(
             text,
-            data_as_of=data.get("as_of"),
+            data_as_of=stock_as_of,
             data_quality="available",
             tools_used=("verified_observation_snapshot",),
         )
 
     if market_context == "US":
         report = _conversation_report_lookup("post_close", market="US")
         if report.get("data_quality") != "available":
             return ConversationAnswer("已驗證的美股市場觀察資料暫時無法取得。")
         us_citation = _asksorb_report_citation(
             market="US",
             report_type="post_close",
             source_date=report.get("source_market_date"),
             applicable_date=report.get("applicable_trading_date"),
         )
+        date_answer = _observation_date_answer(
+            question, market="US", data_as_of=report.get("source_market_date"),
+            tools_used=("verified_us_report_index",), citations=[us_citation] if us_citation else [],
+        )
+        if date_answer is not None:
+            return date_answer
         generated = _asksorb_grounded_answer(
             question,
             {"market": "US", "report": report},
             data_as_of=report.get("source_market_date"),
             tools_used=("verified_us_report_index",),
             citations=[us_citation] if us_citation else [],
         )
         if generated is not None:
             return generated
         summary = "；".join(report.get("summary") or []) or report.get("title")
         return ConversationAnswer(
             f"美股市場實況：{summary}\n\n資料截至：{report.get('source_market_date') or '未提供'}｜內容只描述已發布資料。",
             data_as_of=report.get("source_market_date"),
             data_quality="available",
             tools_used=("verified_us_report_index",),
             citations=[us_citation] if us_citation else (),
         )
 
     snapshot = _published_dashboard_snapshot()
     if not isinstance(snapshot, dict) or snapshot.get("product_mode") != "observation":
         return ConversationAnswer("已驗證的市場觀察資料暫時無法取得。")
     dashboard_citation = _asksorb_report_citation(
         market=snapshot.get("market", "TW"),
         report_type="post_close",
         source_date=snapshot.get("observation_as_of"),
         applicable_date=None,
     )
+    date_answer = _observation_date_answer(
+        question, market="TW", data_as_of=snapshot.get("observation_as_of"),
+        tools_used=("verified_observation_dashboard",), citations=[dashboard_citation] if dashboard_citation else [],
+    )
+    if date_answer is not None:
+        return date_answer
     generated = _asksorb_grounded_answer(
         question,
         {
             "market": snapshot.get("market", "TW"),
             "observation_as_of": snapshot.get("observation_as_of"),
             "market_observation": snapshot.get("market_observation", {}),
             "industry_observations": list(snapshot.get("industry_observations") or [])[:10],
             "daily_focus": list(snapshot.get("daily_focus") or [])[:8],
             "stock_events": list(snapshot.get("stock_events") or [])[:12],
             "data_quality": snapshot.get("data_quality", {}),
         },
         data_as_of=snapshot.get("observation_as_of"),
         tools_used=("verified_observation_dashboard",),
         citations=[dashboard_citation] if dashboard_citation else [],
     )
     if generated is not None:
         return generated
     industries = snapshot.get("industry_observations", [])
     industry = next(
         (
             item for item in industries
             if isinstance(item, dict)
             and str(item.get("name") or "") in question
         ),
         None,
diff --git a/stock_papi/web/route_registration.py b/stock_papi/web/route_registration.py
index 2c3b813..33c6954 100644
--- a/stock_papi/web/route_registration.py
+++ b/stock_papi/web/route_registration.py
@@ -45,50 +45,51 @@ def register_routes(app, dependencies):
         load_canonical_object=dependencies["load_canonical_object"],
         load_regression_artifact=dependencies["load_regression_artifact"],
         prediction_capability=dependencies["prediction_capability"],
         load_data_freshness=load_data_freshness,
         load_prediction_snapshot=dependencies["prediction_snapshot"],
     )
     register_market_routes(
         app,
         analyze=dependencies["analyze"],
         stock_observation=dependencies["stock_observation"],
         dashboard_sector_cards=dependencies["dashboard_sector_cards"],
         cached_opportunities=dependencies["cached_opportunities"],
         build_market_heatmap=dependencies["build_market_heatmap"],
         dashboard_top_picks=dependencies["dashboard_top_picks"],
         industry_map=dependencies["industry_map"],
         market_insights_payload=dependencies["market_insights_payload"],
         twstock_codes=dependencies["twstock_codes"],
         is_us_ticker=dependencies["is_us_ticker"],
         find_industry_peers=dependencies["find_industry_peers"],
         get_stock_name=dependencies["get_stock_name"],
         dashboard_snapshot=dependencies["dashboard_snapshot"],
         us_securities_observation=dependencies["us_securities_observation"],
         prediction_snapshot=dependencies["prediction_snapshot"],
         load_report_index_v2=dependencies["load_report_index_v2"],
         load_relationships=dependencies["load_research_relationships"],
+        load_data_freshness=load_data_freshness,
         load_events=dependencies["load_research_events"],
         load_opinions=dependencies["load_public_opinions"],
         load_intel_snapshot=dependencies.get("load_intel_snapshot"),
         intel_enabled=dependencies.get("intel_information_enabled", False),
         resolve_intel_stock_instrument=dependencies.get("resolve_intel_stock_instrument"),
     )
     register_intel_routes(
         app,
         load_snapshot=dependencies.get("load_intel_snapshot"),
         enabled=dependencies.get("intel_information_enabled", False),
     )
     register_research_routes(
         app,
         load_relationships=dependencies["load_research_relationships"],
         load_events=dependencies["load_research_events"],
         load_events_status=dependencies.get("load_research_events_status"),
         load_opinions=dependencies["load_public_opinions"],
         stock_observation=dependencies["stock_observation"],
         get_stock_name=dependencies["get_stock_name"],
         allowed_symbols=dependencies["twstock_codes"],
     )
     register_auth_routes(
         app,
         config=dependencies["line_login_config"],
         auth_store=dependencies["get_auth_store"],
diff --git a/stock_papi/web/routes/dashboard.py b/stock_papi/web/routes/dashboard.py
index dfee313..46b3de2 100644
--- a/stock_papi/web/routes/dashboard.py
+++ b/stock_papi/web/routes/dashboard.py
@@ -1,64 +1,70 @@
 """Dashboard page route registration."""
 
 from flask import abort, make_response, render_template, request
 
 from reporting.exceptions import ReportWebError
 from stock_papi.services.prediction_view import prediction_for
+from stock_papi.services.us_presentation import localize_us_key_event
 
 
 def register_dashboard_page(
     app,
     *,
     load_report_index_v2,
     load_dashboard_snapshot,
     load_data_freshness=None,
     load_prediction_snapshot=None,
     preview_enabled=False,
 ):
     def _snapshot():
         value = load_dashboard_snapshot() or {}
         return value if isinstance(value, dict) else {}
 
     def dashboard_page():
         try:
             reports = load_report_index_v2(market="TW") or []
         except ReportWebError:
             reports = []
         reports = [
             item
             for item in reports
             if isinstance(item, dict) and item.get("market", "TW") == "TW"
         ]
         daily_cards = {
             report_type: next(
                 (item for item in reports if item.get("report_type") == report_type),
                 None,
             )
             for report_type in ("post_close", "pre_market")
         }
         snapshot = _snapshot()
+        snapshot = {**snapshot, "daily_focus": [localize_us_key_event({"headline": text})["headline"]
+                                               for text in snapshot.get("daily_focus", [])]}
+        daily_cards = {kind: {**item, "summary": [localize_us_key_event({"headline": text})["headline"]
+                                                 for text in item.get("summary", [])]} if item else None
+                       for kind, item in daily_cards.items()}
         market_index = snapshot.get("market_index") or {}
         prediction = None
         if load_prediction_snapshot is not None and market_index.get("as_of"):
             try:
                 prediction = prediction_for(
                     load_prediction_snapshot("TW"),
                     "TW",
                     "TAIEX",
                     market_index["as_of"],
                 )
             except Exception:
                 prediction = None
         data_freshness = {}
         if load_data_freshness is not None:
             try:
                 data_freshness["TW"] = load_data_freshness(
                     "TW", reports=reports, snapshot=snapshot
                 )
             except Exception:
                 pass
         response = make_response(render_template(
             "dashboard.html",
             search_query=request.args.get("q", "").strip(),
             search_error=request.args.get("error") == "not-found",
             daily_cards=daily_cards,
diff --git a/stock_papi/web/routes/market.py b/stock_papi/web/routes/market.py
index 2d1a47e..f243145 100644
--- a/stock_papi/web/routes/market.py
+++ b/stock_papi/web/routes/market.py
@@ -3,51 +3,60 @@
 import re
 from datetime import datetime, timezone
 
 from flask import abort, jsonify, make_response, redirect, render_template, request, url_for
 
 from stock_papi.shared.formatting import safe_float as _safe_float
 from stock_papi.services.model_evidence import sanitize_recommendation
 from stock_papi.services.prediction_view import prediction_for
 from stock_papi.services.us_presentation import latest_post_close_item
 from stock_papi.services.opinion_consensus import query_opinions
 from stock_papi.web.routes.intel import sanitize_public_event, sanitize_public_summary
 
 
 def register_market_routes(
     app, *, analyze, stock_observation, dashboard_sector_cards, cached_opportunities,
     build_market_heatmap, dashboard_top_picks, industry_map,
     market_insights_payload, twstock_codes, is_us_ticker,
     find_industry_peers, get_stock_name, dashboard_snapshot,
     us_securities_observation,
     prediction_snapshot,
     load_report_index_v2,
     load_relationships=None, load_events=None, load_opinions=None,
     trading_beta_users=None, trade_plan_builder=None,
     load_intel_snapshot=None, intel_enabled=False,
     resolve_intel_stock_instrument=None,
+    load_data_freshness=None,
 ):
+    def freshness(market, observation_as_of=None):
+        try:
+            if load_data_freshness:
+                return load_data_freshness(market, observation_as_of=observation_as_of)
+        except Exception:
+            pass
+        return {"status": "unavailable", "source_market_date": observation_as_of}
+
     def dashboard_api():
         snapshot = dashboard_snapshot()
         if not isinstance(snapshot, dict):
             return jsonify(
                 {
                     "status": "observation_unavailable",
                     "prediction_status": "AI 預測研究中",
                     "message": "市場觀察資料暫時無法使用",
                 }
             ), 503
         if snapshot.get("product_mode") == "observation":
             return jsonify(
                 {
                     **snapshot,
                     "prediction_status": "AI 預測研究中",
                 }
             )
 
         # Verified preview candidates retain their separate research rendering.
         market = analyze("TAIEX")
         if not market:
             return jsonify({"error": "market data unavailable"}), 503
         sector_cards = dashboard_sector_cards()
         presentation = snapshot.get("presentation") or {}
         baseline_status = snapshot.get("baseline_status")
@@ -260,67 +269,69 @@ def register_market_routes(
                 if isinstance(intel_snapshot, dict):
                     intel_snapshot = dict(intel_snapshot)
                     rows = intel_snapshot.get("events")
                     if isinstance(rows, list):
                         intel_snapshot["events"] = [
                             sanitize_public_event(row) for row in rows if isinstance(row, dict)
                         ]
                     release = intel_snapshot.get("release")
                     summary = sanitize_public_summary(
                         intel_snapshot.get("summary"), intel_instrument_id,
                         release.get("decision_cutoff_at") if isinstance(release, dict) else None,
                     )
                     if intel_snapshot.get("status") in {"available", "partial", "stale"} and summary is None:
                         intel_snapshot.update(
                             status="unavailable", reason_codes=["schema_error"], events=[]
                         )
                     intel_snapshot["summary"] = summary
         return render_template(
             "stock_detail.html", d={**data, "market": market, "prediction": prediction}, peers=peers,
             peer_category=peer_group["category"],
             related_relationships=related_relationships,
             related_events=related_events,
             related_opinions=related_opinions,
             intel_snapshot=intel_snapshot,
             intel_instrument_id=intel_instrument_id,
+            observation_freshness=freshness(market, data.get("observation_as_of") or data.get("as_of")),
         ) if data else "查無資料"
 
     def us_stocks_page():
         try:
             observation = us_securities_observation()
             if (
                 not isinstance(observation, dict)
                 or not isinstance(observation.get("stock_events"), list)
                 or not isinstance(observation.get("etf_observations"), list)
             ):
                 raise ValueError("US securities observation is invalid")
         except Exception:
             return render_template(
                 "stocks.html", observation={}, search_query="",
                 search_error=False, market="US", data_unavailable=True,
             ), 503
         return render_template(
             "stocks.html", observation=observation, search_query="",
             search_error=False, market="US", data_unavailable=False,
+            observation_freshness=freshness("US", observation.get("observation_as_of")),
         )
 
     def market_page():
         snapshot = dashboard_snapshot()
         observation = (
             snapshot
             if isinstance(snapshot, dict)
             and snapshot.get("product_mode") == "observation"
             else {}
         )
         return render_template("market.html", observation=observation)
 
     app.add_url_rule("/api/dashboard", "dashboard_api", dashboard_api)
     app.add_url_rule("/api/market-insights", "market_insights_api", market_insights_api)
     app.add_url_rule(
         "/api/market-chart/<market>",
         "market_chart_refresh_api",
         market_chart_refresh_api,
     )
     app.add_url_rule("/market-map", "market_map_page", market_map_page)
     app.add_url_rule("/stock/<code>", "stock_page", stock_page)
     app.add_url_rule("/us/stocks", "us_stocks_page", us_stocks_page)
     app.add_url_rule("/market", "market_page", market_page)
diff --git a/stock_papi/web/routes/reports.py b/stock_papi/web/routes/reports.py
index f4e4993..d17b9a5 100644
--- a/stock_papi/web/routes/reports.py
+++ b/stock_papi/web/routes/reports.py
@@ -1,59 +1,59 @@
 """Public HTML report routes and legacy compatibility redirects."""
 
 import copy
 import datetime
 import hashlib
 import hmac
 import json
 import os
 import re
 import uuid
 
-from flask import abort, make_response, redirect, render_template, url_for
+from flask import abort, make_response, redirect, render_template, request, url_for
 
 from reporting.exceptions import ReportWebError
 from reporting.web import find_report
 from reporting.professional_html import (
     REGRESSION_ARTIFACT_UNAVAILABLE_REASON,
     build_professional_report_view,
 )
 from reporting.professional_binding import (
     validate_professional_report_binding,
     validate_regression_research_binding,
 )
 from reporting.regression_schema import (
     MAX_REGRESSION_ARTIFACT_BYTES,
     RegressionResearchArtifact,
 )
 from reporting.schemas import ReportMetadataV2
 from stock_papi.services.report_view import (
     build_observation_report_view,
     dedupe_reports_for_list,
 )
 from stock_papi.services.market_summary import build_market_summary_view
-from stock_papi.services.us_presentation import latest_post_close_item
+from stock_papi.services.us_presentation import latest_post_close_item, localize_us_key_event
 from stock_papi.services.prediction_view import prediction_for
 from reporting.config import MAX_CANONICAL_REPORT_BYTES
 from werkzeug.exceptions import HTTPException
 
 
 def _valid_report_date(report_date):
     try:
         parsed = datetime.date.fromisoformat(report_date)
     except ValueError:
         return False
     return parsed.isoformat() == report_date
 
 
 def register_report_routes(
     app, *, load_index, load_metadata, load_index_v2, load_metadata_v2,
     load_metadata_v2_by_sha=None,
     load_canonical_object=None, load_regression_artifact=None,
     prediction_capability=None,
     load_data_freshness=None,
     load_prediction_snapshot=None,
 ):
     observation_mode = (
         prediction_capability is not None
         and prediction_capability.mode == "research"
     )
@@ -344,68 +344,73 @@ def register_report_routes(
                 )
                 response = make_response(
                     render_template("reports/post_close_professional.html", report=view_model)
                 )
             else:
                 abort(404)
             return _secure_response(response)
         except ReportWebError as exc:
             return _report_error(
                 503,
                 report_type=report_type,
                 report_date=date_param,
                 exc=exc,
             )
         except HTTPException:
             raise
         except Exception as exc:
             return _report_error(
                 500,
                 report_type=report_type,
                 report_date=date_param,
                 exc=exc,
             )
 
     def reports_page():
+        selected_date = request.args.get("date", "")
+        if selected_date and not _valid_report_date(selected_date):
+            abort(400)
         if observation_mode:
             reports = []
         else:
             try:
                 reports = load_index()
             except ReportWebError:
                 reports = None
         try:
             reports_v2 = _v2_reports(required=observation_mode)
         except ReportWebError as exc:
             if observation_mode:
                 return _report_error(503, exc=exc)
             reports_v2 = None
         response = make_response(render_template(
-            "reports.html", reports=reports or [],
-            reports_v2=dedupe_reports_for_list(reports_v2 or []),
+            "reports.html", reports=[item for item in reports or []
+                                     if not selected_date or item.get("report_date") == selected_date],
+            reports_v2=_history_reports(reports_v2, selected_date),
             unavailable=reports is None and reports_v2 is None,
             market="TW",
+            selected_date=selected_date,
         ))
         return _secure_response(response)
 
     def report_page(report_date):
         if observation_mode:
             abort(404)
         if not _valid_report_date(report_date):
             abort(404)
         try:
             reports = load_index()
         except ReportWebError:
             return "報告服務暫時無法使用", 503
         if reports is None:
             return "報告服務暫時無法使用", 503
         item = find_report(reports, report_date)
         if item is None:
             abort(404)
         try:
             metadata = load_metadata(item)
         except ReportWebError:
             return "報告內容暫時無法使用", 503
         if metadata is None:
             return "報告內容暫時無法使用", 503
         response = make_response(render_template(
             "report_detail.html",
@@ -434,62 +439,73 @@ def register_report_routes(
             if not items:
                 abort(404)
             response = make_response(render_template(
                 "report_day_index.html",
                 trading_date=trading_date,
                 reports=items,
             ))
             return _secure_response(response)
         except ReportWebError as exc:
             return _report_error(503, report_date=trading_date, exc=exc)
         except HTTPException:
             raise
         except Exception as exc:
             return _report_error(500, report_date=trading_date, exc=exc)
 
     def post_close_report_page(trading_date):
         if not _valid_report_date(trading_date):
             abort(404)
         return _observation_page(trading_date, "post_close", market="TW")
 
     def pre_market_report_page(trading_date):
         if not _valid_report_date(trading_date):
             abort(404)
         return _observation_page(trading_date, "pre_market", market="TW")
 
+    def _history_reports(reports, selected_date):
+        rows = dedupe_reports_for_list(reports or [])
+        return [{**row, "summary": [localize_us_key_event({"headline": text})["headline"]
+                                    for text in row.get("summary", [])]}
+                for row in rows if not selected_date or selected_date == row.get(
+                    "applicable_trading_date" if row.get("report_type") == "pre_market" else "source_market_date")]
+
     def us_reports_page():
+        selected_date = request.args.get("date", "")
+        if selected_date and not _valid_report_date(selected_date):
+            abort(400)
         try:
             reports_v2 = _v2_reports(market="US", required=observation_mode)
         except ReportWebError as exc:
             if observation_mode:
                 return _report_error(503, exc=exc)
             reports_v2 = None
         response = make_response(render_template(
             "reports.html", reports=[],
-            reports_v2=dedupe_reports_for_list(reports_v2 or []),
+            reports_v2=_history_reports(reports_v2, selected_date),
             unavailable=reports_v2 is None,
             market="US",
+            selected_date=selected_date,
         ))
         return _secure_response(response)
 
     def _us_summary_response(template_name):
         try:
             reports = _v2_reports(market="US", required=True)
             item = latest_post_close_item(reports)
             if item is None:
                 raise ReportWebError("美股盤後報告暫時無法使用")
             metadata = load_metadata_v2(item, expected_market="US")
             if metadata is None:
                 raise ReportWebError("美股報告內容暫時無法使用")
             report = _load_verified_professional_report(
                 metadata=metadata,
                 route_source_date=item.get("source_market_date"),
                 expected_market="US",
             )
             if report.identity.market != "US":
                 raise ReportWebError("美股 Canonical Object 市場不一致")
             summary = build_market_summary_view(report)
             context = {
                 "summary": summary,
                 "market": "US",
                 "index_predictions": [],
             }
diff --git a/stock_papi/web/routes/research.py b/stock_papi/web/routes/research.py
index e0d1e4d..35dbc6a 100644
--- a/stock_papi/web/routes/research.py
+++ b/stock_papi/web/routes/research.py
@@ -1,82 +1,87 @@
 """Public research surfaces backed by reviewed, versioned research catalogs."""
 
 import copy
 from datetime import datetime, timedelta, timezone
 from urllib.parse import urlencode
 
 from flask import abort, jsonify, render_template, request
 
 from stock_papi.integrations.market_data.tw_security_master import is_taiwan_symbol
 from stock_papi.integrations.market_data.us_universe import validate_us_ticker
 from stock_papi.services.company_events import CompanyEventSchemaError, split_event_window
 from stock_papi.services.industry_relationships import relationship_is_current
 from stock_papi.services.opinion_consensus import build_consensus, query_opinions
 from stock_papi.services.public_opinions import query_activities
 from stock_papi.services.event_context import annotate_events
+from stock_papi.shared.validation import is_us_ticker
 
 
 _MARKETS = {"TW", "US"}
 _WINDOWS = {1, 7, 28}
 _VIEWS = {"latest", "consensus", "timeline"}
 _STANCES = {"bullish", "bearish", "neutral", "unclear", "conditional", "news", "flow", "trade"}
 _CONTENT_TYPES = {"original_opinion", "news_relay", "flow_observation", "trade_disclosure"}
 _ACTIVITY_WINDOWS = {7, 28, 90}
 _ACTIVITY_TABS = {"latest", "trades", "holdings", "opinions"}
 _ACTIVITY_TYPES = {"trade_disclosure", "holding_snapshot", "self_reported_trade"}
 _ACTIVITY_LABELS = {"trade_disclosure": "官方交易揭露", "self_reported_trade": "當事人自述",
                     "holding_snapshot": "機構季底持倉", "original_opinion": "公開觀點"}
 _PAGE_SIZE = 20
 _LABELS = {'bullish': '看多', 'bearish': '看空', 'neutral': '中立', 'unclear': '未表態',
            'original_opinion': '原創觀點', 'news_relay': '新聞轉述', 'flow_observation': '資金觀察',
            'trade_disclosure': '交易揭露', 'verified': '已核對', 'pending': '待核對',
            'pending_review': '待核對', 'legacy_unverified': '舊紀錄待核對', 'partial': '部分涵蓋',
            'available': '可用', 'unavailable': '暫時無法驗證', 'person': '人物',
            'household': '家庭', 'institution': '機構', 'purchase': '買入', 'sale': '賣出',
            'holding': '持有', 'common_stock': '普通股', 'option': '選擇權', 'self': '本人',
            'spouse': '配偶', 'joint': '共同持有', 'confirmed': '已確認', 'corrected': '已更正',
-           'cancelled': '已取消'}
+           'cancelled': '已取消', 'active': '有效', 'historical': '歷史紀錄'}
 
 
 def _time_label(value):
     if not value:
         return '未提供'
     try:
         parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
         if parsed.tzinfo is None:
             return str(value)
         return parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
     except ValueError:
         return '未提供'
 
 
 def register_research_routes(
     app, *, load_relationships, load_events, load_opinions, load_events_status=None,
     stock_observation, get_stock_name, allowed_symbols,
 ):
     app.jinja_env.filters['research_label'] = lambda value: _LABELS.get(value, value or '未提供')
     app.jinja_env.filters['research_time'] = _time_label
+    def supported_symbol(symbol):
+        permitted = allowed_symbols() if callable(allowed_symbols) else allowed_symbols
+        return symbol in (permitted or ()) or is_us_ticker(symbol)
+
     def add_graph(catalog):
         catalog = copy.deepcopy(catalog or {})
         stages = catalog.get("stages") or []
         graph_nodes = []
         positions = {}
         for stage_index, stage in enumerate(stages):
             nodes = stage.get("nodes") or []
             for node_index, node in enumerate(nodes):
                 symbol = node.get("symbol")
                 if not symbol:
                     continue
                 point = {
                     "symbol": symbol,
                     "name": node.get("name") or symbol,
                     "stage": stage.get("name") or stage.get("id") or "",
                     "x": 120 + stage_index * 250,
                     "y": 90 + node_index * 78,
                 }
                 graph_nodes.append(point)
                 positions[symbol] = point
         graph_edges = []
         for relation in catalog.get("relationships") or []:
             source = relation.get("from") or {}
             target = relation.get("to") or {}
             left = positions.get(source.get("symbol"))
@@ -166,87 +171,87 @@ def register_research_routes(
                 if isinstance(node, dict) and node.get("symbol")
             }
             known_symbols.update(
                 str((endpoint or {}).get("symbol") or "").upper()
                 for item in raw_catalog.get("relationships", [])
                 if isinstance(item, dict)
                 for endpoint in (item.get("from"), item.get("to"))
                 if isinstance(endpoint, dict) and endpoint.get("symbol")
             )
             if focus and focus not in known_symbols:
                 return jsonify({"field": "focus", "reason": "unknown_company"}), 400
             catalog = relationship_view(raw_catalog, focus=focus or None)
         except Exception:
             catalog = {
                 "topic": "產業關係圖",
                 "coverage_note": "產業關係資料暫時無法驗證，請稍後再試。",
                 "stages": [], "relationships": [], "graph_nodes": [],
                 "graph_edges": [], "research_leads": [], "unavailable": True,
             }
         return render_template(
             "industry_relationships.html",
             catalog=catalog,
             relationships=list(catalog.get("relationships") or []),
             research_leads=list(catalog.get("research_leads") or []),
             focus=focus,
+            supported_symbol=supported_symbol,
         )
 
     def relationships_api():
         focus = request.args.get("focus", "").strip().upper()
         try:
             raw_catalog = load_relationships() or {}
             known_symbols = {
                 str(node.get("symbol") or "").upper()
                 for stage in raw_catalog.get("stages", [])
                 if isinstance(stage, dict)
                 for node in stage.get("nodes", [])
                 if isinstance(node, dict) and node.get("symbol")
             }
             known_symbols.update(
                 str((endpoint or {}).get("symbol") or "").upper()
                 for item in raw_catalog.get("relationships", [])
                 if isinstance(item, dict)
                 for endpoint in (item.get("from"), item.get("to"))
                 if isinstance(endpoint, dict) and endpoint.get("symbol")
             )
             if focus and focus not in known_symbols:
                 return jsonify({"field": "focus", "reason": "unknown_company"}), 400
             catalog = relationship_view(raw_catalog, focus=focus or None)
         except Exception:
             return jsonify({
                 "status": "unavailable",
                 "message": "產業關係資料暫時無法驗證",
             }), 503
         return jsonify(catalog)
 
     def compare_page():
         raw = request.args.get("symbols", "")
         symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
-        permitted = {str(item).upper() for item in (allowed_symbols() or set())}
         if not 2 <= len(symbols) <= 4 or len(set(symbols)) != len(symbols):
             return jsonify({"error": "請選擇 2 至 4 檔不同公司"}), 400
-        if any(symbol not in permitted for symbol in symbols):
+        if any(not supported_symbol(symbol) for symbol in symbols):
             return jsonify({"error": "公司代碼無法驗證"}), 400
         rows = []
         for symbol in symbols:
             observation = stock_observation(symbol)
             if not isinstance(observation, dict):
                 observation = {"code": symbol, "name": get_stock_name(symbol)}
             else:
                 observation = dict(observation)
                 observation.setdefault("code", symbol)
                 observation.setdefault("name", get_stock_name(symbol))
             rows.append(observation)
         return render_template("stock_compare.html", rows=rows, symbols=symbols)
 
     def events_page():
         if callable(load_events_status):
             try:
                 raw_events, event_status = load_events_status()
             except Exception:
                 raw_events, event_status = [], "unavailable"
         else:
             try:
                 raw_events = load_events() or []
                 event_status = "available" if raw_events else "empty"
             except Exception:
                 raw_events, event_status = [], "unavailable"
diff --git a/stock_papi/web/routes/system.py b/stock_papi/web/routes/system.py
index d26e7f5..6b12a1c 100644
--- a/stock_papi/web/routes/system.py
+++ b/stock_papi/web/routes/system.py
@@ -134,96 +134,112 @@ def _next_session_for_market(market, value):
 
 
 def create_data_freshness_loader(
     *,
     load_dashboard_snapshot,
     load_report_index_v2,
     now=None,
     next_session_for_market=None,
 ):
     """Create a lazy, market-scoped verified freshness loader."""
 
     def unavailable(source=None, applicable=None):
         return classify_data_freshness(
             source_market_date=source,
             applicable_trading_date=applicable,
             reference_date=None,
             next_session=None,
         )
 
     def load(
         market,
         *,
         reports=_UNSET,
         snapshot=_UNSET,
         reference_now=_UNSET,
+        observation_as_of=_UNSET,
     ):
         if market not in _MARKET_TIMEZONES:
             return unavailable()
 
+        resolver = next_session_for_market or _next_session_for_market
+        if observation_as_of is not _UNSET:
+            source = _parse_iso_date(observation_as_of)
+            if source is None:
+                return unavailable()
+            try:
+                applicable = resolver(market, source)
+                if type(applicable) is not dt.date or applicable <= source:
+                    return unavailable(source.isoformat())
+            except Exception:
+                return unavailable(source.isoformat())
+            reports = [{"market": market, "report_type": "post_close",
+                        "source_market_date": source.isoformat(),
+                        "applicable_trading_date": applicable.isoformat()}]
+            snapshot = {"market": market, "observation_as_of": source.isoformat()}
+
         if reports is _UNSET:
             try:
                 reports = load_report_index_v2(market=market)
             except Exception:
                 return unavailable()
         source, applicable, valid_market = _latest_post_close_dates(
             reports, market=market
         )
         if not valid_market:
             return unavailable()
 
         if market == "TW":
             if snapshot is _UNSET:
                 try:
                     snapshot = load_dashboard_snapshot()
                 except Exception:
                     return unavailable()
             if not isinstance(snapshot, dict):
                 return unavailable()
             if "market" in snapshot and snapshot.get("market") != "TW":
                 return unavailable()
             dashboard_source = _parse_iso_date(snapshot.get("observation_as_of"))
             report_source = source
             source = (
                 dashboard_source.isoformat()
                 if dashboard_source is not None
                 else None
             )
             if source is None or source != report_source:
                 applicable = None
 
         try:
             instant = (
                 (now or _utc_now)()
                 if reference_now is _UNSET
                 else reference_now
             )
             reference = market_local_date(market, now=instant)
         except Exception:
             return unavailable(source, applicable)
 
-        resolver = next_session_for_market or _next_session_for_market
         return classify_data_freshness(
             source_market_date=source,
             applicable_trading_date=applicable,
             reference_date=reference,
             next_session=lambda value: resolver(market, value),
         )
 
     return load
 
 
 def register_system_routes(
     app, *, search_stock, load_data_freshness, now=None
 ):
     def healthz():
         return "ok", 200
 
     def data_health():
         try:
             reference_now = (now or _utc_now)()
         except Exception:
             reference_now = None
         markets = {
             market: load_data_freshness(
                 market, reference_now=reference_now
             )
diff --git a/templates/dashboard.html b/templates/dashboard.html
index 01b5685..e22ae4d 100644
--- a/templates/dashboard.html
+++ b/templates/dashboard.html
@@ -7,76 +7,77 @@
 {% set focus = observation.daily_focus or [] %}
 {% set market_index = observation.market_index or {} %}
 {% set advancing = market.get('advancing_count') %}
 {% set declining = market.get('declining_count') %}
 {% set unchanged = market.get('unchanged_count') %}
 {% set total_count = advancing + declining + unchanged if advancing is not none and declining is not none and unchanged is not none else none %}
 {% set advancing_pct = (advancing / total_count * 100) if total_count else none %}
 {% set declining_pct = (declining / total_count * 100) if total_count else none %}
 {% set available_count = quality.get('available_count', quality.get('symbol_count')) %}
 {% set freshness = (data_freshness|default({}, true)).get('TW', {}) %}
 {% set freshness_label = {'current':'資料最新','updating':'更新中','stale':'資料過期','unavailable':'暫時無法取得'}.get(freshness.get('status'), '暫時無法取得') %}
 <div class="page dashboard-page research-dashboard" data-dashboard-endpoint="/api/dashboard">
   {% if search_error %}<div class="error-banner" role="alert">找不到「{{ search_query }}」，請輸入台股代碼、名稱或美股代碼。</div>{% endif %}
 
   <header class="research-summary" data-research-summary>
     <div class="research-copy">
       <p class="research-status"><span aria-hidden="true"></span>台股市場研究摘要</p>
       <h1>台股市場研究摘要</h1>
       <p class="research-headline">{% if market %}MA20 市場廣度 {{ '%.1f%%'|format(market.get('ma20_breadth_pct')) if market.get('ma20_breadth_pct') is not none else '資料不足' }}，20 日已實現波動 {{ '%.1f%%'|format(market.get('realized_volatility_20d_pct')) if market.get('realized_volatility_20d_pct') is not none else '資料不足' }}，風險狀態為 {{ {'normal':'一般','cautious':'謹慎','elevated':'升高'}.get(market.get('risk_state'), '資料不足') }}。{% else %}已驗證市場觀察尚待發布，暫不形成方向判斷。{% endif %}</p>
       <p class="research-limit">畫面整理已發生的市場廣度、報酬、波動與產業相對強度。缺值維持缺值，所有數據皆以資料基準日為準。</p>
     </div>
     <dl class="research-evidence">
       <div><dt>資料基準日</dt><dd>{{ observation.observation_as_of or '待更新' }}</dd></div>
       <div><dt>資料覆蓋</dt><dd>{{ '%.1f%%'|format(quality.get('coverage') * 100) if quality.get('coverage') is not none else '資料不足' }}</dd></div>
       <div><dt>有效標的</dt><dd>{{ available_count if available_count is not none else '資料不足' }}</dd></div>
-      <div><dt>產生時間</dt><dd>{{ observation.generated_at|replace('T', ' ')|replace('Z', ' UTC') if observation.generated_at else '待更新' }}</dd></div>
+      <div><dt>產生時間（台北）</dt><dd>{{ observation.generated_at|research_time if observation.generated_at else '待更新' }}</dd></div>
     </dl>
   </header>
 
   <section class="research-command" data-market-command aria-labelledby="market-command-title">
     <div class="command-heading"><div><h2 id="market-command-title">市場指揮台</h2><p>價格、廣度、資金與風險同步觀察</p></div><span>資料基準日 {{ observation.observation_as_of or '待更新' }}</span></div>
     <div class="command-grid">
       <div class="command-metrics" aria-label="市場關鍵指標">
         <article><span>市場廣度</span><strong>{{ '%.1f%%'|format(market.get('ma20_breadth_pct')) if market.get('ma20_breadth_pct') is not none else '資料不足' }}</strong><small>站上 MA20</small>{% if market.get('ma20_breadth_pct') is not none %}<progress value="{{ market.get('ma20_breadth_pct') }}" max="100" aria-label="市場廣度 {{ '%.1f%%'|format(market.get('ma20_breadth_pct')) }}">{{ market.get('ma20_breadth_pct') }}%</progress>{% endif %}</article>
         <article><span>成交動能</span><strong>{{ '%.2f'|format(market.get('median_volume_ratio')) if market.get('median_volume_ratio') is not none else '資料不足' }}</strong><small>成交量中位比</small>{% if market.get('median_volume_ratio') is not none %}<progress value="{{ market.get('median_volume_ratio') }}" max="2" aria-label="成交動能 {{ '%.2f'|format(market.get('median_volume_ratio')) }}">{{ market.get('median_volume_ratio') }}</progress>{% endif %}</article>
         <article><span>波動壓力</span><strong>{{ '%.1f%%'|format(market.get('realized_volatility_20d_pct')) if market.get('realized_volatility_20d_pct') is not none else '資料不足' }}</strong><small>20 日已實現波動</small></article>
         <article><span>風險狀態</span><strong>{{ {'normal':'一般','cautious':'謹慎','elevated':'升高'}.get(market.get('risk_state'), '資料不足') }}</strong><small>{{ '已驗證狀態' if market.get('risk_state') in ['normal','cautious','elevated'] else '資料待驗證' }}</small></article>
       </div>
 
       <section class="evidence-canvas market-index-canvas" aria-labelledby="return-title">
         <div class="evidence-canvas-head"><div><span>TAIWAN CAPITALIZATION WEIGHTED INDEX</span><h3 id="return-title">{{ market_index.get('name', '加權指數') }}</h3></div><span>資料日 {{ market_index.get('as_of', observation.observation_as_of or '待更新') }}</span></div>
         {% if market_index.get('price') is not none %}
         <div class="market-index-quote">
           <div><strong>{{ '{:,.2f}'.format(market_index.get('price')) }}</strong><span class="{{ 'positive' if market_index.get('change_pct', 0) > 0 else 'negative' if market_index.get('change_pct', 0) < 0 else '' }}">{{ '{:+,.2f}'.format(market_index.get('change')) if market_index.get('change') is not none else '—' }}（{{ '{:+.2f}%'.format(market_index.get('change_pct')) if market_index.get('change_pct') is not none else '—' }}）</span></div>
           <dl><div><dt>開盤</dt><dd>{{ '{:,.2f}'.format(market_index.get('open')) if market_index.get('open') is not none else '—' }}</dd></div><div><dt>最高</dt><dd>{{ '{:,.2f}'.format(market_index.get('high')) if market_index.get('high') is not none else '—' }}</dd></div><div><dt>最低</dt><dd>{{ '{:,.2f}'.format(market_index.get('low')) if market_index.get('low') is not none else '—' }}</dd></div></dl>
         </div>
         <div id="market-index-chart" class="market-index-chart" data-chart-refresh-url="{{ url_for('market_chart_refresh_api', market='TW') }}" role="img" aria-label="加權指數 K 線圖" aria-describedby="market-index-chart-table"></div>
         <div id="market-index-chart-table" class="sr-only">
           <table><caption>加權指數最近五個交易日 OHLC</caption><thead><tr><th>日期</th><th>開盤</th><th>最高</th><th>最低</th><th>收盤</th></tr></thead><tbody>{% for row in market_index.get('candles', [])[-5:] %}<tr><td>{{ row.time }}</td><td>{{ row.open }}</td><td>{{ row.high }}</td><td>{{ row.low }}</td><td>{{ row.close }}</td></tr>{% endfor %}</tbody></table>
         </div>
         {% else %}<p class="empty-state market-index-empty">已驗證的大盤指數 K 線尚待發布。</p>{% endif %}
+        <p class="muted small">全市場有效股票的中位報酬（與上方指數漲跌幅不同）</p>
         <dl class="return-grid">
           {% for key, label in [('return_1d_pct','1 日'),('return_5d_pct','5 日'),('return_20d_pct','20 日'),('return_60d_pct','60 日')] %}
           {% set value = market.get(key) %}<div><dt>{{ label }}</dt><dd class="{{ 'positive' if value is not none and value > 0 else 'negative' if value is not none and value < 0 else '' }}">{{ '%+.2f%%'|format(value) if value is not none else '資料不足' }}</dd></div>
           {% endfor %}
         </dl>
         <p class="canvas-note">K 線呈現加權指數實際走勢；期間報酬為全市場觀察，兩者分開標示。來源：<a href="https://data.gov.tw/dataset/11755" rel="noopener noreferrer" target="_blank">TWSE 每日指數歷史資料（政府資料開放授權第 1 版）</a>。資料發布後頁面每 30 秒檢查新 K 線；這是日線，不是盤中即時行情。</p>
       </section>
 
       <div class="command-insights">
         <section class="forecast-panel" aria-labelledby="market-forecast-title">
           <div class="insight-heading"><h3 id="market-forecast-title">AI 五日情境</h3><span>{{ market_prediction.as_of if market_prediction else '尚未發布' }}</span></div>
           {% if market_prediction %}
           <div class="forecast-primary"><div><span>{{ market_prediction.probability_label }}</span><strong>{{ '%.1f%%'|format(market_prediction.probability_pct) }}</strong></div><div><span>第 5 個交易日預測價</span><strong>{{ '{:,.2f}'.format(market_prediction.predicted_price) }}</strong></div></div>
           <dl class="forecast-evidence"><div><dt>預估漲跌幅</dt><dd class="{{ 'positive' if market_prediction.predicted_change_pct > 0 else 'negative' if market_prediction.predicted_change_pct < 0 else '' }}">{{ '%+.2f%%'|format(market_prediction.predicted_change_pct) }}</dd></div><div><dt>目標交易日</dt><dd>{{ market_prediction.target_session }}</dd></div></dl>
           <p>{% if market_prediction.validation_mode == 'research' %}AI 五日研究推估，未經回測校準{% else %}{{ '目前正式預測' if market_prediction.status == 'current' else '前次預測，資料日已標示' }}{% endif %}；提供機率與價格估計，不產生買賣指令。</p>
           {% else %}<p class="empty-state">本交易日推估尚未發布；沒有可用產物時不顯示機率或預測價。</p>{% endif %}
         </section>
         <section class="breadth-panel" data-breadth-visual aria-labelledby="breadth-title">
           <div class="insight-heading"><h3 id="breadth-title">市場廣度</h3><span>{{ total_count if total_count is not none else '資料不足' }} 檔</span></div>
           {% if advancing_pct is not none and declining_pct is not none %}
           <div class="breadth-chart"><svg viewBox="0 0 42 42" role="img" aria-label="上漲 {{ advancing }} 檔，下跌 {{ declining }} 檔，持平 {{ unchanged }} 檔"><circle class="breadth-track" cx="21" cy="21" r="15.9155"></circle><circle class="breadth-up" cx="21" cy="21" r="15.9155" stroke-dasharray="{{ '%.2f %.2f'|format(advancing_pct, 100 - advancing_pct) }}" stroke-dashoffset="25"></circle><circle class="breadth-down" cx="21" cy="21" r="15.9155" stroke-dasharray="{{ '%.2f %.2f'|format(declining_pct, 100 - declining_pct) }}" stroke-dashoffset="{{ '%.2f'|format(25 - advancing_pct) }}"></circle><text x="21" y="20">{{ '%.0f%%'|format(advancing_pct) }}</text><text class="breadth-caption" x="21" y="25">上漲占比</text></svg><dl><div><dt>上漲</dt><dd class="positive">{{ advancing }}</dd></div><div><dt>下跌</dt><dd class="negative">{{ declining }}</dd></div><div><dt>持平</dt><dd>{{ unchanged }}</dd></div></dl></div>
           {% else %}<p class="empty-state">市場廣度資料不足。</p>{% endif %}
         </section>
         <section class="risk-panel" aria-labelledby="risk-title"><div class="insight-heading"><h3 id="risk-title">波動與風險</h3><span>20 日觀察</span></div><dl><div><dt>20 日新高</dt><dd>{{ market.get('new_high_20d_count') if market.get('new_high_20d_count') is not none else '資料不足' }}</dd></div><div><dt>20 日新低</dt><dd>{{ market.get('new_low_20d_count') if market.get('new_low_20d_count') is not none else '資料不足' }}</dd></div><div><dt>法人淨流中位</dt><dd>{{ '%+.2f%%'|format(market.get('median_institution_net_ratio_pct')) if market.get('median_institution_net_ratio_pct') is not none else '資料不足' }}</dd></div></dl><p>風險檢查不等同停損建議，需與個別標的事件分開判讀。</p></section>
       </div>
diff --git a/templates/events.html b/templates/events.html
index e0b8b5a..2449033 100644
--- a/templates/events.html
+++ b/templates/events.html
@@ -1,32 +1,32 @@
 {% extends "base.html" %}
 {% block title %}公司事件｜ABSORB{% endblock %}
 {% block content %}
 <div class="page research-page">
   <header class="page-header"><div><p class="eyebrow">COMPANY EVENTS</p><h1>公司事件與公告</h1><p class="page-intro">查看官方重大訊息與已有明確日期的事件。公告時間與生效日期分開呈現；不從公告文字推測未來日期。</p></div></header>
   <section class="panel event-filter-panel">
     <form method="get" class="research-filters">
       <label>市場<select name="market"><option value="TW"{% if selected_market == 'TW' %} selected{% endif %}>台股</option><option value="US"{% if selected_market == 'US' %} selected{% endif %}>美股（尚未接入）</option></select></label>
       <label>公司代碼<input name="symbol" value="{{ selected_symbol or '' }}" placeholder="例如 2330" maxlength="20"></label>
       <label>事件類型<select name="event_type"><option value="">全部類型</option>{% for value in event_types %}<option value="{{ value }}"{% if selected_event_type == value %} selected{% endif %}>{{ value }}</option>{% endfor %}{% if selected_event_type and selected_event_type not in event_types %}<option value="{{ selected_event_type }}" selected>{{ selected_event_type }}</option>{% endif %}</select></label>
       <label>公告分類<select name="category"><option value="">全部分類</option>{% for value in categories %}<option value="{{ value }}"{% if selected_category == value %} selected{% endif %}>{{ value }}</option>{% endfor %}</select></label>
       <label>觀察日期<input type="date" name="as_of" value="{{ event_window.as_of }}"></label>
       <button class="button button-secondary" type="submit">套用篩選</button><a class="button button-secondary" href="/events">清除篩選</a>
     </form>
     <p class="muted small">最近資料核對：{{ checked_at|research_time }}（台北時間）。公告窗口 {{ event_window.past_start }} 至 {{ event_window.as_of }}；未來事件至 {{ event_window.future_end }}。</p>
     <p class="muted small">{{ announcements_total }} 筆窗口內公告 · {{ upcoming_events|length }} 筆已公布未來事件 · 第 {{ event_page }}／{{ event_pages }} 頁。資料為近期官方快照及累積公告，最多 1000 筆並受檔案大小上限限制；不代表完整歷史。公告分類依主旨關鍵字整理，僅供篩選。</p>
   </section>
   {% if event_status == 'unavailable' %}<section class="panel"><p class="empty-state" role="status">事件資料尚未更新；目前未把空結果當成沒有事件。</p></section>
   {% elif event_status == 'source_error' %}<section class="panel"><p class="error-banner" role="status">最近一次官方來源更新失敗；以下保留前次成功核對的公告與時間。</p></section>
   {% elif event_status == 'stale' %}<section class="panel"><p class="error-banner" role="status">公告資料已超過兩日未成功更新；以下為前次可用資料，近期公告可能未涵蓋。</p></section>
   {% elif event_status == 'not_covered' %}<section class="panel"><p class="empty-state" role="status">目前尚未涵蓋{{ '美股公司公告' if selected_market == 'US' else '這家公司或個別公司公告' }}；官方來源入口仍可查，未推論沒有公告。</p></section>{% endif %}
   <section class="panel research-list"><div class="section-heading"><div><p class="eyebrow">OFFICIAL ANNOUNCEMENTS</p><h2>最近公司公告</h2></div></div>
-    {% for event in announcements %}<article class="event-research-card"><div><p class="eyebrow">{{ event.event_type }} · {{ event.category }}{% if event.correction_notice %} · 更正公告{% endif %}</p><h2>{{ event.name }} · {{ event.symbol }}</h2><p>{{ event.title }}</p></div><dl><div><dt>公告時間</dt><dd>{{ event.published_at|research_time }}</dd></div><div><dt>生效日期</dt><dd>{{ event.effective_at|research_time }}</dd></div><div><dt>狀態</dt><dd>{{ event.status|research_label }}</dd></div></dl><p>{{ event.summary }}</p>{% include "event_correction.html" %}<a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">{{ event.source_publisher or '官方來源' }}</a><details><summary>來源定位與核對</summary><p class="muted small">{{ event.source_locator }} · 核對 {{ event.source_checked_at|research_time }}</p></details></article>{% else %}<p class="empty-state">{% if event_status in ['not_covered','unavailable','source_error','stale'] %}尚無可在此窗口呈現的公司公告，請參考上方資料狀態。{% else %}目前收錄範圍內沒有符合篩選的公告；不代表完整市場沒有公告。{% endif %}</p>{% endfor %}
+    {% for event in announcements %}<article class="event-research-card"><div><p class="eyebrow">{{ event.event_type }} · {{ event.category }}{% if event.correction_notice %} · 更正公告{% endif %}</p><h2>{{ event.name }} · {{ event.symbol }}</h2><p>{{ event.title }}</p></div><dl><div><dt>公告時間</dt><dd>{{ event.published_at|research_time }}</dd></div><div><dt>生效日期</dt><dd>{{ event.effective_at|research_time }}</dd></div><div><dt>狀態</dt><dd>{{ event.status|research_label }}</dd></div></dl>{% if event.summary and event.summary != event.title %}<details><summary>查看公告內容</summary><p>{{ event.summary }}</p></details>{% endif %}{% include "event_correction.html" %}<a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">{{ event.source_publisher or '官方來源' }}</a><details><summary>來源定位與核對</summary><p class="muted small">{{ event.source_locator }} · 核對 {{ event.source_checked_at|research_time }}</p></details></article>{% else %}<p class="empty-state">{% if event_status in ['not_covered','unavailable','source_error','stale'] %}尚無可在此窗口呈現的公司公告，請參考上方資料狀態。{% else %}目前收錄範圍內沒有符合篩選的公告；不代表完整市場沒有公告。{% endif %}</p>{% endfor %}
   </section>
   {% if previous_url or next_url %}<nav class="activity-actions" aria-label="公告分頁">{% if previous_url %}<a class="button button-secondary" href="{{ previous_url }}">上一頁</a>{% endif %}{% if next_url %}<a class="button button-secondary" href="{{ next_url }}">下一頁</a>{% endif %}</nav>{% endif %}
   <section class="panel research-list"><div class="section-heading"><div><p class="eyebrow">UPCOMING · 14 DAYS</p><h2>接下來已公布事件</h2></div></div>
-    {% for event in upcoming_events or [] %}<article class="event-research-card"><div><p class="eyebrow">{{ event.event_type }} · {{ event.category }}{% if event.correction_notice %} · 更正公告{% endif %}</p><h2>{{ event.name }} · {{ event.symbol }}</h2><p>{{ event.title }}</p></div><p>生效 {{ event.effective_at|research_time }} · {{ event.status|research_label }}</p><p>{{ event.summary }}</p><a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">官方來源</a></article>{% else %}<p class="empty-state">目前收錄資料中尚無未來 14 日具有明確生效日期的事件；未提供日期的公告仍列於上方。</p>{% endfor %}
+    {% for event in upcoming_events or [] %}<article class="event-research-card"><div><p class="eyebrow">{{ event.event_type }} · {{ event.category }}{% if event.correction_notice %} · 更正公告{% endif %}</p><h2>{{ event.name }} · {{ event.symbol }}</h2><p>{{ event.title }}</p></div><p>生效 {{ event.effective_at|research_time }} · {{ event.status|research_label }}</p>{% if event.summary and event.summary != event.title %}<details><summary>查看公告內容</summary><p>{{ event.summary }}</p></details>{% endif %}<a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">官方來源</a></article>{% else %}<p class="empty-state">目前收錄資料中尚無未來 14 日具有明確生效日期的事件；未提供日期的公告仍列於上方。</p>{% endfor %}
   </section>
   {% if past_events %}<section class="panel research-list"><div class="section-heading"><h2>最近已生效事件</h2></div>{% for event in past_events %}<article class="event-research-card"><h2>{{ event.name }} · {{ event.symbol }}</h2><p>{{ event.title }}</p><p>生效 {{ event.effective_at|research_time }}</p><a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">官方來源</a></article>{% endfor %}</section>{% endif %}
   {% if source_links %}<section class="panel research-list"><div class="section-heading"><h2>官方資料入口</h2></div><p class="muted small">以下是來源入口，不計入公司公告或事件數量。</p>{% for event in source_links %}<article><strong>{{ event.name }}</strong><a class="source-link" href="{{ event.source }}" target="_blank" rel="noopener noreferrer">{{ event.source_title or '查看官方來源' }}</a></article>{% endfor %}</section>{% endif %}
 </div>
 {% endblock %}
diff --git a/templates/industry_relationships.html b/templates/industry_relationships.html
index 98c71ca..a718439 100644
--- a/templates/industry_relationships.html
+++ b/templates/industry_relationships.html
@@ -1,35 +1,35 @@
 {% extends "base.html" %}
 {% block title %}產業關係圖｜ABSORB{% endblock %}
 {% block content %}
 <div class="page research-page">
   <header class="page-header"><div><p class="eyebrow">RELATIONSHIP EVIDENCE</p><h1>{{ catalog.topic or '產業關係圖' }}</h1><p class="page-intro">每條關係都附來源。題材相同只代表研究分類，不代表供應或合作。{% if focus %}目前研究中心：{{ focus }}{% endif %}</p></div><a class="button button-secondary" href="{{ url_for('industries_page') }}">回到產業觀察</a></header>
   {% if catalog.coverage_note %}<div class="error-banner" role="note">{{ catalog.coverage_note }}</div>{% endif %}
   <section class="panel relationship-layout" aria-label="產業關係與證據">
     <div class="relationship-graph-wrap" aria-label="產業關係圖">
       <svg class="relationship-graph" viewBox="0 0 1120 440" role="img" aria-labelledby="relationship-graph-title relationship-graph-desc">
         <title id="relationship-graph-title">{{ catalog.topic or '產業關係圖' }}</title>
         <desc id="relationship-graph-desc">關係線只代表資料中已審核的來源；同一環節分類以虛線表示。</desc>
         <defs><marker id="relationship-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z"></path></marker></defs>
         {% for edge in catalog.graph_edges or [] %}<line x1="{{ edge.x1 }}" y1="{{ edge.y1 }}" x2="{{ edge.x2 }}" y2="{{ edge.y2 }}" class="relationship-edge{% if edge.type in ('同一環節／題材', 'competition', 'same_segment') %} is-dashed{% endif %}"{% if edge.type in ('供應關係', 'supply') %} marker-end="url(#relationship-arrow)"{% endif %}></line>{% endfor %}
         {% for node in catalog.graph_nodes or [] %}<g class="relationship-node" transform="translate({{ node.x - 92 }},{{ node.y - 28 }})"><rect width="184" height="56" rx="12"></rect><text x="92" y="24" text-anchor="middle">{{ node.name }}</text><text x="92" y="43" text-anchor="middle" class="relationship-symbol">{{ node.symbol }}</text></g>{% endfor %}
       </svg>
       <p class="muted small">圖形提供位置概覽；手機與鍵盤使用者可用下方清單閱讀同一批資料。</p>
     </div>
     <div class="relationship-stages">
       {% for stage in catalog.stages or [] %}<div class="relationship-stage"><h2>{{ stage.name }}</h2>{% for node in stage.nodes or [] %}<a href="{{ url_for('industry_relationships_page', focus=node.symbol) if node.symbol else '#' }}"><strong>{{ node.name }}</strong>{% if node.symbol %}<small>{{ node.symbol }} · 設為研究中心</small>{% endif %}</a>{% endfor %}</div>{% endfor %}
     </div>
     <div class="relationship-feed">
       <div class="relationship-list">
         <div class="section-heading"><div><p class="eyebrow">REVIEWED EDGES</p><h2>已確認關係</h2></div><span class="muted small">{{ relationships|length }} 條紀錄</span></div>
-        {% for item in relationships %}<article class="relationship-card"><div class="relationship-card-head"><strong>{{ item['from']['name'] }} → {{ item['to']['name'] }}</strong><span>{{ item.type }}</span></div><p>{{ item.product_scope }}</p><small>審核日 {{ item.reviewed_at or '未提供' }}{% if item.status %} · {{ item.status }}{% endif %}</small><details><summary>查看證據與操作</summary><p>{{ item.description or '未提供額外描述。' }}</p>{% if item.source %}<dl><div><dt>來源</dt><dd>{{ item.source.title or '未提供標題' }} · {{ item.source.publisher or '未提供發布者' }}</dd></div><div><dt>發布</dt><dd>{{ item.source.published_at or '未提供' }}</dd></div><div><dt>定位</dt><dd>{{ item.source.locator or '未提供' }}</dd></div></dl>{% endif %}</details><div class="relationship-actions"><a class="source-link" href="{{ url_for('stock_page', code=item['from']['symbol']) }}">查看 {{ item['from']['symbol'] }}</a><a class="source-link" href="{{ url_for('stock_compare_page') }}?symbols={{ item['from']['symbol'] }},{{ item['to']['symbol'] }}">加入比較</a>{% if item.source and item.source.url %}<a class="source-link" href="{{ item.source.url }}" target="_blank" rel="noopener noreferrer">原始來源</a>{% endif %}</div></article>{% else %}<p class="empty-state">目前沒有通過審核的關係資料。</p>{% endfor %}
+        {% for item in relationships %}<article class="relationship-card"><div class="relationship-card-head"><strong>{{ item['from']['name'] }} → {{ item['to']['name'] }}</strong><span>{{ item.type }}</span></div><p>{{ item.product_scope }}</p><small>審核日 {{ item.reviewed_at or '未提供' }}{% if item.status %} · {{ item.status|research_label }}{% endif %}</small><details><summary>查看證據與操作</summary><p>{{ item.description or '未提供額外描述。' }}</p>{% if item.source %}<dl><div><dt>來源</dt><dd>{{ item.source.title or '未提供標題' }} · {{ item.source.publisher or '未提供發布者' }}</dd></div><div><dt>發布</dt><dd>{{ item.source.published_at or '未提供' }}</dd></div><div><dt>定位</dt><dd>{{ item.source.locator or '未提供' }}</dd></div></dl>{% endif %}</details><div class="relationship-actions">{% if supported_symbol(item['from']['symbol']) %}<a class="source-link" href="{{ url_for('stock_page', code=item['from']['symbol']) }}">查看 {{ item['from']['symbol'] }}</a>{% else %}<span class="muted small">{{ item['from']['symbol'] }} 尚未提供個股觀察</span>{% endif %}{% if supported_symbol(item['from']['symbol']) and supported_symbol(item['to']['symbol']) %}<a class="source-link" href="{{ url_for('stock_compare_page') }}?symbols={{ item['from']['symbol'] }},{{ item['to']['symbol'] }}">加入比較</a>{% endif %}{% if item.source and item.source.url %}<a class="source-link" href="{{ item.source.url }}" target="_blank" rel="noopener noreferrer">原始來源</a>{% endif %}</div></article>{% else %}<p class="empty-state">目前沒有通過審核的關係資料。</p>{% endfor %}
       </div>
       {% if research_leads %}
       <div class="relationship-list research-lead-list" aria-label="研究線索">
         <div class="section-heading"><div><p class="eyebrow">RESEARCH LEADS</p><h2>研究線索</h2></div><span class="muted small">不列入已確認關係</span></div>
         {% for lead in research_leads %}<article class="relationship-card"><div class="relationship-card-head"><strong>{{ lead.title or lead.symbol }}</strong><span>{{ lead.status or 'pending' }}</span></div><p>{{ lead.summary or '公開說法仍待官方或文件來源確認。' }}</p><small>{{ lead.market or '' }} {{ lead.symbol or '' }}</small>{% if lead.source_url %}<a class="source-link" href="{{ lead.source_url }}" target="_blank" rel="noopener noreferrer">研究線索來源</a>{% endif %}</article>{% endfor %}
       </div>
       {% endif %}
     </div>
   </section>
 </div>
 {% endblock %}
diff --git a/templates/observation_freshness.html b/templates/observation_freshness.html
new file mode 100644
index 0000000..7476d57
--- /dev/null
+++ b/templates/observation_freshness.html
@@ -0,0 +1,6 @@
+{% set freshness = observation_freshness|default({}, true) %}
+<section class="freshness-status" data-freshness-status="{{ freshness.get('status', 'unavailable') }}" aria-label="觀察資料狀態">
+  <div><h2>資料狀態</h2><p>{{ {'current':'資料最新','updating':'更新中','stale':'資料過期','unavailable':'暫時無法核對新鮮度'}.get(freshness.get('status'), '暫時無法核對新鮮度') }}</p></div>
+  <p>資料日 {{ freshness.get('source_market_date') or '尚無已驗證日期' }}</p>
+  {% if freshness.get('status') in ['stale','updating','unavailable'] %}<p class="freshness-warning">以下為最近一次已驗證觀察，不代表今日即時行情。{{ '新交易日資料尚待發布。' if freshness.get('status') == 'updating' else '最新交易日是否已涵蓋，請以資料日期為準。' }}</p>{% endif %}
+</section>
diff --git a/templates/perspectives.html b/templates/perspectives.html
index 462c975..68e16b7 100644
--- a/templates/perspectives.html
+++ b/templates/perspectives.html
@@ -1,35 +1,36 @@
 {% extends "base.html" %}
 {% block title %}觀點與揭露｜ABSORB{% endblock %}
 {% block content %}
 <div class="page research-page">
   <header class="page-header"><div><p class="eyebrow">PERSPECTIVES & DISCLOSURES</p><h1>觀點與揭露</h1><p class="page-intro">分開閱讀公開觀點、交易揭露與機構持倉。交易日、公開日與核對日各有意義，以下只列截止前已核對的內容。</p></div></header>
   <section class="panel activity-card" aria-label="資料更新狀態">
     <div class="section-heading"><h2>資料更新狀態</h2></div>
     {% if reviewed_refresh_status == 'source_error' %}<p class="error-banner" role="status">審核版本更新暫時失敗，目前保留上次成功取得的已核對內容及原發布時間。</p>{% elif reviewed_refresh_status == 'deployment_snapshot' %}<p class="muted small">目前使用隨網站版本部署的已核對資料；尚未取得獨立審核發布版本。</p>{% endif %}
     <dl><div><dt>最近核對時間</dt><dd>{{ reviewed_at|research_time }}（台北時間）</dd></div><div><dt>最近候選抓取</dt><dd>{{ fetched_at|research_time }}</dd></div><div><dt>資料發布時間</dt><dd>{{ published_at|research_time }}</dd></div></dl>
     <p class="muted small">{{ pending_count }} 筆候選待審；{{ unreviewed_count }} 筆舊紀錄或未核對紀錄未列入清單。各來源涵蓋範圍見下方卡片；更新時間不代表涵蓋完整。</p>
+    {% if pending_count %}<p class="muted small" role="note">候選抓取時間只代表取得待審資料；以下公開清單仍以最近核對時間為準，完成審核與發布後才會新增內容。</p>{% endif %}
     {% if catalog_status == 'unavailable' %}<p class="error-banner" role="status">資料暫時無法驗證（unavailable），請稍後再試。</p>{% elif catalog_status == 'empty' %}<p class="empty-state">目前尚未建立可核對的公開紀錄。</p>{% endif %}
   </section>
   <nav class="activity-tabs" aria-label="動態類型">
     {% for name, label in [('latest','最新動態'),('trades','交易揭露'),('holdings','機構持倉'),('opinions','公開觀點')] %}<a class="{{ 'active' if activity_tab == name else '' }}" href="{{ tab_urls[name] }}"{% if activity_tab == name %} aria-current="page"{% endif %}>{{ label }}</a>{% endfor %}
   </nav>
   <section class="panel event-filter-panel">
     <form method="get" class="research-filters perspective-toolbar">
       <input type="hidden" name="tab" value="{{ activity_tab }}"><input type="hidden" name="cutoff_at" value="{{ query.cutoff_at }}"><input type="hidden" name="view" value="{{ query.view }}">
       <label>人物或機構<select name="subject_id"><option value="">全部對象</option>{% for subject in subjects %}<option value="{{ subject.subject_id }}"{% if subject_filter == subject.subject_id %} selected{% endif %}>{{ subject.subject_name }}</option>{% endfor %}</select></label>
       <label>市場<select name="market"><option value=""{% if not query.market %} selected{% endif %}>全部市場</option><option value="TW"{% if query.market == 'TW' %} selected{% endif %}>台股</option><option value="US"{% if query.market == 'US' %} selected{% endif %}>美股</option></select></label>
       <label>證券代碼<input name="symbol" value="{{ query.symbol or '' }}" placeholder="例如 2330 / INTC" maxlength="20"></label>
       <label>發布者<select name="creator_id"><option value="">全部發布者</option>{% for creator in creators if creator.id %}<option value="{{ creator.id }}"{% if query.creator_id == creator.id %} selected{% endif %}>{{ creator.name }}</option>{% endfor %}</select></label>
       <label>公開時間<select name="activity_window">{% for value, label in [('all','全部時間'),('7','近 7 日'),('28','近 28 日'),('90','近 90 日')] %}<option value="{{ value }}"{% if activity_window|string == value %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></label>
       {% if query.symbol %}<label>共識觀察窗口<select name="window">{% for value in [1,7,28] %}<option value="{{ value }}"{% if query.window == value %} selected{% endif %}>{{ value }} 日</option>{% endfor %}</select></label>{% endif %}
       {% if query.stance %}<input type="hidden" name="stance" value="{{ query.stance }}">{% endif %}{% if query.content_type %}<input type="hidden" name="content_type" value="{{ query.content_type }}">{% endif %}
       <button class="button button-secondary" type="submit">套用篩選</button><a class="button button-secondary" href="{{ url_for('perspectives_page') }}">清除篩選</a>
     </form>
     <p class="muted small">觀點 {{ opinions_total }} 筆 · 動態 {{ activities_total }} 筆 · 第 {{ activity_page }}／{{ activity_pages }} 頁。截止 {{ query.cutoff_at|research_time }}（台北時間）</p>
     {% if query.query_string %}<details><summary>查詢條件</summary><p class="muted small">{{ query.query_string }}</p></details>{% endif %}
   </section>
   {% if activity_tab != 'opinions' %}
   <section class="panel activity-list" aria-label="已核對動態"><div class="section-heading"><h2>{{ '機構季底持倉' if activity_tab == 'holdings' else '已核對揭露與動態' }}</h2></div>
     {% for item in activities %}<article class="activity-card" data-activity-id="{{ item.activity_id }}">
       <div><p class="eyebrow">{{ item.type_label }} · {{ item.subject_name }}</p><h2>{{ item.market }} · {{ item.symbol }} · {{ item.action|research_label }}</h2><p>{{ item.summary }}</p></div>
       <dl><div><dt>對象</dt><dd>{{ item.subject_name }}（{{ item.owner|research_label }}）</dd></div><div><dt>證券類型</dt><dd>{{ item.instrument_type|research_label }}</dd></div><div><dt>交易／基準日</dt><dd>{{ item.transaction_label }}{% if item.holdings_label %}／季底 {{ item.holdings_label }}{% endif %}</dd></div><div><dt>揭露日</dt><dd>{{ item.public_label|research_time }}</dd></div><div><dt>最近核對</dt><dd>{{ item.reviewed_label|research_time }}</dd></div>{% if item.amount_min is not none or item.amount_max is not none %}<div><dt>金額區間</dt><dd>{{ item.amount_min if item.amount_min is not none else '未揭露' }}–{{ item.amount_max if item.amount_max is not none else '未揭露' }} {{ item.currency }}</dd></div>{% endif %}</dl>
diff --git a/templates/reports.html b/templates/reports.html
index 5d27cc2..b9db8a3 100644
--- a/templates/reports.html
+++ b/templates/reports.html
@@ -10,94 +10,102 @@
 <div class="page reports-page">
   <header class="page-header">
     <div>
       <p class="eyebrow">VERIFIED MARKET OBSERVATIONS</p>
       <h1>每日報告</h1>
       <p class="page-intro">已完成內容雜湊與發布鏈驗證的{{ market_label }}市場觀察日報。</p>
       <p class="muted small">AI 預測研究中；正式報告只呈現已發生的市場資料。</p>
     </div>
   </header>
 
   <section class="panel" aria-labelledby="report-history-title">
     <div class="report-history-head">
       <div>
         <p class="eyebrow">{{ 'US MARKET' if is_us else 'TW INDUSTRY' }}</p>
         <h2 id="report-history-title">歷史報告</h2>
         <p>盤前與盤後分流排列，依發布時間由新到舊閱讀。</p>
       </div>
       {% if reports_v2 %}
       <div class="report-filters" data-report-filters role="group" aria-label="篩選報告類型">
         <button class="active" type="button" data-report-filter="all" aria-pressed="true">全部</button>
         <button type="button" data-report-filter="pre_market" aria-pressed="false">盤前</button>
         <button type="button" data-report-filter="post_close" aria-pressed="false">盤後</button>
       </div>
       {% endif %}
     </div>
+    <form method="get" class="report-date-filter" aria-label="依報告日期篩選">
+      <label for="report-date">報告日期（盤前適用日／盤後資料日）</label>
+      <input id="report-date" type="date" name="date" value="{{ selected_date|default('') }}">
+      <button class="button button-secondary" type="submit">篩選日期</button>
+      {% if selected_date %}<a class="button button-secondary" href="{{ url_for('us_reports_page' if is_us else 'reports_page') }}">清除日期</a>{% endif %}
+    </form>
     {% if reports_v2 %}
       <div class="report-lanes" data-report-lanes>
         {% for report_type, lane_title, lane_description in [('pre_market', '盤前風險更新', '開盤前確認隔夜訊號與資料限制'), ('post_close', '盤後市場觀察', '收盤後整理市場、產業與異常事件')] %}
         {% set lane_reports = reports_v2|selectattr('report_type', 'equalto', report_type)|list %}
         <section class="report-lane" data-report-type="{{ report_type }}" aria-labelledby="report-lane-{{ report_type }}">
           <header class="report-lane-header">
             <div><h3 id="report-lane-{{ report_type }}">{{ lane_title }}</h3><p>{{ lane_description }}</p></div>
             <span>{{ lane_reports|length }} 份</span>
           </header>
           <div class="report-lane-list">
             {% for report in lane_reports %}
+            {% if loop.index == 4 %}<details class="report-history-older"><summary>查看較早報告（{{ lane_reports|length - 3 }} 份）</summary>{% endif %}
             <article class="report-card report-card-{{ report_type }}">
               <div>
                 <p class="report-date">{{ report.applicable_trading_date if report_type == 'pre_market' else report.source_market_date }}</p>
                 <h3>{{ report.title }}</h3>
                 <p class="report-summary">{{ report.summary|join('；') }}</p>
                 <p class="muted small">資料基準日 {{ report.source_market_date }}｜適用交易日 {{ report.applicable_trading_date }}</p>
                 {% if report.duplicate_notice %}<p class="muted small" role="note">{{ report.duplicate_notice }}</p>{% endif %}
               </div>
               <div class="report-actions">
                 {% if report.index_conflict %}
                   <p class="empty-state" role="alert">此報告索引存在內容衝突，暫不提供閱讀連結；雜湊見上方說明。</p>
                 {% elif report_type == 'post_close' %}
                   <a class="button button-secondary" href="{{ url_for(post_close_endpoint, trading_date=report.source_market_date) }}">閱讀盤後觀察</a>
                 {% else %}
                   <a class="button button-secondary" href="{{ url_for(pre_market_endpoint, trading_date=report.applicable_trading_date) }}">閱讀盤前更新</a>
                 {% endif %}
               </div>
             </article>
+            {% if loop.last and lane_reports|length > 3 %}</details>{% endif %}
             {% else %}
             <div class="empty-state" role="status"><p>目前沒有已通過發布驗證的{{ lane_title }}。</p></div>
             {% endfor %}
           </div>
         </section>
         {% endfor %}
       </div>
     {% endif %}
     {% if reports %}
       <div class="report-list">
         {% for report in reports %}
           <article class="report-card">
             <div>
               <p class="eyebrow">報告交易日</p>
               <h3>{{ report.report_date }}</h3>
               <p class="action-label">{{ report.get('market_action', '舊版報告') }}</p>
               <p class="report-headline">{{ report.get('headline', '此報告採舊版格式，未包含新版卡片摘要；不是等待人工確認，請進入完整報告查看。') }}</p>
               <dl class="report-meta">
                 <div><dt>資料截止日</dt><dd>{{ report.data_as_of }}</dd></div>
                 <div><dt>資料覆蓋率</dt><dd>{{ '%.1f%%'|format(report.coverage * 100) if report.coverage is not none else '資料不足' }}</dd></div>
                 <div><dt>重點產業</dt><dd>{{ report.get('key_industries', [])|join('、') or '舊版未提供' }}</dd></div>
               </dl>
               <details class="report-technical"><summary>技術資訊</summary><p>模型版本：{{ report.model_versions.keys()|join('、') }}｜內部存檔 {{ report.page_count }} 頁｜產生時間 {{ report.generated_at }}</p></details>
             </div>
             <div class="report-actions" aria-label="{{ report.report_date }} 報告操作">
               <a class="button" href="{{ url_for('report_page', report_date=report.report_date) }}">閱讀完整報告</a>
             </div>
           </article>
         {% endfor %}
       </div>
     {% endif %}
     {% if not reports_v2 and not reports %}
       <div class="empty-state" role="status">
-        <h3>目前沒有可用的每日報告</h3>
-        <p>{% if unavailable %}報告服務暫時無法讀取，請稍後再試。{% else %}目前尚無已完成發布驗證的報告。{% endif %}</p>
+        <h3>{{ '目前沒有符合此日期的報告' if selected_date else '目前沒有可用的每日報告' }}</h3>
+        <p>{% if unavailable %}報告服務暫時無法讀取，請稍後再試。{% elif selected_date %}此日期尚無已完成發布驗證的報告，可清除日期查看其他報告。{% else %}目前尚無已完成發布驗證的報告。{% endif %}</p>
       </div>
     {% endif %}
   </section>
 </div>
 {% endblock %}
diff --git a/templates/reports/post_close_professional.html b/templates/reports/post_close_professional.html
index f9ffdbc..e06a336 100644
--- a/templates/reports/post_close_professional.html
+++ b/templates/reports/post_close_professional.html
@@ -125,56 +125,56 @@
           {% for item in exec_summary.opposing_evidence %}
             <li>{{ item }}</li>
           {% else %}
             <li class="muted">目前沒有足夠資料形成明確反向證據</li>
           {% endfor %}
         </ul>
       </div>
     </div>
 
     <!-- Largest Risk Callout -->
     <div class="callout-box warning-callout">
       <div class="callout-icon">⚠️</div>
       <div class="callout-content">
         <strong>主要風險警示：</strong>
         <span>{{ exec_summary.largest_risk or '市場風險狀態隨總體波動調整。' }}</span>
       </div>
     </div>
 
     <!-- Key Events -->
     <div class="subsection">
       <h3 class="subsection-title">今日市場重要事件與異常摘要</h3>
       <div class="event-card-list">
         {% for event in report.key_events %}
           <div class="event-item severity-{{ event.severity or 'medium' }}">
             <div class="event-meta">
-              <span class="badge event-category-badge">{{ '正面' if event.category == 'positive' else '風險' }}</span>
-              <span class="badge severity-badge">{{ event.severity|upper }}</span>
+              <span class="badge event-category-badge">{{ {'positive':'正面','risk':'風險','negative':'風險'}.get(event.category, '觀察') }}</span>
+              {% if event.severity %}<span class="badge severity-badge">{{ {'high':'極端','medium':'顯著','low':'注意'}.get(event.severity, event.severity) }}</span>{% endif %}
               {% if event.symbol %}<span class="event-symbol">{{ event.name or event.symbol }}（{{ event.symbol }}）</span>{% endif %}
             </div>
             <strong class="event-headline">{{ event.headline }}</strong>
-            <p class="event-desc">{{ event.description }}</p>
+            {% if event.description and event.description != event.headline %}<p class="event-desc">{{ event.description }}</p>{% endif %}
           </div>
         {% else %}
           <div class="empty-state">目前沒有已通過條件的重大異常事件。</div>
         {% endfor %}
       </div>
     </div>
   </section>
 
   <!-- Section 2: Market & Risk -->
   <section class="panel report-section" id="market-analysis">
     <div class="section-heading">
       <div>
         <p class="eyebrow">SECTION 02 ｜ MARKET AND RISK</p>
         <h2>市場總體與風險</h2>
       </div>
       <span class="muted small">資料基準日 {{ ident.source_market_date or report.source_market_date or '—' }}</span>
     </div>
 
     {% if market_sec.status == 'available' %}
       {% set market = market_sec.data %}
       <div class="report-kpi-grid">
         <div class="kpi-card">
           <span class="kpi-label">全市場單日中位報酬</span>
           <strong class="kpi-value {{ 'positive' if market.return_1d_pct and market.return_1d_pct >= 0 else 'negative' }}">
             {{ '%+.2f%%'|format(market.return_1d_pct) if market.return_1d_pct is not none else '資料不足' }}
@@ -698,40 +698,41 @@
       資料治理原則：統計關聯不等於因果關係，歷史資料與模型研究結果不保證未來交易獲利。所有發布產物具備嚴格內容雜湊簽署，杜絕事後竄改或未來資訊洩漏 (Lookahead-Free)。
     </p>
   </section>
 
   <!-- Section 10: AI Reference & Legal Disclosure -->
   <section class="panel report-section risk-panel" id="ai-reference">
     <div class="section-heading">
       <div>
         <p class="eyebrow">SECTION 10 ｜ AI REFERENCE</p>
         <h2>AI 模型參考建議與監管免責聲明</h2>
       </div>
     </div>
 
     {% if ai_sec.status == 'available' %}
       <div class="ai-conclusion-box">
         <p class="ai-text">{{ ai_sec.data.conclusion }}</p>
       </div>
     {% else %}
       <div class="empty-state">{{ ai_sec.reason or 'AI 參考建議尚未提供。' }}</div>
     {% endif %}
 
     <div class="legal-disclaimer">
       <p>
         <strong>免責聲明：</strong>
         {% if market_code == 'US' %}
-          {% set report_sources = '美國公開市場資料、已驗證產業架構及量化回歸研究模型' %}
+          {% set report_sources = '美國公開市場資料、已驗證產業架構' %}
         {% else %}
-          {% set report_sources = '台灣證券交易所 (TWSE)、證券櫃檯買賣中心 (TPEx) 公開市場資料、已驗證產業架構及量化回歸研究模型' %}
+          {% set report_sources = '台灣證券交易所 (TWSE)、證券櫃檯買賣中心 (TPEx) 公開市場資料、已驗證產業架構' %}
         {% endif %}
+        {% if quant_sec.status == 'available' %}{% set report_sources = report_sources ~ '及量化回歸研究模型' %}{% endif %}
         {% if ai_sec.status == 'available' %}
           本報告內容由 Google Gemini 根據 ABSORB 可取得之{{ report_sources }}分析生成。
         {% else %}
           本報告由 ABSORB 規則式研究框架根據可取得之{{ report_sources }}生成；{{ ai_sec.reason or 'Gemini 參考解讀尚未產生' }}。
         {% endif %}
         本報告僅供學術量化研究與市場觀察參考，不構成任何證券、金融商品之買賣推薦、要約或投資顧問服務。投資人應獨立評估投資風險，並就投資決策自行承擔盈虧責任。
       </p>
     </div>
   </section>
 </article>
 {% endblock %}
diff --git a/templates/stock_compare.html b/templates/stock_compare.html
index a9c68dc..cd3467d 100644
--- a/templates/stock_compare.html
+++ b/templates/stock_compare.html
@@ -1,18 +1,18 @@
 {% extends "base.html" %}
 {% block title %}同業比較｜ABSORB{% endblock %}
 {% block content %}
 <div class="page research-page">
-  <header class="page-header"><div><p class="eyebrow">COMPANY COMPARISON</p><h1>公司比較</h1><p class="page-intro">比較同一資料日的已驗證市場觀察；缺少欄位會保留為資料不足。</p></div><a class="button button-secondary" href="{{ url_for('industry_relationships_page') }}">回到產業關係</a></header>
+  <header class="page-header"><div><p class="eyebrow">COMPANY COMPARISON</p><h1>公司比較</h1><p class="page-intro">依各標的資料日比較已驗證觀察；資料日不同時，報酬期間也不同，不能視為同日比較。缺少欄位會保留為資料不足。</p></div><a class="button button-secondary" href="{{ url_for('industry_relationships_page') }}">回到產業關係</a></header>
   <section class="panel comparison-table-wrap"><table class="comparison-table"><thead><tr><th>指標</th>{% for row in rows %}<th><a href="{{ url_for('stock_page', code=row.code) }}">{{ row.name }}<small>{{ row.code }}</small></a></th>{% endfor %}</tr></thead><tbody>
     <tr><th>資料日</th>{% for row in rows %}<td>{{ row.get('as_of') or '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>最新收盤</th>{% for row in rows %}<td>{{ '%.2f'|format(row.get('price')) if row.get('price') is not none else '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>近 5 日價格變動</th>{% for row in rows %}<td>{{ '%+.2f%%'|format(row.get('return_5d_pct')) if row.get('return_5d_pct') is not none else '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>近 20 日價格變動</th>{% for row in rows %}<td>{{ '%+.2f%%'|format(row.get('return_20d_pct')) if row.get('return_20d_pct') is not none else '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>均線狀態</th>{% for row in rows %}<td>{{ {'above_ma20_ma60':'站上 MA20 與 MA60','above_ma20':'站上 MA20','below_ma60':'低於 MA60','mixed':'均線交錯'}.get(row.get('trend_observation'), '資料不足') }}</td>{% endfor %}</tr>
     <tr><th>量比</th>{% for row in rows %}<td>{{ '%.2f'|format(row.get('volume_ratio')) if row.get('volume_ratio') is not none else '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>近 5 日外資</th>{% for row in rows %}<td>{{ '%.0f'|format(row.get('foreign_net_5')) if row.get('foreign_net_5') is not none else '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>資料品質</th>{% for row in rows %}<td>{{ row.get('data_quality') or ('已驗證觀察' if row.get('as_of') else '資料不足') }}</td>{% endfor %}</tr>
     <tr><th>產業關係</th>{% for row in rows %}<td><a href="{{ url_for('industry_relationships_page', focus=row.code) }}">查看已核對關係</a></td>{% endfor %}</tr>
   </tbody></table></section>
 </div>
 {% endblock %}
diff --git a/templates/stock_detail.html b/templates/stock_detail.html
index 2d78e44..bda20fc 100644
--- a/templates/stock_detail.html
+++ b/templates/stock_detail.html
@@ -1,88 +1,90 @@
 {% extends "base.html" %}
 {% set market = d.get("market", "TW") %}
 {% set prediction_status = d.get("prediction_status", "AI 預測研究中") %}
 {% set as_of = d.get("as_of", "資料日期待確認") %}
 {% set quant_source = d.get("quant_source", "已發布市場資料") %}
 {% set trend_observation = d.get("trend_observation") %}
 {% set ma20 = d.get("ma20") %}
 {% set ma60 = d.get("ma60") %}
 {% set volume_ratio = d.get("volume_ratio") %}
 {% set foreign_net_5 = d.get("foreign_net_5") %}
 {% set foreign_net_20 = d.get("foreign_net_20") %}
 {% set institution_net_ratio_pct = d.get("institution_net_ratio_pct") %}
 {% set rsi = d.get("rsi") %}
 {% set macd_osc = d.get("macd_osc") %}
 {% set k_value = d.get("k") %}
 {% set d_value = d.get("d") %}
 {% set risk_events = d.get("risk_events", []) %}
 {% set candles = d.get("candles", []) %}
 {% set ma20_line = d.get("ma20_line", []) %}
 {% set prediction = d.get("prediction") %}
 {% set observation_kind = d.get("observation_kind", "regular_price") %}
 {% block title %}{% if d.name and d.name|upper != d.code|upper %}{{ d.name }}（{{ d.code }}）{% else %}{{ d.code }}{% endif %}觀察｜ABSORB{% endblock %}
 {% block head %}{% if observation_kind == "regular_price" %}<script src="https://unpkg.com/lightweight-charts@4.2.2/dist/lightweight-charts.standalone.production.js" integrity="sha384-qQnpH1Chlwm0r93GZ6NgZoEehIelWkhwbBtJMWh0P5wPqySGEt8UjETGKMF0GUdn" crossorigin="anonymous"></script>{% endif %}{% endblock %}
 {% block content %}
+{% set quote_label = '最近可用收盤' if (observation_freshness|default({}, true)).get('status') in ['stale', 'updating'] else '最新收盤' %}
 <div class="page stock-page" data-stock-code="{{ d.code }}" data-stock-name="{{ d.name }}"{% if observation_kind == "regular_price" %} data-stock-price="{{ '%.2f'|format(d.price) }}"{% endif %}>
+  {% include "observation_freshness.html" %}
   {% if observation_kind != "regular_price" %}
   <header class="stock-hero" id="status-summary">
     <div class="hero-copy">
       <a class="back-link" href="{{ url_for('us_dashboard_page' if market == 'US' else 'dashboard_page') }}">返回市場觀察</a>
       <p class="eyebrow">{{ market }} · {{ d.code }}</p>
       <h1>{{ d.name }}</h1>
       <p class="decision-headline">{{ d.status_label }}</p>
       <p class="muted">官方狀態驗證日 {{ d.observation_as_of }}。本頁不以既有價格代表該日交易結果。</p>
       {% if d.get("last_regular_close") is not none %}<p class="muted">最後正常交易收盤 {{ '{:,.2f}'.format(d.last_regular_close) }}（{{ d.latest_regular_price_date }}）</p>{% endif %}
       <p class="muted small">證據雜湊 {{ d.evidence_sha256[:12] }}｜{{ quant_source }}</p>
       <button class="button button-secondary watchlist-toggle" type="button" data-watchlist-toggle data-code="{{ d.code }}" data-name="{{ d.name }}" aria-pressed="false">加入關注</button>
     </div>
   </header>
   {% else %}
   <div class="error-banner" role="status">{% if prediction %}{{ prediction.label }}已標示於 K 線{% if prediction.validation_mode == 'research' %}，未經回測校準{% endif %}；提供機率與價格估計，不產生買賣指令。{% else %}AI 五日預測尚未發布；沒有可用產物時不補入示意數字。{% endif %}</div>
 
   <header class="stock-hero" id="summary">
     <div class="hero-copy">
       <a class="back-link" href="{{ url_for('us_dashboard_page' if market == 'US' else 'dashboard_page') }}">返回市場觀察</a>
       <p class="eyebrow">{{ market }} · {{ d.code }}</p>
       <h1>{{ d.name }}</h1>
       <p class="decision-headline">個股觀察摘要</p>
-      <p class="muted">最新收盤 {{ '{:,.2f}'.format(d.price) }}；均線狀態為 {{ {'above_ma20_ma60':'站上 MA20 與 MA60', 'above_ma20':'站上 MA20', 'below_ma60':'低於 MA60', 'mixed':'均線交錯'}.get(trend_observation, '資料不足') }}。</p>
+      <p class="muted">{{ quote_label }} {{ '{:,.2f}'.format(d.price) }}；均線狀態為 {{ {'above_ma20_ma60':'站上 MA20 與 MA60', 'above_ma20':'站上 MA20', 'below_ma60':'低於 MA60', 'mixed':'均線交錯'}.get(trend_observation, '資料不足') }}。</p>
       <p class="muted small">資料日 {{ as_of }}｜{{ quant_source }}</p>
       <button class="button button-secondary watchlist-toggle" type="button" data-watchlist-toggle data-code="{{ d.code }}" data-name="{{ d.name }}" aria-pressed="false">加入關注</button>
     </div>
     <section class="summary-strip" aria-label="個股觀察摘要">
-      <article class="summary-card"><span>最新收盤</span><strong>{{ '{:,.2f}'.format(d.price) }}</strong><small>資料日 {{ as_of }}</small></article>
+      <article class="summary-card"><span>{{ quote_label }}</span><strong>{{ '{:,.2f}'.format(d.price) }}</strong><small>資料日 {{ as_of }}</small></article>
       <article class="summary-card"><span>MA20</span><strong>{{ '{:,.2f}'.format(ma20) if ma20 is not none else '資料不足' }}</strong><small>20 日移動平均</small></article>
       <article class="summary-card"><span>MA60</span><strong>{{ '{:,.2f}'.format(ma60) if ma60 is not none else '資料不足' }}</strong><small>60 日移動平均</small></article>
       <article class="summary-card"><span>量比</span><strong>{{ '%.2f'|format(volume_ratio) if volume_ratio is not none else '資料不足' }}</strong><small>相對近期常態量</small></article>
     </section>
   </header>
 
   <section class="panel trade-plan-panel" aria-label="條件式交易計畫" data-trade-plan
            data-market="{{ market }}" data-symbol="{{ d.code }}">
       <div class="section-heading"><div><p class="eyebrow">TRADE PLAN · TRIAL</p><h2>條件式交易計畫</h2></div></div>
-      <p class="muted small">日線規則試用版，尚未驗證獲利能力。私人計畫經 no-store API 載入；資料截至日、觸發價、上限、失效價載入後顯示。</p>
+      <p class="muted small">日線規則試用版，尚未驗證獲利能力。使用 LINE 登入且受邀後，可查看自己的資料截至日、觸發條件與失效條件。</p>
       <div data-plan-body><p class="empty-state">載入中…</p></div>
     </section>
 
     <nav class="page-jump-nav glass-panel" aria-label="個股觀察導覽">
     <a href="#summary">總覽</a><a href="#chart">價格</a><a href="#chips">籌碼</a><a href="#technicals">技術</a><a href="#risk">風險</a>{% if intel_snapshot %}<a href="#intel">申報資料</a>{% endif %}{% if peers or related_relationships or related_events or related_opinions %}<a href="#research">研究</a>{% endif %}
   </nav>
 
   {% if peers or related_relationships or related_events or related_opinions %}
   <section class="panel research-tabs" id="research" aria-labelledby="research-title" data-research-tabs>
     <div class="section-heading"><div><p class="eyebrow">RESEARCH</p><h2 id="research-title">研究資料</h2></div></div>
     <div class="research-tablist" role="tablist" aria-label="研究資料分類">
       {% if peers %}<button type="button" role="tab" id="tab-peers" aria-controls="panel-peers" aria-selected="true" data-research-tab="panel-peers">同儕</button>{% endif %}
       {% if related_relationships %}<button type="button" role="tab" id="tab-relationships" aria-controls="relationships" aria-selected="{{ 'false' if peers else 'true' }}" data-research-tab="relationships">關係</button>{% endif %}
       {% if related_events %}<button type="button" role="tab" id="tab-events" aria-controls="company-events" aria-selected="{{ 'false' if peers or related_relationships else 'true' }}" data-research-tab="company-events">事件</button>{% endif %}
       {% if related_opinions %}<button type="button" role="tab" id="tab-opinions" aria-controls="public-opinions" aria-selected="{{ 'false' if peers or related_relationships or related_events else 'true' }}" data-research-tab="public-opinions">觀點</button>{% endif %}
     </div>
     {% if peers %}
     <div role="tabpanel" id="panel-peers" aria-labelledby="tab-peers" data-research-panel="panel-peers" tabindex="0">
       <div class="section-heading">
         <div><p class="eyebrow">INDUSTRY PEERS</p><h3 id="peer-title">產業同儕</h3></div>
         <span class="muted small">{{ peer_category }}</span>
       </div>
       <div class="peer-list">
         {% for peer in peers %}<a class="peer-chip" href="{{ url_for('stock_page', code=peer.code) }}"><strong>{{ peer.name }}</strong><span>{{ peer.code }}</span></a>{% endfor %}
       </div>
diff --git a/templates/stocks.html b/templates/stocks.html
index 19253f3..d3d6c22 100644
--- a/templates/stocks.html
+++ b/templates/stocks.html
@@ -8,45 +8,46 @@
   <span>{% if item.name and item.name|upper != item.symbol|upper %}{{ item.name }} · {{ item.symbol }}{% else %}{{ item.symbol }}{% endif %}</span>
   <strong>{{ item.observation }}</strong>
   <div class="event-card-meta"><b>{{ severity_labels.get(item.severity, '注意') }}</b>{% if item.metric_value is not none %}<p class="{{ 'positive' if item.metric_value > 0 else 'negative' if item.metric_value < 0 else '' }}">{{ item.metric_value }}{{ unit_labels.get(item.unit, ' ' + (item.unit or '')) }}</p>{% endif %}</div>
   <small>資料日 {{ item.as_of }}</small>
 </a>
 {%- endmacro %}
 {% macro event_group(key, title, items) -%}
 <details class="event-group event-{{ key }}" data-event-group="{{ key }}"><summary class="event-group-heading"><h3>{{ title }}</h3><span>{{ items|length }} 件</span></summary><div class="top-picks">{% for item in items %}{{ event_card(item) }}{% else %}<div class="empty-state">目前沒有{{ title }}事件。</div>{% endfor %}</div></details>
 {%- endmacro %}
 {% set events = observation.stock_events or [] %}
 {% set groups = namespace(up=[], down=[], volume=[], institution=[], technical=[], data=[]) %}
 {% for item in events %}
   {% if item.event_type == 'price_move' and item.metric_value > 0 %}{% set groups.up = groups.up + [item] %}
   {% elif item.event_type == 'price_move' %}{% set groups.down = groups.down + [item] %}
   {% elif item.event_type in ('volume_surge','volume_dry_up') %}{% set groups.volume = groups.volume + [item] %}
   {% elif item.event_type == 'institution_flow' %}{% set groups.institution = groups.institution + [item] %}
   {% elif item.event_type in ('rsi_overbought','rsi_oversold','new_high_20d','new_low_20d') %}{% set groups.technical = groups.technical + [item] %}
   {% elif item.event_type == 'data_warning' %}{% set groups.data = groups.data + [item] %}
   {% endif %}
 {% endfor %}
 {% set official = observation.trading_status_observations or [] %}
 <div class="page dashboard-page"{% if market|default('TW', true) == 'TW' %} data-dashboard-endpoint="/api/dashboard"{% endif %}>
   <header class="page-header"><div><p class="eyebrow">STOCK ACTUALS</p><h1>個股與 ETF</h1><p class="page-intro">搜尋標的，或依事件類型查看已觸發的市場觀察。</p></div></header>
   {% if search_error %}<div class="error-banner" role="alert">找不到「{{ search_query }}」，請輸入台股代碼、名稱或美股代碼。</div>{% endif %}
   {% if data_unavailable %}<div class="error-banner" role="alert">已驗證的美股個股與 ETF 觀察暫時無法取得，請稍後再試。</div>{% endif %}
+  {% if market == 'US' and not data_unavailable %}{% include "observation_freshness.html" %}{% endif %}
   <section class="panel" aria-labelledby="stock-search-title"><h2 id="stock-search-title">搜尋股票</h2><form class="stock-search" action="{{ url_for('search_page') }}" method="get" role="search"><input type="hidden" name="market" value="{{ market|default('TW', true) }}"><label class="search-label" for="stock-search">股票代碼或名稱</label><div class="search-control"><input id="stock-search" name="q" value="{{ search_query }}" placeholder="輸入 2330、台積電或 AAPL" autocomplete="off" required><button type="submit">查看觀察</button></div></form></section>
   {% if not data_unavailable %}
   <section class="panel picks-panel" aria-labelledby="events-title">
     <div class="section-heading"><div><h2 id="events-title">個股異常事件</h2><p>漲跌、量能、法人、技術、官方狀態與資料警示分開呈現；分類不代表事件之間具有因果關係。</p></div></div>
     <p class="event-severity-rule">分級規則：價格異常與資料警示為「極端」；量能放大、技術與法人事件為「顯著」；量能收縮為「注意」。</p>
     <div class="event-groups" data-stock-events>
       {{ event_group('up', '異常上漲', groups.up) }}
       {{ event_group('down', '異常下跌', groups.down) }}
       {{ event_group('volume', '量能異常', groups.volume) }}
       {{ event_group('institution', '法人動向', groups.institution) }}
       {{ event_group('technical', '技術面', groups.technical) }}
       <details class="event-group event-official" data-event-group="official"><summary class="event-group-heading"><h3>官方事件</h3><span>{{ official|length }} 件</span></summary><div class="top-picks">{% for item in official %}<a class="pick-card event-card severity-high" href="{{ url_for('stock_page', code=item.symbol) }}"><span>{{ item.name }} · {{ item.symbol }}</span><strong>{{ item.label }}</strong><div class="event-card-meta"><b>官方</b></div><small>驗證日 {{ item.observation_as_of }}</small></a>{% else %}<div class="empty-state">目前沒有官方事件。</div>{% endfor %}</div></details>
       {{ event_group('data', '資料警示', groups.data) }}
     </div>
   </section>
-  <section class="panel picks-panel" aria-labelledby="etf-title"><div class="section-heading"><div><h2 id="etf-title">ETF 觀察</h2></div></div><div class="top-picks" data-etf-observations>{% for item in observation.etf_observations or [] %}<a class="pick-card" href="{{ url_for('stock_page', code=item.symbol) }}"><span>{{ item.name }} · {{ item.symbol }}</span><strong>收盤 {{ item.price }}</strong><small>5 日 {{ '%+.2f%%'|format(item.return_5d_pct) if item.return_5d_pct is not none else '資料不足' }}</small></a>{% else %}<div class="empty-state">ETF 觀察資料不足。</div>{% endfor %}</div></section>
+  <section class="panel picks-panel" aria-labelledby="etf-title"><div class="section-heading"><div><h2 id="etf-title">ETF 觀察</h2></div></div><div class="top-picks" data-etf-observations>{% for item in observation.etf_observations or [] %}<a class="pick-card" href="{{ url_for('stock_page', code=item.symbol) }}"><span>{{ item.name }} · {{ item.symbol }}</span><strong>收盤 {{ item.price }}</strong><small>5 日 {{ '%+.2f%%'|format(item.return_5d_pct) if item.return_5d_pct is not none else '資料不足' }}</small><small>資料日 {{ item.as_of or observation.observation_as_of or '未提供' }}</small></a>{% else %}<div class="empty-state">ETF 觀察資料不足。</div>{% endfor %}</div></section>
   {% endif %}
   <div class="error-banner" data-dashboard-error hidden>個股觀察資料暫時無法取得。</div>
 </div>
 {% endblock %}
diff --git a/tests/test_observation_public_surfaces.py b/tests/test_observation_public_surfaces.py
index 9a0eb83..fe2e624 100644
--- a/tests/test_observation_public_surfaces.py
+++ b/tests/test_observation_public_surfaces.py
@@ -356,50 +356,116 @@ class ObservationPublicSurfaceTests(unittest.TestCase):
         payloads = (
             stock_app.build_stock_observation_flex(
                 "2330",
                 "台積電",
                 data,
                 "https://example.com/stock/2330",
             ),
             stock_app.build_line_navigation_flex("https://example.com"),
             stock_app.build_alert_menu_flex(
                 "2330", "台積電", prediction_allowed=False
             ),
         )
 
         encoded = json.dumps(payloads, ensure_ascii=False)
         for text in (
             "五日上漲機率",
             "模型輸出",
             "產業預測",
             "推薦",
             "回測",
             "績效",
             "投資試算",
         ):
             self.assertNotIn(text, encoded)
 
+    @patch("stock_papi.web.routes.system._utc_now", return_value=datetime.datetime(2026, 10, 7, 12, tzinfo=datetime.timezone.utc))
+    @patch.object(stock_app, "_asksorb_report_citation")
+    @patch.object(stock_app, "_asksorb_grounded_answer", return_value=None)
+    @patch.object(stock_app, "_published_dashboard_snapshot")
+    @patch.object(stock_app, "search_stock_code", return_value=(None, None))
+    @patch.object(stock_app, "fetch_published_quant_snapshot")
+    def test_market_date_question_uses_dashboard_even_in_stock_or_us_context(
+        self, fetch, search, snapshot, grounded, citation, clock
+    ):
+        snapshot.return_value = observation_dashboard()
+        citation.return_value = {"label": "盤後觀察", "url": "/reports/2026-07-15/post-close"}
+        for context in ({}, {"market_context": "US"},
+                        {"page_context": "stock", "symbol_context": "AAPL"}):
+            answer = stock_app.run_absorb_conversation(
+                principal="web:test", question="台股最新資料日是哪一天？請附來源。", **context
+            )
+            self.assertEqual(answer.data_as_of, "2026-07-15")
+            self.assertIn("2026-07-15", answer.text)
+            self.assertIn("資料過期", answer.text)
+            self.assertTrue(answer.stale)
+            self.assertEqual(answer.data_quality, "stale")
+            self.assertEqual(answer.citations[0]["url"], "/reports/2026-07-15/post-close")
+        fetch.assert_not_called()
+        grounded.assert_not_called()
+
+    @patch.object(stock_app, "_conversation_report_lookup")
+    @patch.object(stock_app, "search_stock_code", return_value=(None, None))
+    def test_explicit_us_date_question_does_not_inherit_tw_stock_page(self, search, lookup):
+        lookup.return_value = {"data_quality": "available", "source_market_date": "2026-10-02",
+                               "applicable_trading_date": "2026-10-05"}
+        answer = stock_app.run_absorb_conversation(
+            principal="web:test", question="美股最新資料日是哪一天？請附來源。",
+            market_context="TW", page_context="stock", symbol_context="2330",
+        )
+        self.assertIn("美股最近一次已驗證資料日：2026-10-02", answer.text)
+        self.assertEqual(answer.citations[0]["url"], "/reports/us/2026-10-02/post-close")
+        lookup.assert_called_once_with("post_close", market="US")
+
+    @patch("stock_papi.web.routes.system._utc_now", return_value=datetime.datetime(2026, 7, 6, 4, tzinfo=datetime.timezone.utc))
+    @patch.object(stock_app, "resolve_entities", return_value=[
+        {"market": "TW", "symbol": "2330", "name": "台積電"},
+        {"market": "US", "symbol": "AAPL", "name": "Apple"},
+    ])
+    @patch.object(stock_app, "fetch_published_quant_snapshot")
+    def test_stock_date_uses_successful_observation_market_and_official_status_date(self, fetch, resolve, clock):
+        us = quant_snapshot('AAPL', 'US')
+        us['daily'] = [row for row in us['daily'] if row['Date'][:10] <= '2026-07-02']
+        us['as_of'] = '2026-07-02'
+        fetch.side_effect = [None, us]
+        answer = stock_app.run_absorb_conversation(
+            principal='web:test', question='2330和AAPL最新資料日與過期狀態？'
+        )
+        self.assertIn('AAPL', answer.text)
+        self.assertIn('資料最新', answer.text)
+        self.assertEqual(answer.data_quality, 'available')
+        self.assertFalse(answer.stale)
+
+        status = status_stock_document()
+        clock.return_value = datetime.datetime(2026, 7, 20, 4, tzinfo=datetime.timezone.utc)
+        resolve.return_value = [{'market': 'TW', 'symbol': status['symbol'], 'name': status['name']}]
+        fetch.side_effect = None
+        fetch.return_value = status
+        answer = stock_app.run_absorb_conversation(principal='web:test', question='最新資料日？')
+        self.assertEqual(answer.data_as_of, status['observation_as_of'])
+        self.assertEqual(answer.citations[0]['date'], status['observation_as_of'])
+
     @patch.object(stock_app, "fetch_published_quant_snapshot")
     @patch.object(stock_app, "search_stock_code")
     def test_formal_conversation_is_deterministic_observation_only(
         self, search, fetch
     ):
         search.return_value = ("2330", "台積電")
         fetch.return_value = quant_snapshot()
 
         answer = stock_app.run_absorb_conversation(
             principal="web:test",
             question="台積電目前的價格與均線如何？",
         )
 
         self.assertIn("最新收盤", answer.text)
         self.assertIn("均線狀態", answer.text)
         self.assertEqual(
             answer.tools_used, ("verified_observation_snapshot",)
         )
         for text in (
             "五日上漲機率",
             "推薦",
             "排名",
             "回測",
             "勝率",
             "績效",
diff --git a/tests/test_professional_report_html.py b/tests/test_professional_report_html.py
index a5a0f60..a62c059 100644
--- a/tests/test_professional_report_html.py
+++ b/tests/test_professional_report_html.py
@@ -1,35 +1,49 @@
 import pathlib
 import unittest
 
 from jinja2 import DictLoader, Environment
 
 from reporting.professional_builder import build_professional_post_close_artifact
 from reporting.professional_html import build_professional_report_view
 
 
 class ProfessionalReportHtmlTests(unittest.TestCase):
+    def test_uncategorized_observations_do_not_claim_risk_or_unused_models(self):
+        view = self._view()
+        view['key_events'] = [dict(headline='中性事件', description='中性事件'),
+                              dict(headline='有明確風險', description='限制', category='risk')]
+        env = Environment(loader=DictLoader({
+            'report': pathlib.Path('templates/reports/post_close_professional.html').read_text(encoding='utf-8'),
+            'base.html': '{% block content %}{% endblock %}',
+        }))
+        html = env.get_template('report').render(report=view)
+        self.assertIn('event-category-badge">觀察', html)
+        self.assertIn('event-category-badge">風險', html)
+        self.assertEqual(html.count('中性事件'), 1)
+        self.assertNotIn('量化回歸研究模型', html)
+
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
diff --git a/tests/test_report_web.py b/tests/test_report_web.py
index a42eed1..35093c4 100644
--- a/tests/test_report_web.py
+++ b/tests/test_report_web.py
@@ -292,50 +292,51 @@ class ReportWebTests(unittest.TestCase):
         metadata = build_post_close_observation_metadata(dashboard, Calendar())
         metadata["market"] = "US"
         professional = build_professional_post_close_artifact(
             metadata, code_commit_sha="b" * 40
         )
         publish_report_v2(root, metadata, professional_report=professional)
         publish = root / "publish" / "reports" / "v2"
         objects = {
             f"reports/v2/{path.relative_to(publish).as_posix()}": path.read_bytes()
             for path in publish.rglob("*")
             if path.is_file()
         }
 
         with patch.object(
             stock_app,
             "_gcs_get_report_v2_object",
             side_effect=lambda path, _size: objects.get(path)
             if path.startswith("reports/v2/")
             else objects.get(f"reports/v2/{path}"),
             create=True,
         ):
             observation = stock_app._published_us_securities_observation()
 
         self.assertEqual(observation["stock_events"][0]["symbol"], "AAPL")
         self.assertEqual(observation["etf_observations"][0]["symbol"], "SPY")
+        self.assertEqual(observation["observation_as_of"], professional.identity.source_market_date.isoformat())
 
     def test_explicit_item_market_mismatch_is_rejected_by_index_validator(self):
         temporary, objects, _metadata = self._objects()
         self.addCleanup(temporary.cleanup)
         index = json.loads(objects["reports/v2/index-TW.json"])
         index["reports"][0]["market"] = "US"
 
         with self.assertRaises(ReportWebError):
             validate_report_index(
                 json.dumps(index).encode("utf-8"), expected_market="TW"
             )
 
     def test_production_shaped_daily_reports_have_distinct_canonical_pages(self):
         temporary, objects = self._production_shaped_objects()
         self.addCleanup(temporary.cleanup)
 
         with patch.object(
             stock_app,
             "_gcs_get_report_v2_object",
             side_effect=lambda path, _size: objects.get(path) if path.startswith("reports/v2/") else objects.get(f"reports/v2/{path}"),
             create=True,
         ):
             client = stock_app.app.test_client()
             post_close = client.get("/reports/2026-07-15/post-close")
             pre_market = client.get("/reports/2026-07-16/pre-market")
diff --git a/tests/test_reports_template.py b/tests/test_reports_template.py
index 79490ec..5bb9c02 100644
--- a/tests/test_reports_template.py
+++ b/tests/test_reports_template.py
@@ -1,32 +1,42 @@
 import pathlib
 import unittest
 
 from jinja2 import DictLoader, Environment
 
 
 class ReportsTemplateTests(unittest.TestCase):
+    def test_older_reports_use_closed_native_disclosure_without_removing_history(self):
+        reports = [dict(report_type='post_close', title=f'報告-{day}', summary=['摘要'],
+                        source_market_date=f'2026-07-{day:02d}', applicable_trading_date=f'2026-07-{day+1:02d}')
+                   for day in range(20, 12, -1)]
+        output = self._render(reports_v2=reports, reports=[])
+        self.assertIn('<details class="report-history-older">', output)
+        self.assertIn('查看較早報告（5 份）', output)
+        self.assertEqual(output.count('class="report-card report-card-post_close"'), 8)
+        self.assertIn('type="date"', output)
+
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
diff --git a/tests/test_research_routes.py b/tests/test_research_routes.py
index 46c6757..0e120a9 100644
--- a/tests/test_research_routes.py
+++ b/tests/test_research_routes.py
@@ -1,35 +1,65 @@
 import unittest
 from pathlib import Path
 
 from flask import Flask
 
 from stock_papi.services import public_opinions
 from stock_papi.web.routes.research import register_research_routes
 
 
 class ResearchRouteTests(unittest.TestCase):
+    def test_relationship_links_and_compare_share_supported_markets(self):
+        html = self.client.get('/industries/ai-server/relationships').get_data(as_text=True)
+        self.assertIn('/stock/NVDA', html)
+        self.assertEqual(self.client.get('/compare?symbols=NVDA,2317').status_code, 200)
+        self.assertEqual(self.client.get('/compare?symbols=000660,NVDA').status_code, 400)
+
+    def test_unsupported_market_keeps_evidence_without_broken_links(self):
+        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
+        app.add_url_rule('/industries', 'industries_page', lambda: '')
+        app.add_url_rule('/stock/<code>', 'stock_page', lambda code: code)
+        register_research_routes(app, load_relationships=lambda: {
+            'topic': 'AI 伺服器', 'stages': [], 'relationships': [{
+                'from': {'symbol': '000660', 'name': 'SK hynix'},
+                'to': {'symbol': 'NVDA', 'name': 'NVIDIA'}, 'type': '供應關係',
+                'source': {'url': 'https://example.com/evidence', 'title': '來源'},
+            }]}, load_events=lambda: [], load_opinions=lambda: {},
+            stock_observation=lambda code: {'as_of': '2026-10-02' if code == 'NVDA' else '2026-10-07'},
+            get_stock_name=lambda code: code,
+            allowed_symbols=lambda: {'2330'})
+        html = app.test_client().get('/industries/ai-server/relationships').get_data(as_text=True)
+        self.assertNotIn('/stock/000660', html)
+        self.assertNotIn('symbols=000660,NVDA', html)
+        self.assertIn('000660 尚未提供個股觀察', html)
+        self.assertIn('https://example.com/evidence', html)
+        compare = app.test_client().get('/compare?symbols=NVDA,2330')
+        self.assertEqual(compare.status_code, 200)
+        self.assertIn('2026-10-02', compare.get_data(as_text=True))
+        self.assertIn('2026-10-07', compare.get_data(as_text=True))
+        self.assertIn('不能視為同日比較', compare.get_data(as_text=True))
+
     def test_company_announcements_paginate_and_keep_filters(self):
         app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
         rows = [dict(id=f'announcement-{i}', symbol='2317', name='鴻海', event_type='重大訊息',
                      title=f'公告-{i}', published_at='2026-09-16T09:00:00+08:00', status='confirmed',
                      source='https://openapi.twse.com.tw/v1/opendata/t187ap04_L') for i in range(21)]
         register_research_routes(app, load_relationships=lambda: {}, load_events=lambda: rows,
                                  load_opinions=lambda: self.opinion_catalog, stock_observation=lambda symbol: {},
                                  get_stock_name=lambda symbol: symbol, allowed_symbols=['2317'])
         client = app.test_client()
         html = client.get('/events?symbol=2317&as_of=2026-09-17').get_data(as_text=True)
         self.assertIn('下一頁', html)
         self.assertEqual(html.count('class="event-research-card"'), 20)
         self.assertIn('symbol=2317', html)
         second = client.get('/events?symbol=2317&as_of=2026-09-17&page=2')
         self.assertEqual(second.status_code, 200)
         self.assertEqual(second.get_data(as_text=True).count('class="event-research-card"'), 1)
         self.assertEqual(client.get('/events?page=bad').status_code, 400)
         self.assertEqual(client.get('/events?as_of=2026-09-17&page=3').status_code, 400)
 
     def test_opinions_hide_pending_and_records_not_available_at_cutoff_on_all_pages(self):
         pending = dict(self.opinion_catalog['opinions'][0], is_confirmed=False, text='PENDING PRIVATE TEXT')
         future = dict(self.opinion_catalog['opinions'][0], reviewed_at='2099-01-01T00:00:00Z', text='FUTURE REVIEW TEXT')
         self.opinion_catalog['opinions'].extend([pending, future])
         for path in ('/perspectives', '/perspectives/alpha', '/perspectives/stocks/US/NVDA'):
             html = self.client.get(path + '?cutoff_at=2026-09-17T08:00:00Z').get_data(as_text=True)
diff --git a/tests/test_web_product.py b/tests/test_web_product.py
index 94414dc..a458a4b 100644
--- a/tests/test_web_product.py
+++ b/tests/test_web_product.py
@@ -27,50 +27,96 @@ from tests.test_observation_public_surfaces import (
 def prediction_product(market="TW", symbol="2330", as_of="2026-07-15"):
     return {
         "schema_version": 1,
         "kind": "absorb-five-session-predictions",
         "market": market,
         "as_of": as_of,
         "model_version": "lgbm-5d-v1",
         "backtest_sha256": "b" * 64,
         "entities": {
             symbol: {
                 "symbol": symbol,
                 "entity_type": "market_index" if symbol.startswith("^") or symbol == "TAIEX" else "security",
                 "as_of": as_of,
                 "target_session": "2026-07-22",
                 "current_price": 23150.25 if symbol == "TAIEX" else 164.0,
                 "up_probability": 0.68,
                 "predicted_return_5d": 0.0427,
                 "predicted_price": 24138.765675 if symbol == "TAIEX" else 171.0028,
                 "predicted_change_pct": 4.27,
             }
         },
     }
 
 
 class WebProductTests(unittest.TestCase):
+    @patch.object(stock_app, '_published_report_index_v2')
+    def test_report_date_filter_uses_each_report_type_date_and_validates_input(self, load_index):
+        load_index.return_value = [dict(product_mode='observation', report_type=kind, title=kind, summary=['市場風險狀態：normal'],
+                                       source_market_date='2026-07-15', applicable_trading_date='2026-07-16')
+                                  for kind in ('post_close', 'pre_market')]
+        client = stock_app.app.test_client()
+        for path in ('/reports', '/reports/us'):
+            source = client.get(path + '?date=2026-07-15').get_data(as_text=True)
+            applicable = client.get(path + '?date=2026-07-16').get_data(as_text=True)
+            self.assertIn('report-card-post_close', source)
+            self.assertNotIn('report-card-pre_market', source)
+            self.assertIn('report-card-pre_market', applicable)
+            self.assertNotIn('report-card-post_close', applicable)
+            self.assertIn('市場風險狀態：一般', source)
+            self.assertEqual(client.get(path + '?date=2026-02-30').status_code, 400)
+        self.assertEqual(load_index.return_value[0]['summary'], ['市場風險狀態：normal'])
+
+    def test_stock_and_etf_freshness_uses_the_observation_date(self):
+        with patch.object(stock_app, "fetch_published_quant_snapshot", return_value=quant_snapshot()), \
+             patch.object(stock_app, "_published_us_securities_observation", return_value={
+                 "observation_as_of": "2026-07-15", "stock_events": [],
+                 "etf_observations": [{"symbol": "SPY", "name": "S&P 500 ETF", "price": 600,
+                                       "return_5d_pct": None}]}), \
+             patch.object(web_routes.system, "_utc_now", return_value=dt.datetime(2026, 7, 20, 12, tzinfo=dt.timezone.utc)), \
+             patch.object(web_routes.system, "_next_session_for_market", side_effect=lambda market, day: day + dt.timedelta(days=1)):
+            for path, date in (('/stock/2330', quant_snapshot()['as_of']), ('/us/stocks', '2026-07-15')):
+                html = stock_app.app.test_client().get(path).get_data(as_text=True)
+                self.assertIn('data-freshness-status="stale"', html)
+                self.assertIn('資料日 ' + date, html)
+                self.assertIn('不代表今日即時行情', html)
+                if path.startswith('/stock/'):
+                    self.assertIn('最近可用收盤', html)
+
+    def test_observation_freshness_preserves_weekends_and_fails_closed(self):
+        loader = web_routes.system.create_data_freshness_loader(
+            load_dashboard_snapshot=lambda: {}, load_report_index_v2=lambda **kwargs: [],
+            next_session_for_market=lambda market, day: dt.date(2026, 10, 5) if day == dt.date(2026, 10, 2) else dt.date(2026, 10, 6),
+        )
+        for date, expected in [('2026-10-04', 'current'), ('2026-10-05', 'current'),
+                               ('2026-10-06', 'updating'), ('2026-10-07', 'stale')]:
+            actual = loader('US', observation_as_of='2026-10-02',
+                            reference_now=dt.datetime.fromisoformat(date + 'T16:00:00+00:00'))
+            self.assertEqual(actual['status'], expected)
+            self.assertEqual(actual['source_market_date'], '2026-10-02')
+        self.assertEqual(loader('US', observation_as_of='broken')['status'], 'unavailable')
+
     @patch.object(stock_app, "_published_prediction_snapshot")
     @patch.object(stock_app, "_published_dashboard_snapshot")
 
     def test_dashboard_plainly_marks_uncalibrated_research_prediction(
         self, load_snapshot, load_prediction
     ):
         snapshot = observation_dashboard()
         snapshot["market_index"] = {
             "symbol": "TAIEX", "name": "加權指數", "as_of": "2026-07-15",
             "price": 23150.25, "change": 188.4, "change_pct": 0.82,
             "open": 22982.1, "high": 23210.8, "low": 22940.6,
             "candles": [], "ma20": [], "returns": {},
             "source": {"provider": "TWSE", "kind": "official_index_daily"},
         }
         estimate = prediction_product(symbol="TAIEX")
         estimate["schema_version"] = 2
         estimate["validation_mode"] = "research"
         estimate.pop("backtest_sha256")
         load_snapshot.return_value = snapshot
         load_prediction.return_value = estimate
 
         html = stock_app.app.test_client().get("/dashboard").get_data(as_text=True)
 
         self.assertIn("模型推估上漲機率（未校準）", html)
         self.assertIn("未經回測校準", html)
diff --git a/tests/visual_qa_server.py b/tests/visual_qa_server.py
index d7fa232..7c814d3 100644
--- a/tests/visual_qa_server.py
+++ b/tests/visual_qa_server.py
@@ -326,55 +326,56 @@ REPORT_METADATA = {
                 "advantage": "歷史結果略優於買進持有，仍需考慮成本與樣本限制。",
                 "cumulative_return": "投入 10 萬元，歷史結果約變成 10.8 萬元。",
                 "maximum_drawdown": "最差階段約回落 6%。", "win_rate": "每 100 次約 57 次獲利。",
                 "cash_ratio": "策略約 35% 的時間保持空手。",
             },
         },
         "model_quality": {"samples": 24, "direction_accuracy": "54.0%", "brier_score": "0.230"},
     },
 }
 
 
 stock_app._published_dashboard_snapshot = visual_dashboard
 stock_app._published_prediction_snapshot = visual_prediction_snapshot
 stock_app.fetch_published_quant_snapshot = visual_quant_snapshot
 stock_app.find_industry_peers = lambda _code: {"category": "半導體", "codes": ["2454"]}
 stock_app.get_stock_name = lambda code: "聯發科" if code == "2454" else "台積電"
 
 
 class VisualCalendar:
     def next_session(self, _value):
         return datetime.date(2026, 7, 16)
 
 
 _REPORT_ROOT = tempfile.TemporaryDirectory()
 _REPORT_PUBLISH = Path(_REPORT_ROOT.name)
+_TW_METADATA = build_post_close_observation_metadata(observation_dashboard(), VisualCalendar())
 publish_report_v2(
     _REPORT_PUBLISH,
-    build_post_close_observation_metadata(
-        observation_dashboard(),
-        VisualCalendar(),
+    _TW_METADATA,
+    professional_report=build_professional_post_close_artifact(
+        _TW_METADATA, code_commit_sha="b" * 40
     ),
 )
 _US_METADATA = build_post_close_observation_metadata(
     observation_dashboard(), VisualCalendar()
 )
 _US_METADATA.update(market="US", title="2026-07-15 美股盤後市場觀察")
 publish_report_v2(
     _REPORT_PUBLISH,
     _US_METADATA,
     professional_report=build_professional_post_close_artifact(
         _US_METADATA, code_commit_sha="b" * 40
     ),
 )
 _REPORT_V2_ROOT = _REPORT_PUBLISH / "publish" / "reports" / "v2"
 _REPORT_OBJECTS = {
     f"reports/v2/{path.relative_to(_REPORT_V2_ROOT).as_posix()}": path.read_bytes()
     for path in _REPORT_V2_ROOT.rglob("*")
     if path.is_file()
 }
 stock_app._gcs_get_report_v2_object = (
     lambda path, _size: _REPORT_OBJECTS.get(path)
 )
 stock_app.line_auth_store = VisualAuthStore()
 stock_app.line_store = VisualLineStore()
 stock_app.utc_now = lambda: NOW

NEW FRESHNESS TEMPLATE:
{% set freshness = observation_freshness|default({}, true) %}
<section class="freshness-status" data-freshness-status="{{ freshness.get('status', 'unavailable') }}" aria-label="觀察資料狀態">
  <div><h2>資料狀態</h2><p>{{ {'current':'資料最新','updating':'更新中','stale':'資料過期','unavailable':'暫時無法核對新鮮度'}.get(freshness.get('status'), '暫時無法核對新鮮度') }}</p></div>
  <p>資料日 {{ freshness.get('source_market_date') or '尚無已驗證日期' }}</p>
  {% if freshness.get('status') in ['stale','updating','unavailable'] %}<p class="freshness-warning">以下為最近一次已驗證觀察，不代表今日即時行情。{{ '新交易日資料尚待發布。' if freshness.get('status') == 'updating' else '最新交易日是否已涵蓋，請以資料日期為準。' }}</p>{% endif %}
</section>


CURRENT SUPPORTING SOURCE stock_papi/web/routes/system.py
1: """Lightweight health, search, data-freshness, and legacy redirect routes."""
2: 
3: import datetime as dt
4: from zoneinfo import ZoneInfo
5: 
6: from flask import jsonify, redirect, request, url_for
7: 
8: from stock_papi.batch.calendar import TradingCalendarSet
9: from stock_papi.integrations.market_data.us_calendar import (
10:     get_us_calendar_documents,
11: )
12: from stock_papi.integrations.market_data.tw_calendar import (
13:     get_tw_calendar_documents,
14: )
15: 
16: 
17: _MARKET_TIMEZONES = {
18:     "TW": ZoneInfo("Asia/Taipei"),
19:     "US": ZoneInfo("America/New_York"),
20: }
21: _UNSET = object()
22: 
23: 
24: def _parse_iso_date(value):
25:     if not isinstance(value, str):
26:         return None
27:     try:
28:         parsed = dt.date.fromisoformat(value)
29:     except ValueError:
30:         return None
31:     return parsed if parsed.isoformat() == value else None
32: 
33: 
34: def _parse_reference_date(value):
35:     if type(value) is dt.date:
36:         return value
37:     return _parse_iso_date(value)
38: 
39: 
40: def _utc_now():
41:     return dt.datetime.now(dt.timezone.utc)
42: 
43: 
44: def market_local_date(market, *, now):
45:     """Return the explicit market-local date for an aware instant."""
46:     timezone = _MARKET_TIMEZONES.get(market)
47:     if timezone is None:
48:         raise ValueError("unsupported market")
49:     if not isinstance(now, dt.datetime) or now.utcoffset() is None:
50:         raise ValueError("now must be timezone-aware")
51:     return now.astimezone(timezone).date()
52: 
53: 
54: def classify_data_freshness(
55:     *,
56:     source_market_date,
57:     applicable_trading_date,
58:     reference_date,
59:     next_session=None,
60: ):
61:     """Classify verified dates against an injected market-session contract."""
62:     source = _parse_iso_date(source_market_date)
63:     applicable = _parse_iso_date(applicable_trading_date)
64:     reference = _parse_reference_date(reference_date)
65:     normalized_source = source.isoformat() if source is not None else None
66:     normalized_applicable = (
67:         applicable.isoformat() if applicable is not None else None
68:     )
69:     status = "unavailable"
70: 
71:     if (
72:         source is not None
73:         and applicable is not None
74:         and reference is not None
75:         and source <= applicable
76:         and reference >= source
77:     ):
78:         if reference <= applicable:
79:             status = "current"
80:         elif callable(next_session):
81:             try:
82:                 updating_boundary = next_session(applicable)
83:             except Exception:
84:                 updating_boundary = None
85:             if (
86:                 type(updating_boundary) is dt.date
87:                 and updating_boundary > applicable
88:             ):
89:                 if reference < updating_boundary:
90:                     status = "current"
91:                 elif reference == updating_boundary:
92:                     status = "updating"
93:                 else:
94:                     status = "stale"
95: 
96:     return {
97:         "status": status,
98:         "source_market_date": normalized_source,
99:         "applicable_trading_date": normalized_applicable,
100:     }
101: 
102: 
103: def _latest_post_close_dates(reports, *, market):
104:     if not isinstance(reports, list):
105:         return None, None, False
106: 
107:     candidates = []
108:     for report in reports:
109:         if not isinstance(report, dict):
110:             return None, None, False
111:         if "market" in report and report.get("market") != market:
112:             return None, None, False
113:         if report.get("report_type") != "post_close":
114:             continue
115:         source = _parse_iso_date(report.get("source_market_date"))
116:         applicable = _parse_iso_date(report.get("applicable_trading_date"))
117:         if source is None or applicable is None or source > applicable:
118:             return None, None, False
119:         candidates.append((applicable, source))
120:     if not candidates:
121:         return None, None, True
122:     applicable, source = max(candidates)
123:     return source.isoformat(), applicable.isoformat(), True
124: 
125: 
126: def _next_session_for_market(market, value):
127:     if market == "TW":
128:         documents = get_tw_calendar_documents(value.year, value.year + 1)
129:     elif market == "US":
130:         documents = get_us_calendar_documents(value.year, value.year + 1)
131:     else:
132:         return None
133:     return TradingCalendarSet.from_documents(documents).next_session(value)
134: 
135: 
136: def create_data_freshness_loader(
137:     *,
138:     load_dashboard_snapshot,
139:     load_report_index_v2,
140:     now=None,
141:     next_session_for_market=None,
142: ):
143:     """Create a lazy, market-scoped verified freshness loader."""
144: 
145:     def unavailable(source=None, applicable=None):
146:         return classify_data_freshness(
147:             source_market_date=source,
148:             applicable_trading_date=applicable,
149:             reference_date=None,
150:             next_session=None,
151:         )
152: 
153:     def load(
154:         market,
155:         *,
156:         reports=_UNSET,
157:         snapshot=_UNSET,
158:         reference_now=_UNSET,
159:         observation_as_of=_UNSET,
160:     ):
161:         if market not in _MARKET_TIMEZONES:
162:             return unavailable()
163: 
164:         resolver = next_session_for_market or _next_session_for_market
165:         if observation_as_of is not _UNSET:
166:             source = _parse_iso_date(observation_as_of)
167:             if source is None:
168:                 return unavailable()
169:             try:
170:                 applicable = resolver(market, source)
171:                 if type(applicable) is not dt.date or applicable <= source:
172:                     return unavailable(source.isoformat())
173:             except Exception:
174:                 return unavailable(source.isoformat())
175:             reports = [{"market": market, "report_type": "post_close",
176:                         "source_market_date": source.isoformat(),
177:                         "applicable_trading_date": applicable.isoformat()}]
178:             snapshot = {"market": market, "observation_as_of": source.isoformat()}
179: 
180:         if reports is _UNSET:
181:             try:
182:                 reports = load_report_index_v2(market=market)
183:             except Exception:
184:                 return unavailable()
185:         source, applicable, valid_market = _latest_post_close_dates(
186:             reports, market=market
187:         )
188:         if not valid_market:
189:             return unavailable()
190: 
191:         if market == "TW":
192:             if snapshot is _UNSET:
193:                 try:
194:                     snapshot = load_dashboard_snapshot()
195:                 except Exception:
196:                     return unavailable()
197:             if not isinstance(snapshot, dict):
198:                 return unavailable()
199:             if "market" in snapshot and snapshot.get("market") != "TW":
200:                 return unavailable()
201:             dashboard_source = _parse_iso_date(snapshot.get("observation_as_of"))
202:             report_source = source
203:             source = (
204:                 dashboard_source.isoformat()
205:                 if dashboard_source is not None
206:                 else None
207:             )
208:             if source is None or source != report_source:
209:                 applicable = None
210: 
211:         try:
212:             instant = (
213:                 (now or _utc_now)()
214:                 if reference_now is _UNSET
215:                 else reference_now
216:             )
217:             reference = market_local_date(market, now=instant)
218:         except Exception:
219:             return unavailable(source, applicable)
220: 
221:         return classify_data_freshness(
222:             source_market_date=source,
223:             applicable_trading_date=applicable,
224:             reference_date=reference,
225:             next_session=lambda value: resolver(market, value),
226:         )
227: 
228:     return load
229: 
230: 
231: def register_system_routes(
232:     app, *, search_stock, load_data_freshness, now=None
233: ):
234:     def healthz():
235:         return "ok", 200
236: 
237:     def data_health():
238:         try:
239:             reference_now = (now or _utc_now)()
240:         except Exception:
241:             reference_now = None
242:         markets = {
243:             market: load_data_freshness(
244:                 market, reference_now=reference_now
245:             )
246:             for market in ("TW", "US")
247:         }
248:         return jsonify({"service": {"status": "ok"}, "markets": markets})
249: 
250:     def search_page():
251:         query = request.args.get("q", "").strip()
252:         market = request.args.get("market", "TW").upper()
253:         code, _name = search_stock(query)
254:         if code:
255:             return redirect(url_for("stock_page", code=code), code=302)
256:         return redirect(
257:             url_for(
258:                 "us_stocks_page" if market == "US" else "stocks_page",
259:                 q=query,
260:                 error="not-found",
261:             ),
262:             code=302,
263:         )
264: 
265:     def watchlist_page():
266:         return redirect("/dashboard", code=302)
267: 
268:     def client_error():
269:         # Privacy-preserving frontend telemetry: fixed counters only,
270:         # no free-text, no user id, no stock code stored.
271:         try:
272:             payload = request.get_json(silent=True) or {}
273:         except Exception:
274:             payload = {}
275:         page = payload.get("page") if isinstance(payload, dict) else None
276:         detail = payload.get("detail") if isinstance(payload, dict) else None
277:         allowed_pages = {"dashboard", "market", "stock", "industries"}
278:         allowed_details = {"timeout", "fetch-failed", "chart-failed"}
279:         if page not in allowed_pages:
280:             page = "unknown"
281:         if detail not in allowed_details:
282:             detail = "unknown"
283:         try:
284:             app.logger.info("client_error page=%s detail=%s", page, detail)
285:         except Exception:
286:             pass
287:         return ("", 204)
288: 
289:     app.add_url_rule("/healthz", "healthz", healthz)
290:     app.add_url_rule("/health", "healthz", healthz)
291:     app.add_url_rule("/health/data", "data_health", data_health)
292:     app.add_url_rule("/search", "search_page", search_page)
293:     app.add_url_rule("/watchlist", "watchlist_page", watchlist_page)
294:     app.add_url_rule("/api/client-error", "client_error", client_error, methods=["POST"])

CURRENT SUPPORTING SOURCE stock_papi/web/routes/reports.py
1: """Public HTML report routes and legacy compatibility redirects."""
2: 
3: import copy
4: import datetime
5: import hashlib
6: import hmac
7: import json
8: import os
9: import re
10: import uuid
11: 
12: from flask import abort, make_response, redirect, render_template, request, url_for
13: 
14: from reporting.exceptions import ReportWebError
15: from reporting.web import find_report
16: from reporting.professional_html import (
17:     REGRESSION_ARTIFACT_UNAVAILABLE_REASON,
18:     build_professional_report_view,
19: )
20: from reporting.professional_binding import (
21:     validate_professional_report_binding,
22:     validate_regression_research_binding,
23: )
24: from reporting.regression_schema import (
25:     MAX_REGRESSION_ARTIFACT_BYTES,
26:     RegressionResearchArtifact,
27: )
28: from reporting.schemas import ReportMetadataV2
29: from stock_papi.services.report_view import (
30:     build_observation_report_view,
31:     dedupe_reports_for_list,
32: )
33: from stock_papi.services.market_summary import build_market_summary_view
34: from stock_papi.services.us_presentation import latest_post_close_item, localize_us_key_event
35: from stock_papi.services.prediction_view import prediction_for
36: from reporting.config import MAX_CANONICAL_REPORT_BYTES
37: from werkzeug.exceptions import HTTPException
38: 
39: 
40: def _valid_report_date(report_date):
41:     try:
42:         parsed = datetime.date.fromisoformat(report_date)
43:     except ValueError:
44:         return False
45:     return parsed.isoformat() == report_date
46: 
47: 
48: def register_report_routes(
49:     app, *, load_index, load_metadata, load_index_v2, load_metadata_v2,
50:     load_metadata_v2_by_sha=None,
51:     load_canonical_object=None, load_regression_artifact=None,
52:     prediction_capability=None,
53:     load_data_freshness=None,
54:     load_prediction_snapshot=None,
55: ):
56:     observation_mode = (
57:         prediction_capability is not None
58:         and prediction_capability.mode == "research"
59:     )
60: 
61:     def _secure_response(response, *, cache="public, max-age=300"):
62:         response.headers["Cache-Control"] = cache
63:         response.headers["X-Content-Type-Options"] = "nosniff"
64:         return response
65: 
66:     def _report_error(status, *, report_type=None, report_date=None, exc=None):
67:         correlation_id = uuid.uuid4().hex[:16]
68:         if exc is not None:
69:             app.logger.exception(
70:                 "report_render_failed correlation_id=%s report_type=%s report_date=%s error_type=%s",
71:                 correlation_id,
72:                 report_type,
73:                 report_date,
74:                 type(exc).__name__,
75:             )
76:         response = make_response(
77:             render_template(
78:                 "report_unavailable.html",
79:                 status=status,
80:                 correlation_id=correlation_id,
81:             ),
82:             status,
83:         )
84:         response.headers["X-Correlation-ID"] = correlation_id
85:         if status == 503:
86:             response.headers["Retry-After"] = "60"
87:         return _secure_response(response, cache="no-store")
88: 
89:     def _v2_reports(market="TW", *, required=False):
90:         try:
91:             reports = load_index_v2(market=market)
92:         except ReportWebError:
93:             raise
94:         except Exception as exc:
95:             raise ReportWebError("報告索引暫時無法使用") from exc
96:         if reports is None:
97:             if required:
98:                 raise ReportWebError("報告索引暫時無法使用")
99:             return []
100:         if not isinstance(reports, list):
101:             raise ReportWebError("報告索引格式錯誤")
102:         if any(
103:             not isinstance(item, dict)
104:             or ("market" in item and item.get("market") != market)
105:             for item in reports
106:         ):
107:             raise ReportWebError("報告索引市場不一致")
108:         if observation_mode:
109:             return [
110:                 item for item in reports
111:                 if item.get("product_mode") == "observation"
112:             ]
113:         return reports
114: 
115:     def _daily_items(trading_date, market="TW"):
116:         reports = _v2_reports(market=market, required=True)
117:         return [
118:             item
119:             for item in reports
120:             if item.get("applicable_trading_date") == trading_date
121:             and item.get("report_type") in {"post_close", "pre_market"}
122:         ]
123: 
124:     def _optional_regression_overlay(*, metadata, report):
125:         pointer = metadata.get("regression_research")
126:         if pointer is None:
127:             return None
128:         try:
129:             metadata_obj = ReportMetadataV2.from_document(metadata)
130:             pointer = metadata_obj.regression_research
131:             if pointer is None or load_regression_artifact is None:
132:                 raise ValueError("regression artifact loader or pointer unavailable")
133: 
134:             object_path = pointer["object"]
135:             expected_sha = pointer["sha256"]
136:             raw_bytes = load_regression_artifact(
137:                 object_path,
138:                 max_bytes=MAX_REGRESSION_ARTIFACT_BYTES,
139:             )
140:             if (
141:                 not isinstance(raw_bytes, bytes)
142:                 or not raw_bytes
143:                 or len(raw_bytes) > MAX_REGRESSION_ARTIFACT_BYTES
144:             ):
145:                 raise ValueError("regression artifact size invalid")
146:             actual_sha = hashlib.sha256(raw_bytes).hexdigest()
147:             if not hmac.compare_digest(actual_sha, expected_sha):
148:                 raise ValueError("regression artifact SHA mismatch")
149:             if object_path != f"objects/regression/{actual_sha}.json":
150:                 raise ValueError("regression artifact path mismatch")
151: 
152:             document = json.loads(raw_bytes.decode("utf-8"))
153:             if not isinstance(document, dict):
154:                 raise ValueError("regression artifact must be an object")
155:             artifact = RegressionResearchArtifact.from_document(document)
156:             validate_regression_research_binding(
157:                 metadata=metadata_obj,
158:                 professional_report=report,
159:                 pointer=pointer,
160:                 regression_artifact=artifact,
161:             )
162:             return artifact
163:         except Exception as exc:
164:             app.logger.warning(
165:                 "optional_regression_overlay_unavailable error_type=%s",
166:                 type(exc).__name__,
167:             )
168:             return None
169: 
170:     def _load_verified_professional_report(*, metadata, route_source_date, expected_market):
171:         """Load one canonical report through the complete fail-closed contract."""
172:         canonical_ptr = metadata.get("professional_report")
173:         if not isinstance(canonical_ptr, dict):
174:             raise ReportWebError("報告 Canonical Object 指標遺失")
175: 
176:         object_path = canonical_ptr.get("object")
177:         expected_sha = canonical_ptr.get("sha256")
178:         if not isinstance(object_path, str) or not object_path:
179:             raise ReportWebError("報告 Canonical Object 指標遺失")
180:         if not isinstance(expected_sha, str) or not expected_sha:
181:             raise ReportWebError("報告 Canonical Object 指標遺失")
182:         if load_canonical_object is None:
183:             raise ReportWebError("系統未提供 load_canonical_object")
184: 
185:         try:
186:             raw_bytes = load_canonical_object(
187:                 object_path, max_bytes=MAX_CANONICAL_REPORT_BYTES
188:             )
189:         except Exception as exc:
190:             raise ReportWebError("無法讀取 Canonical Object") from exc
191:         if (
192:             not isinstance(raw_bytes, bytes)
193:             or len(raw_bytes) == 0
194:             or len(raw_bytes) > MAX_CANONICAL_REPORT_BYTES
195:         ):
196:             raise ReportWebError("Canonical Object 內容無效")
197: 
198:         actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
199:         if not hmac.compare_digest(actual_sha256, expected_sha):
200:             raise ReportWebError("Canonical Object 雜湊比對失敗")
201:         if object_path != f"objects/canonical/{actual_sha256}.json":
202:             raise ReportWebError("Canonical Object 路徑與雜湊不符")
203: 
204:         try:
205:             canonical_doc = json.loads(raw_bytes.decode("utf-8"))
206:         except UnicodeDecodeError as exc:
207:             raise ReportWebError("Canonical Object 解碼失敗") from exc
208:         except json.JSONDecodeError as exc:
209:             raise ReportWebError("Canonical Object JSON 解析失敗") from exc
210:         if not isinstance(canonical_doc, dict):
211:             raise ReportWebError("Canonical Object 格式錯誤")
212: 
213:         from reporting.professional_schema import ProfessionalPostCloseReport
214:         try:
215:             report = ProfessionalPostCloseReport.from_document(canonical_doc)
216:         except (ValueError, TypeError, KeyError) as exc:
217:             raise ReportWebError("Canonical Object 驗證失敗") from exc
218: 
219:         if metadata.get("market") != expected_market or report.identity.market != expected_market:
220:             raise ReportWebError("Professional Report 市場不符")
221: 
222:         try:
223:             canonical_metadata = copy.deepcopy(metadata)
224:             canonical_metadata.pop("regression_research", None)
225:             validate_professional_report_binding(
226:                 route_source_date=route_source_date,
227:                 metadata=canonical_metadata,
228:                 pointer=canonical_ptr,
229:                 report=report,
230:             )
231:         except (ValueError, TypeError) as exc:
232:             raise ReportWebError("Professional Report 綁定驗證失敗") from exc
233:         return report
234: 
235:     def _observation_page(date_param: str, report_type: str, market="TW"):
236:         try:
237:             reports = _v2_reports(market=market, required=True)
238:             if report_type == "post_close":
239:                 # For post_close, canonical date_param is source_market_date
240:                 item = next(
241:                     (value for value in reports
242:                      if value.get("report_type") == report_type
243:                      and value.get("source_market_date") == date_param),
244:                     None,
245:                 )
246:                 if item is None:
247:                     # Fallback: if navigated with applicable_trading_date, redirect to canonical source_market_date URL
248:                     fallback = next(
249:                         (value for value in reports
250:                          if value.get("report_type") == report_type
251:                          and value.get("applicable_trading_date") == date_param),
252:                         None,
253:                     )
254:                     if fallback is not None:
255:                         canonical_date = fallback.get("source_market_date")
256:                         if canonical_date and canonical_date != date_param:
257:                             endpoint = "post_close_report_page" if market == "TW" else "us_post_close_report_page"
258:                             return redirect(url_for(endpoint, trading_date=canonical_date), code=302)
259:             else:
260:                 # For pre_market, date_param is applicable_trading_date
261:                 item = next(
262:                     (value for value in reports
263:                      if value.get("report_type") == report_type
264:                      and value.get("applicable_trading_date") == date_param),
265:                     None,
266:                 )
267: 
268:             if item is None:
269:                 abort(404)
270:             metadata = load_metadata_v2(item, expected_market=market)
271:             if metadata is None:
272:                 raise ReportWebError("報告內容暫時無法使用")
273:             
274:             if report_type == "pre_market":
275:                 content = metadata.get("content")
276:                 base_metadata_sha256 = (
277:                     content.get("base_metadata_sha256")
278:                     if isinstance(content, dict)
279:                     else None
280:                 )
281:                 base_metadata = (
282:                     load_metadata_v2_by_sha(
283:                         base_metadata_sha256, expected_market=market
284:                     )
285:                     if load_metadata_v2_by_sha is not None
286:                     else None
287:                 )
288:                 if base_metadata is not None:
289:                     if (
290:                         base_metadata.get("report_type") != "post_close"
291:                         or base_metadata.get("market", "TW") != market
292:                         or base_metadata.get("source_market_date")
293:                         != metadata.get("source_market_date")
294:                         or base_metadata.get("applicable_trading_date")
295:                         != metadata.get("applicable_trading_date")
296:                     ):
297:                         raise ReportWebError("盤前報告盤後基底不一致")
298:                     expected_base_metadata_sha256 = base_metadata_sha256
299:                 else:
300:                     post_close_item = next(
301:                         (
302:                             value for value in reports
303:                             if value.get("report_type") == "post_close"
304:                             and value.get("applicable_trading_date") == date_param
305:                         ),
306:                         None,
307:                     )
308:                     if post_close_item is None:
309:                         raise ReportWebError("盤前報告缺少盤後基底")
310:                     expected_base_metadata_sha256 = post_close_item.get(
311:                         "metadata_sha256"
312:                     )
313:                 report = build_observation_report_view(
314:                     metadata,
315:                     expected_base_metadata_sha256=expected_base_metadata_sha256,
316:                 )
317:                 response = make_response(
318:                     render_template("report_observation.html", report=report)
319:                 )
320:             elif report_type == "post_close":
321:                 canonical_ptr = metadata.get("professional_report")
322:                 if canonical_ptr is None and metadata.get("product_mode") == "observation":
323:                     report = build_observation_report_view(metadata)
324:                     response = make_response(
325:                         render_template("report_observation.html", report=report)
326:                     )
327:                     return _secure_response(response)
328:                 prof_report = _load_verified_professional_report(
329:                     metadata=metadata,
330:                     route_source_date=date_param,
331:                     expected_market=market,
332:                 )
333: 
334:                 pdf_download_url = None
335:                 regression_artifact = _optional_regression_overlay(
336:                     metadata=metadata,
337:                     report=prof_report,
338:                 )
339:                 view_model = build_professional_report_view(
340:                     prof_report,
341:                     regression_artifact=regression_artifact,
342:                     regression_unavailable_reason=REGRESSION_ARTIFACT_UNAVAILABLE_REASON,
343:                     pdf_download_url=pdf_download_url,
344:                 )
345:                 response = make_response(
346:                     render_template("reports/post_close_professional.html", report=view_model)
347:                 )
348:             else:
349:                 abort(404)
350:             return _secure_response(response)
351:         except ReportWebError as exc:
352:             return _report_error(
353:                 503,
354:                 report_type=report_type,
355:                 report_date=date_param,
356:                 exc=exc,
357:             )
358:         except HTTPException:
359:             raise
360:         except Exception as exc:
361:             return _report_error(
362:                 500,
363:                 report_type=report_type,
364:                 report_date=date_param,
365:                 exc=exc,
366:             )
367: 
368:     def reports_page():
369:         selected_date = request.args.get("date", "")
370:         if selected_date and not _valid_report_date(selected_date):
371:             abort(400)
372:         if observation_mode:
373:             reports = []
374:         else:
375:             try:
376:                 reports = load_index()
377:             except ReportWebError:
378:                 reports = None
379:         try:
380:             reports_v2 = _v2_reports(required=observation_mode)
381:         except ReportWebError as exc:
382:             if observation_mode:
383:                 return _report_error(503, exc=exc)
384:             reports_v2 = None
385:         response = make_response(render_template(
386:             "reports.html", reports=[item for item in reports or []
387:                                      if not selected_date or item.get("report_date") == selected_date],
388:             reports_v2=_history_reports(reports_v2, selected_date),
389:             unavailable=reports is None and reports_v2 is None,
390:             market="TW",
391:             selected_date=selected_date,
392:         ))
393:         return _secure_response(response)
394: 
395:     def report_page(report_date):
396:         if observation_mode:
397:             abort(404)
398:         if not _valid_report_date(report_date):
399:             abort(404)
400:         try:
401:             reports = load_index()
402:         except ReportWebError:
403:             return "報告服務暫時無法使用", 503
404:         if reports is None:
405:             return "報告服務暫時無法使用", 503
406:         item = find_report(reports, report_date)
407:         if item is None:
408:             abort(404)
409:         try:
410:             metadata = load_metadata(item)
411:         except ReportWebError:
412:             return "報告內容暫時無法使用", 503
413:         if metadata is None:
414:             return "報告內容暫時無法使用", 503
415:         response = make_response(render_template(
416:             "report_detail.html",
417:             report=item,
418:             metadata=metadata,
419:             public_report=metadata.get("public_report"),
420:         ))
421:         return _secure_response(response)
422: 
423:     def legacy_report_redirect(report_date):
424:         if not _valid_report_date(report_date):
425:             abort(404)
426:         return redirect(url_for("report_page", report_date=report_date), code=302)
427: 
428:     def sample_report_download():
429:         # Policy: SAMPLE must never be served as a report download; the
430:         # static copy under static/samples/ exists only for local visual
431:         # verification. Always redirect to the public HTML list.
432:         return redirect(url_for("reports_page"), code=302)
433: 
434:     def trading_day_report_page(trading_date):
435:         if not _valid_report_date(trading_date):
436:             abort(404)
437:         try:
438:             items = _daily_items(trading_date)
439:             if not items:
440:                 abort(404)
441:             response = make_response(render_template(
442:                 "report_day_index.html",
443:                 trading_date=trading_date,
444:                 reports=items,
445:             ))
446:             return _secure_response(response)
447:         except ReportWebError as exc:
448:             return _report_error(503, report_date=trading_date, exc=exc)
449:         except HTTPException:
450:             raise
451:         except Exception as exc:
452:             return _report_error(500, report_date=trading_date, exc=exc)
453: 
454:     def post_close_report_page(trading_date):
455:         if not _valid_report_date(trading_date):
456:             abort(404)
457:         return _observation_page(trading_date, "post_close", market="TW")
458: 
459:     def pre_market_report_page(trading_date):
460:         if not _valid_report_date(trading_date):
461:             abort(404)
462:         return _observation_page(trading_date, "pre_market", market="TW")
463: 
464:     def _history_reports(reports, selected_date):
465:         rows = dedupe_reports_for_list(reports or [])
466:         return [{**row, "summary": [localize_us_key_event({"headline": text})["headline"]
467:                                     for text in row.get("summary", [])]}
468:                 for row in rows if not selected_date or selected_date == row.get(
469:                     "applicable_trading_date" if row.get("report_type") == "pre_market" else "source_market_date")]
470: 
471:     def us_reports_page():
472:         selected_date = request.args.get("date", "")
473:         if selected_date and not _valid_report_date(selected_date):
474:             abort(400)
475:         try:
476:             reports_v2 = _v2_reports(market="US", required=observation_mode)
477:         except ReportWebError as exc:
478:             if observation_mode:
479:                 return _report_error(503, exc=exc)
480:             reports_v2 = None
481:         response = make_response(render_template(
482:             "reports.html", reports=[],
483:             reports_v2=_history_reports(reports_v2, selected_date),
484:             unavailable=reports_v2 is None,
485:             market="US",
486:             selected_date=selected_date,
487:         ))
488:         return _secure_response(response)
489: 
490:     def _us_summary_response(template_name):
491:         try:
492:             reports = _v2_reports(market="US", required=True)
493:             item = latest_post_close_item(reports)
494:             if item is None:
495:                 raise ReportWebError("美股盤後報告暫時無法使用")
496:             metadata = load_metadata_v2(item, expected_market="US")
497:             if metadata is None:
498:                 raise ReportWebError("美股報告內容暫時無法使用")
499:             report = _load_verified_professional_report(
500:                 metadata=metadata,
501:                 route_source_date=item.get("source_market_date"),
502:                 expected_market="US",
503:             )
504:             if report.identity.market != "US":
505:                 raise ReportWebError("美股 Canonical Object 市場不一致")
506:             summary = build_market_summary_view(report)
507:             context = {
508:                 "summary": summary,
509:                 "market": "US",
510:                 "index_predictions": [],
511:             }
512:             if template_name == "us_dashboard.html" and load_prediction_snapshot:
513:                 predictions = []
514:                 try:
515:                     product = load_prediction_snapshot("US")
516:                     for symbol, name in (
517:                         ("^GSPC", "S&P 500"),
518:                         ("^IXIC", "Nasdaq Composite"),
519:                         ("^DJI", "道瓊工業指數"),
520:                     ):
521:                         value = prediction_for(
522:                             product, "US", symbol, summary["source_market_date"]
523:                         )
524:                         if value is not None:
525:                             predictions.append({**value, "symbol": symbol, "name": name})
526:                     if not predictions:
527:                         app.logger.info(
528:                             "us_index_predictions_empty source_market_date=%s has_product=%s",
529:                             summary.get("source_market_date"),
530:                             product is not None,
531:                         )
532:                 except Exception:
533:                     predictions = []
534:                 context["index_predictions"] = predictions
535:             if load_data_freshness:
536:                 try:
537:                     context["data_freshness"] = {
538:                         "US": load_data_freshness("US", reports=reports)
539:                     }
540:                 except Exception:
541:                     context["data_freshness"] = {}
542:             response = make_response(render_template(template_name, **context))
543:             return _secure_response(
544:                 response,
545:                 cache="no-store" if template_name == "us_dashboard.html" else "public, max-age=300",
546:             )
547:         except ReportWebError as exc:
548:             return _report_error(503, report_type="post_close", exc=exc)
549:         except Exception as exc:
550:             return _report_error(500, report_type="post_close", exc=exc)
551: 
552:     def us_dashboard_page():
553:         return _us_summary_response("us_dashboard.html")
554: 
555:     def us_market_page():
556:         return _us_summary_response("us_market.html")
557: 
558:     def us_industries_page():
559:         return _us_summary_response("us_industries.html")
560: 
561:     def us_post_close_report_page(trading_date):
562:         if not _valid_report_date(trading_date):
563:             abort(404)
564:         return _observation_page(trading_date, "post_close", market="US")
565: 
566:     def us_pre_market_report_page(trading_date):
567:         if not _valid_report_date(trading_date):
568:             abort(404)
569:         return _observation_page(trading_date, "pre_market", market="US")
570: 
571:     def us_trading_day_report_page(trading_date):
572:         if not _valid_report_date(trading_date):
573:             abort(404)
574:         try:
575:             items = _daily_items(trading_date, market="US")
576:             if not items:
577:                 abort(404)
578:             if any(item.get("report_type") == "post_close" for item in items):
579:                 post_close_item = next(item for item in items if item.get("report_type") == "post_close")
580:                 canonical_source_date = post_close_item.get("source_market_date") or trading_date
581:                 return redirect(
582:                     url_for("us_post_close_report_page", trading_date=canonical_source_date),
583:                     code=302,
584:                 )
585:             if any(item.get("report_type") == "pre_market" for item in items):
586:                 return redirect(
587:                     url_for("us_pre_market_report_page", trading_date=trading_date),
588:                     code=302,
589:                 )
590:             abort(404)
591:         except ReportWebError as exc:
592:             return _report_error(503, report_date=trading_date, exc=exc)
593:         except HTTPException:
594:             raise
595:         except Exception as exc:
596:             return _report_error(500, report_date=trading_date, exc=exc)
597: 
598:     def weekly_report_page(week_id):
599:         if observation_mode:
600:             abort(404)
601:         if not isinstance(week_id, str) or re.fullmatch(r"[0-9]{4}-W[0-9]{2}", week_id) is None:
602:             abort(404)
603:         return _report_error(503)
604: 
605:     app.add_url_rule("/reports", "reports_page", reports_page)
606:     app.add_url_rule("/reports/<report_date>", "report_page", report_page)
607:     app.add_url_rule(
608:         "/reports/<report_date>/preview", "report_preview", legacy_report_redirect
609:     )
610:     app.add_url_rule(
611:         "/reports/<report_date>/download", "report_download", legacy_report_redirect
612:     )
613:     app.add_url_rule(
614:         "/reports/sample/download", "sample_report_download", sample_report_download
615:     )
616:     app.add_url_rule(
617:         "/reports/trading-day/<trading_date>",
618:         "trading_day_report_page",
619:         trading_day_report_page,
620:     )
621:     app.add_url_rule(
622:         "/reports/<trading_date>/post-close",
623:         "post_close_report_page",
624:         post_close_report_page,
625:     )
626:     app.add_url_rule(
627:         "/reports/<trading_date>/pre-market",
628:         "pre_market_report_page",
629:         pre_market_report_page,
630:     )
631:     app.add_url_rule(
632:         "/reports/us",
633:         "us_reports_page",
634:         us_reports_page,
635:     )
636:     app.add_url_rule("/us", "us_dashboard_page", us_dashboard_page)
637:     app.add_url_rule("/us/market", "us_market_page", us_market_page)
638:     app.add_url_rule("/us/industries", "us_industries_page", us_industries_page)
639:     app.add_url_rule(
640:         "/reports/us/<trading_date>/post-close",
641:         "us_post_close_report_page",
642:         us_post_close_report_page,
643:     )
644:     app.add_url_rule(
645:         "/reports/us/<trading_date>/pre-market",
646:         "us_pre_market_report_page",
647:         us_pre_market_report_page,
648:     )
649:     app.add_url_rule(
650:         "/reports/us/trading-day/<trading_date>",
651:         "us_trading_day_report_page",
652:         us_trading_day_report_page,
653:     )
654:     app.add_url_rule(
655:         "/reports/weekly/<week_id>", "weekly_report_page", weekly_report_page
656:     )

CURRENT SUPPORTING SOURCE stock_papi/services/us_presentation.py
1: """US presentation helpers - centralized view-model mapping for US pages."""
2: from __future__ import annotations
3: from typing import Any
4: 
5: MARKET_OBSERVATION_LABELS = {
6:     "advancing_count": "上漲家數",
7:     "declining_count": "下跌家數",
8:     "unchanged_count": "平盤家數",
9:     "ma20_breadth_pct": "站上 MA20 比例",
10:     "ma60_breadth_pct": "站上 MA60 比例",
11:     "new_high_20d_count": "20 日新高家數",
12:     "new_low_20d_count": "20 日新低家數",
13:     "realized_volatility_20d_pct": "20 日已實現波動率",
14:     "return_1d_pct": "單日報酬",
15:     "return_5d_pct": "5 日報酬",
16:     "return_20d_pct": "20 日報酬",
17:     "return_60d_pct": "60 日報酬",
18:     "median_volume_ratio": "中位量比",
19:     "median_institution_net_ratio_pct": "法人淨流中位",
20:     "risk_state": "風險狀態",
21:     "market_state": "市場狀態",
22: }
23: 
24: RISK_STATE_LABELS = {
25:     "normal": "一般",
26:     "cautious": "謹慎",
27:     "elevated": "升高",
28:     "defensive": "防守",
29: }
30: 
31: INDUSTRY_FIELD_LABELS = {
32:     "relative_return_5d_pct": "5 日相對大盤",
33:     "coverage": "資料覆蓋率",
34:     "available_count": "有效樣本",
35:     "component_count": "成分數",
36:     "rank": "排名",
37:     "name": "產業",
38: }
39: 
40: VALIDATION_GATE_LABELS = {
41:     "ranking": "模型排名",
42:     "calibration": "模型校準",
43:     "quality": "品質 Gate",
44:     "transaction_value": "交易價值驗證",
45:     "promotion": "模型 Promotion",
46: }
47: 
48: GATE_UNAVAILABLE_TEXT = "尚未提供驗證資料"
49: GATE_BLOCKED_TEXT = "暫不發布"
50: 
51: 
52: def format_market_value(key: str, value: Any) -> str:
53:     if value is None or (isinstance(value, str) and value.strip().lower() in {"none", "null", ""}):
54:         return "尚無已驗證資料"
55:     if isinstance(value, bool):
56:         return "尚無已驗證資料"
57:     if key == "risk_state" and isinstance(value, str):
58:         return RISK_STATE_LABELS.get(value, value)
59:     if key == "median_institution_net_ratio_pct" and isinstance(value, (int, float)):
60:         return f"{value:+.2f}%"
61:     if key.endswith("_pct") and isinstance(value, (int, float)):
62:         return f"{value:+.2f}%" if "return" in key else f"{value:.1f}%"
63:     if key == "median_volume_ratio" and isinstance(value, (int, float)):
64:         return f"{value:.2f}"
65:     if isinstance(value, int):
66:         return str(value)
67:     if isinstance(value, float):
68:         return f"{value:.2f}"
69:     return str(value)
70: 
71: 
72: def localize_us_key_event(event: dict[str, Any]) -> dict[str, Any]:
73:     """Translate machine risk-state text without changing verified event data."""
74:     if not isinstance(event, dict):
75:         return event
76:     localized = dict(event)
77:     for field in ("headline", "description"):
78:         value = localized.get(field)
79:         if not isinstance(value, str):
80:             continue
81:         for separator in ("：", ":"):
82:             prefix = f"市場風險狀態{separator}"
83:             if value.startswith(prefix):
84:                 raw_state = value[len(prefix):].strip()
85:                 localized[field] = f"市場風險狀態：{RISK_STATE_LABELS.get(raw_state, raw_state)}"
86:                 break
87:     return localized
88: 
89: 
90: def build_us_market_observation_view(market_section: dict) -> list[dict[str, Any]]:
91:     if not isinstance(market_section, dict) or market_section.get("status") != "available":
92:         return []
93:     data = market_section.get("data") or {}
94:     if not isinstance(data, dict):
95:         return []
96:     rows = []
97:     for key, value in data.items():
98:         if isinstance(value, (dict, list)) and not isinstance(value, str):
99:             continue
100:         label = MARKET_OBSERVATION_LABELS.get(key, key)
101:         formatted = format_market_value(key, value)
102:         rows.append({"key": key, "label": label, "value": value, "formatted": formatted, "available": formatted != "尚無已驗證資料"})
103:     # order by label priority
104:     order = list(MARKET_OBSERVATION_LABELS.keys())
105:     rows.sort(key=lambda x: order.index(x["key"]) if x["key"] in order else 999)
106:     return rows
107: 
108: 
109: def build_us_industries_view(industries_section: dict) -> list[dict[str, Any]]:
110:     if not isinstance(industries_section, dict) or industries_section.get("status") != "available":
111:         return []
112:     data = industries_section.get("data") or {}
113:     ranking = data.get("ranking")
114:     if not isinstance(ranking, list):
115:         return []
116:     result = []
117:     for item in ranking:
118:         if not isinstance(item, dict):
119:             continue
120:         name = item.get("name") or "未命名"
121:         result.append({
122:             "name": name,
123:             "rank": item.get("rank"),
124:             "relative_return_5d_pct": item.get("relative_return_5d_pct"),
125:             "coverage": item.get("coverage"),
126:             "available_count": item.get("available_count"),
127:             "component_count": item.get("component_count"),
128:         })
129:     return result
130: 
131: 
132: def format_percent(value: Any) -> str:
133:     if isinstance(value, bool) or not isinstance(value, (int, float)):
134:         return "尚無已驗證資料"
135:     return f"{value:+.2f}%"
136: 
137: 
138: def format_coverage(value: Any) -> str:
139:     if isinstance(value, bool) or not isinstance(value, (int, float)):
140:         return "尚無已驗證資料"
141:     return f"{value*100:.0f}%"
142: 
143: 
144: def validation_gate_display(gate_name: str, gate_value: str) -> tuple[str, str]:
145:     label = VALIDATION_GATE_LABELS.get(gate_name, gate_name)
146:     if gate_value == "BLOCKED":
147:         return label, GATE_BLOCKED_TEXT
148:     if gate_value == "UNAVAILABLE":
149:         return label, GATE_UNAVAILABLE_TEXT
150:     return label, gate_value
151: 
152: 
153: def stock_display_name(name: str, symbol: str) -> str:
154:     n = (name or "").strip()
155:     s = (symbol or "").strip().upper()
156:     if not n or n.upper() == s:
157:         return s
158:     return f"{n} · {s}"
159: 
160: 
161: def latest_post_close_item(reports: Any) -> dict[str, Any] | None:
162:     """Return the post_close entry with the newest session dates.
163: 
164:     Report index order reflects publication recency (newest first), which a
165:     late backfill can reorder away from session recency. Select by
166:     (applicable_trading_date, source_market_date) so pages always render the
167:     newest verified session, matching the freshness loader's max() semantics.
168:     """
169:     best: dict[str, Any] | None = None
170:     best_key: tuple[str, str] | None = None
171:     if not isinstance(reports, list):
172:         return None
173:     for item in reports:
174:         if not isinstance(item, dict) or item.get("report_type") != "post_close":
175:             continue
176:         applicable = item.get("applicable_trading_date") or item.get("source_market_date")
177:         source = item.get("source_market_date") or applicable
178:         if not isinstance(applicable, str) or not isinstance(source, str):
179:             continue
180:         key = (applicable, source)
181:         if best_key is None or key > best_key:
182:             best_key = key
183:             best = item
184:     return best
