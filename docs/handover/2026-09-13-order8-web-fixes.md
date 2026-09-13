# 交接：ORDER 8 介面修復（研究版報告排版／市場實況預測線／版面順序與視覺化）

對象：負責審核與部署的人（Codex）。
分支：`claude/youthful-brown-j04373`。
寫這份文件的原因：**這一輪的變更沒有在我的工作環境跑過測試套件**（環境缺依賴，
見第 4 節），所以交接必須把「我驗了什麼」與「誰補上了剩下那一段」分開寫清楚，
再決定上不上線。後來 PR #84 的 CI 在 Python 3.10／3.11 上各跑了一次完整的
`scripts/check_ci.sh`，兩個都綠 —— 但那是 CI 跑的，不是我跑的。

---

## 1. 這次修的三個問題

### 1-1 研究版報告整份排版崩壞（最嚴重）

`.report-track` 在 CSS 裡同時是兩個不同的元件：

- ORDER 5：研究版報告三軌閱讀的 **tabpanel 容器**
  （`templates/reports/post_close_professional.html` 的三個
  `<div class="report-track" role="tabpanel">`）
- ORDER 7：報告索引卡上的 **一行摘要**
  （`templates/reports.html` 的「研究版 · N／M 章有內容」），宣告 `display:flex`

摘要那條規則在 `static/components.css` 裡出現得比較晚，所以它同時套在
tabpanel 上：整個分頁變成橫向 flex 容器，九個章節被擠成九個並排的窄欄，
中文標題一個字換一行，數值被裁掉（委託人截圖即此狀態）。

**修法**：摘要列改名 `.report-track-meta`；tabpanel 維持 `.report-track`，
且不再有任何 `display` 宣告（`[hidden]` 的收合與 `@media print` 的展開除外）。

### 1-2 市場實況（`/market`）的 AI 五日情境線不見了

那張圖一直是用 `createPriceChart(..., { predictionMarker: true })` 畫的，
但 `market_page()` 只把 `observation` 傳進模板，`#market-index-chart-data`
裡沒有 `prediction`／`band`，`app.js` 於是只畫得出 K 線與均價線。
今日市場（`dashboard_page()`）有做這件事 —— 同一份已驗證產物因此只有
一個入口看得到。

**修法**：路由補上 `prediction_for(prediction_snapshot("TW"), "TW", "TAIEX", …)`，
模板補上預測線與誤差區間的圖例，並依 DESIGN.md §18 把估計的摘要數字
獨立成一張虛線卡（機率／預測價／預測變動／目標交易日／誤差區間，
加上「它是什麼、不是什麼、不保證什麼」三句式）。
沒有已驗證產物時：K 線上不補線，摘要卡寫「尚未發布」。

### 1-3 版面順序與視覺化（委託人裁示）

- 台股與美股首頁的「最新更新」都移到證據區之後。它是報告與觀察的**入口清單**，
  不是今天的市場本身；佔第一屏會把指數走勢與廣度推出畫面。入口沒有刪除，
  兩條報告軌道與「重要性優先、不是時間倒序」的排序規則都保留。
- 期間報酬（今日市場 + 市場實況）改成**共用刻度、零線置中的發散長條**。
- 市場實況新增三組視覺化：市場廣度堆疊長條、三個附刻度說明的量表、
  20 日新高／新低對比長條。全部只是既有已驗證數值的第二種讀法 ——
  沒有新數字、沒有平滑、沒有推估，缺值仍然是缺值。
- 市場實況拿掉 `data-market-summary`：`app.js` 的 `renderDashboard()` 會把
  伺服器端已白話化的區塊換成「站上 MA20」「20 日已實現波動」這類術語卡，
  同一頁因此有兩種長相，而且後到的那一種比較差。
  `data-dashboard-endpoint` 保留，因為錯誤橫幅仍然要在 API 不可用時出現。

---

## 2. 改了哪些檔案

| 檔案 | 內容 |
|---|---|
| `static/components.css` | `.report-track` → `.report-track-meta`；新增市場實況視覺化元件；`.return-grid` 整組退場（已無使用者） |
| `static/app.css` | 產生檔，由 `python3 scripts/build_css.py` 重建 |
| `templates/reports.html` | 索引卡摘要列改用 `.report-track-meta` |
| `stock_papi/web/routes/market.py` | `market_page()` 取已驗證預測並傳給模板 |
| `templates/market.html` | 預測線圖例、模型估計區塊、三組視覺化、移除 `data-market-summary` |
| `templates/dashboard.html` | 「最新更新」下移、期間報酬改長條 |
| `templates/us_dashboard.html` | 「最新更新」下移（與台股同一條規則） |
| `tests/test_web_product.py` | 三個新回歸測試；既有圖例計數測試改為只數 K 線圖自己的圖例 |
| `DESIGN.md` | §18 同一份估計在每個入口都要畫；§23 密度目標；§29 版面容器與內容元件不得共用類名 |

---

## 3. 我驗了什麼（可重現）

沙箱裡沒有專案依賴（`flask` 等），所以改用離線的方式驗：

1. **模板離線 render**：用 `jinja2` 直接載入 `templates/`，餵 repo 自己的
   fixture（`observation_dashboard()` 的同一份資料 + `prediction_for()` 的
   真實輸出），render `market.html`／`dashboard.html`／`us_dashboard.html`／
   `reports/post_close_professional.html`，全部無例外。
2. **HTML 結構**：用 `html.parser` 檢查標籤配對，四個頁面都沒有未閉合或錯位。
3. **Chromium 截圖**：1440px 與 390px（用 iframe 取得真實 390 視寬）各看一次；
   390px 下 `scrollWidth == clientWidth`，沒有水平溢出。
   K 線區塊在截圖裡是空白的 —— 沙箱擋掉 unpkg CDN，**不是**程式問題；
   預測線改以圖表實際吃的 JSON payload 驗證（`prediction`／`band` 兩個欄位）。
4. **排版崩壞的重現與修復對照**：用 `git show HEAD:static/app.css` 的舊版 CSS
   重現委託人截圖裡的九欄窄柱，再用新版 CSS 確認章節恢復成整頁堆疊。
5. **既有測試裡的掃描式不變量**逐條在本機重跑並通過：
   缺值不帶單位、方向元素必帶正負號或方向詞、術語只能出現在 `.term-tag`
   或收合區、type scale 封閉集合、圓角封閉集合、中文行高下限、
   沒有未定義的 CSS 變數、hex 字面值不超過 token 數、`.positive,`／`.negative,`
   各只宣告一次、`app.css` 與六個原始檔同步。

---

## 4. 測試套件：本機沒跑，CI 跑了

**我沒有在工作環境跑 `./scripts/check_ci.sh`** —— 那個環境沒有安裝專案依賴，
所以整個 `unittest` 套件我一次都沒有執行過。這是這份交接最初要請你補的那一段。

**後來 PR #84 的 CI 補上了這一段**：`.github/workflows/ci.yml` 在
Python 3.10 與 3.11 上各跑了一次 `scripts/check_ci.sh`（也就是完整的
CI 測試範圍），head commit `c0ca906` 兩個都 success。

所以這一項現在不是未知數，但它是**CI 跑的、不是我跑的**；如果你要在本機
再確認一次：

```bash
pip install -r requirements.txt -r requirements-dev.txt
./scripts/check_ci.sh
```

無論看 CI 或自己跑，特別留意這幾個模組（改動直接命中它們）：

- `tests/test_web_product.py`：新增的三個 `test_order8_*`，以及被我改過的
  `test_order4_market_chart_declares_its_own_legend_and_limits`
  （圖例計數改為只數 `.chart-legend` 區塊內的 `legend-swatch`）
- `tests/test_observation_public_surfaces.py`：首頁區塊名稱與順序
- `tests/test_reports_template.py`：`report-track-badge` 仍在，只有外層的
  `<p>` 改名
- `tests/test_us_presentation_regression.py`：美股模板字串

如果 `test_order8_market_page_draws_the_same_verified_prediction_as_today`
紅了，先看 `prediction_for()` 是不是因為 fixture 的 `as_of` 不一致被擋掉
（那個函式對日期與自洽性是 fail-closed 的）。

---

## 5. 審核重點（最容易出錯的三處）

1. **`.report-track` 不可以再有 `display`。** 這是這次崩壞的根因。
   `tests/test_web_product.py::test_order8_report_track_panel_is_never_turned_into_a_row`
   會掃 CSS，任何人把 `display` 加回精確的 `.report-track` 選擇器就會紅。
2. **缺值語意**：新的長條與量表在缺值時不畫、不補 0，文字改為
   `.value-unavailable`。請用「某個欄位缺值」的快照看一次 `/market`。
3. **預測的視覺分區**：`/market` 的估計必須在虛線卡內，圖例要逐條標明
   哪一條是估計。線上如果當天沒有已驗證預測，應該看到「尚未發布」而不是
   空白卡或補值。

---

## 6. 上線

照 `docs/release-web.md`：合併進 `main` 之後 `.github/workflows/deploy.yml`
會自動建候選 revision → 驗環境變數 → 煙霧測試 → 切 100% 流量，
失敗自動回滾。這次的變更只動介面層（模板／CSS／一個路由），
沒有碰資料管線與發布旗標，所以**不需要**走
`deploy_observation_production.ps1` 的 LKG 手動路徑。

上線後請人工看三個畫面（自動煙霧測試只驗 HTTP 200，看不出排版）：

- `/reports/<交易日>/post-close#track-research` —— 章節是整頁堆疊，不是並排窄欄
- `/market` —— K 線上有虛線的五日情境（當天有已驗證預測時），圖例有「五日情境」
- `/` 與 `/us` —— 第一屏是「今天怎麼了」＋指數走勢，「最新更新」在證據之後

## 7. 回滾

只改介面層，回滾等同把這個 commit revert 掉再讓 workflow 重跑；
或依 `docs/release-web.md` 把 Cloud Run 流量切回前一個 revision。

## 8. 已知未做

- `app.js` 的 `renderDashboard()` 裡那段 `[data-market-summary]` 渲染已經沒有
  任何模板在用，但沒有刪除：`tests/test_observation_public_surfaces.py`
  的 `test_browser_renderer_has_timeout_and_no_prediction_rendering` 要求
  `market_observation` 出現在該函式內，清理要連同測試一起改，
  不適合夾在這次的修復裡。
- 同一支函式裡的 `data-market-hero`、`data-daily-focus`、`data-market-heatmap`
  等 hook 在模板裡也已無對應元素（本次之前就是如此）。
