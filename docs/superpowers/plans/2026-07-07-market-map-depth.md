# Stock Papi Market Map Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用現有本地量化 artifact 為產業地圖加入關鍵指標、熱力圖、籌碼摘要與更完整的產業／供應鏈公司卡。

**Architecture:** `local_quant.py` 只多讀取 artifact 已存在的數值；`market_insights.py` 以純函式彙總並輸出向後相容欄位；Jinja 與 CSS 負責呈現，不加入前端圖表套件。Cloud Run 仍只讀 GCS 快照。

**Tech Stack:** Python 3.10、Flask/Jinja、Vanilla CSS、unittest。

## Global Constraints

- 不增加 Cloud Run 網路抓取或模組層重運算。
- 不新增依賴、資料庫或網站收藏狀態。
- 缺資料時省略或降級，不推測投信、大戶與商業契約。
- 維持 `market-insights` schema version 1 向後相容。

---

### Task 1: 產業聚合資料

**Files:**
- Modify: `tests/test_market_insights.py`
- Modify: `market_insights.py`
- Modify: `local_quant.py`

**Interfaces:**
- Consumes: `build_industries(theme_map, metrics, limit=5)` 與 `_read_insights_metric(root, symbol)`。
- Produces: 每個 industry 的 `average_prob`、`average_return`、`bullish_ratio`、`coverage`、`heat_tone`、`heat_size`、`chips`，以及 leader 的價格、漲跌與訊號。

- [x] **Step 1: Write the failing test**

新增測試，輸入兩檔含 `prob`、`return_1d`、`inst_ratio`、`margin_change`、`volume_ratio` 的 metrics，斷言平均值、排序、色階、大小與三項籌碼分數。

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_market_insights -v`
Expected: FAIL，缺少新增聚合欄位。

- [x] **Step 3: Write minimal implementation**

在 `build_industries` 直接計算平均與比例；在 `_read_insights_metric` 使用 `latest.get()` 讀取 `Close`、`RET_1`、`INST_NET_RATIO`、`MARGIN_CHG`、`SHORT_CHG`、`VOL_RATIO`，缺值回傳 `None`。

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_market_insights -v`
Expected: PASS。

### Task 2: 產業地圖頁面

**Files:**
- Modify: `tests/test_web_product.py`
- Modify: `templates/market_map.html`
- Modify: `static/app.css`

**Interfaces:**
- Consumes: Task 1 的 industry 欄位及既有 `supply_chains`。
- Produces: 產業關鍵指標、CSS 熱力圖、籌碼列、產業公司卡與強化供應鏈節點。

- [x] **Step 1: Write the failing test**

擴充 route fixture，斷言頁面包含「產業關鍵指標」、「產業漲跌熱力圖」、「籌碼訊號」、「產業角色分群」與 `+1.8%`。

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_web_product.WebProductTests.test_market_map_renders_industries_mops_etfs_and_supply_chains -v`
Expected: FAIL，頁面尚無新區塊。

- [x] **Step 3: Write minimal implementation**

以 Jinja 迴圈呈現四張摘要卡、熱力圖、每產業籌碼進度與公司卡；供應鏈節點補上漲跌與趨勢。用 CSS Grid 與既有色票完成響應式版面。

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_web_product.WebProductTests.test_market_map_renders_industries_mops_etfs_and_supply_chains -v`
Expected: PASS。

### Task 3: 驗證與發布

**Files:**
- Modify: `README.md` only if the visible feature list is stale.

- [x] **Step 1: Run full verification**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS。

Run: `python -m py_compile app.py local_quant.py market_insights.py line_state.py`
Expected: exit 0。

Run: `node --check static/app.js` and `git diff --check`
Expected: exit 0。

- [x] **Step 2: Commit, push and deploy**

只 stage 本計畫列出的檔案；推送 `main`，部署既有 `line-stock-bot` Cloud Run 服務，最後確認 `/health` 與 `/market-map` 回傳 200。

### Task 4: 無資料恢復與五檔下限

**Files:**
- Modify: `scripts/upload_local_quant.ps1`
- Modify: `app.py`
- Modify: `local_quant.py`
- Modify: `market_insights.py`
- Modify: `tests/test_local_quant_task.py`
- Modify: `tests/test_web_product.py`
- Modify: `tests/test_market_insights.py`

**Interfaces:**
- Consumes: `latest-insights.json`、`industry_map`、`build_industries()`。
- Produces: 洞察優先上傳，以及每個正式主題至少五張公司卡的降級與正式快照。

- [x] **Step 1: Write failing tests**

斷言 uploader 的 insights 區塊位於市場物件迴圈之前；斷言 fallback 排除 `全市場`／`ETF專區` 且每個產業有五位 leaders；斷言缺量化值的候選不計入 `coverage`。

- [x] **Step 2: Verify failures**

Run: `python -m unittest tests.test_local_quant_task tests.test_market_insights tests.test_web_product -v`
Expected: FAIL，指出上傳順序、fallback 分類與候選覆蓋尚未符合。

- [x] **Step 3: Implement minimal root-cause fixes**

把 uploader 的 insights 驗證與上傳移到市場迴圈前；用 `build_industries(industry_map, fallback_metrics)` 建立降級資料；正式本地文件先為主題代碼建立名稱與空值，再以有效 artifact 覆蓋；補足半導體製造候選。

- [ ] **Step 4: Verify and publish**

Run full unittest、Python compile、Node syntax、`git diff --check`；只提交相關檔案，推送並部署。若在批次時段外，只用既有 D 槽 artifact 離線補建洞察，不抓市場資料。
