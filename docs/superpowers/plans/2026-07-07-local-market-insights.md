# Local Market Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每晚在 D 槽建立產業地圖、上市／上櫃 MOPS、ETF 持倉與台美日供應鏈快照，09:35 安全上傳，Cloud Run 只讀取單一驗證後的壓縮物件。

**Architecture:** 新增輕量 `market_insights.py`，純函式負責正規化資料與建立文件；`local_quant.py` 在台股批次開始前產生內容定址快照。既有上傳器先上傳物件再更新 `latest-insights.json`，Cloud Run 驗證大小、SHA、schema 與日期後提供 `/market-map`。

**Tech Stack:** Python 3.10 stdlib、requests、既有 yfinance、Flask/Jinja、PowerShell、unittest

## Global Constraints

- 所有本地資料只寫入 `D:\StockPapiData`。
- 只在 02:30–09:20 領取新資料，09:30 後不得補跑。
- Cloud Run 不執行全市場、ETF 或 MOPS 批次。
- 不新增套件；來源失敗保留上一版快照。
- 發布順序固定為 object → latest pointer，所有路徑與 SHA 必須驗證。

---

### Task 1: 正規化市場洞察資料

**Files:**
- Create: `market_insights.py`
- Create: `tests/test_market_insights.py`

**Interfaces:**
- Consumes: TWSE/TPEx JSON lists、yfinance holdings DataFrame-like rows、股票 artifact 摘要。
- Produces: `parse_mops_items(items, source, limit=100) -> list[dict]`、`normalize_etf_holdings(rows, etf) -> dict`、`build_supply_chains(metrics) -> list[dict]`。

- [ ] 先寫測試，驗證民國日期、欄位差異、去重、ETF 權重與供應鏈節點。
- [ ] 執行 `python -m unittest tests.test_market_insights -v`，確認缺少模組而失敗。
- [ ] 以 stdlib 實作正規化與固定供應鏈角色目錄。
- [ ] 重跑測試，確認通過。

### Task 2: D 槽快照與排程

**Files:**
- Modify: `local_quant.py`
- Modify: `scripts/upload_local_quant.ps1`
- Modify: `tests/test_local_quant_publish.py`
- Modify: `tests/test_local_quant_task.py`

**Interfaces:**
- Produces: `publish_market_insights(root, document, generated_at) -> Path`，指向 `publish/quant/v1/latest-insights.json`。
- Snapshot document: `schema_version=1`、`as_of`、`industries`、`mops`、`etfs`、`supply_chains`、`sources`。

- [ ] 寫失敗測試，驗證 gzip object、SHA、原子 latest 與上傳順序。
- [ ] 實作每日一次產生洞察；失敗只記錄 `insights_error`，不得中止 TW/US 股票批次。
- [ ] 擴充上傳器，只接受 `objects/<sha>.json.gz` 與固定 `latest-insights.json`。
- [ ] 重跑 local quant 測試。

### Task 3: Cloud Run 驗證讀取與市場地圖頁

**Files:**
- Modify: `app.py`
- Create: `templates/market_map.html`
- Modify: `templates/base.html`
- Modify: `static/app.css`
- Modify: `tests/test_prediction_pipeline.py`
- Modify: `tests/test_web_product.py`

**Interfaces:**
- Produces: `fetch_market_insights(today=None) -> dict | None`、`GET /api/market-insights`、`GET /market-map`。

- [ ] 寫失敗測試，拒絕錯誤 SHA、過大 gzip、未來日期與未知 schema。
- [ ] 實作有界下載、解壓與快取；缺少快照時回傳既有產業卡與靜態供應鏈，不即時抓 MOPS/ETF。
- [ ] 建立響應式地圖、MOPS、ETF 與台美日供應鏈區塊。
- [ ] 重跑 Web 與 pipeline 測試。

### Task 4: 驗證與發布

**Files:**
- Modify: `README.md`

**Interfaces:** 無新增執行介面。

- [ ] 文件化來源、快照格式、回退與資料限制。
- [ ] 執行完整 unittest、py_compile、JavaScript 檢查、`git diff --check` 與 ShellWard。
- [ ] 僅提交本計畫相關檔案，保留既有未追蹤檔。
- [ ] 推送 main、部署 Cloud Run，驗證 Secret Manager 引用、`/health`、`/market-map` 與 `/api/market-insights`。
