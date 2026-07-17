# ABSORB 多頁資訊架構與報告可靠性設計

日期：2026-07-18

## 目標

- 將首頁縮成「今日市場」入口，把市場、產業、個股、報告、Ask ABSORB 與學習內容放到可直接連結的獨立路由。
- 修復 Observation 報告 500，並讓報告 schema 錯誤 fail closed，顯示可追查但不洩漏內部資訊的錯誤頁。
- 保持 Observation-only、GCS 驗證、Cloud Run cold-start 與 LINE 安全邊界不變。

## 已證實根因

Production 的 `/reports/trading-day/2026-07-17` 同時載入盤後與盤前 metadata，卻共用只支援盤後平面 content 的 Jinja 模板。盤前 content 是 `{core, base_metadata_sha256, overnight_overlay}`，沒有 `market_observation`，因此模板存取該欄位時拋出 `UndefinedError` 並回傳 500。

## 報告架構

- 新增型別化、只讀的 report view model；route 依 `report_type` 正規化已驗證 metadata，模板不得讀取原始 metadata。
- canonical routes：
  - `/reports/<date>/post-close`
  - `/reports/<date>/pre-market`
- `/reports/trading-day/<date>` 保留為相容入口，顯示當日可用報告索引，不再混合渲染不同 schema。
- `/reports`、首頁卡片與 LINE URL 產生器一律使用 canonical route；本任務不送出 LINE 訊息。
- 不合法日期或不存在的報告回 404；index／metadata 驗證失敗回 503；未預期錯誤以 route-level exception log 記錄 correlation ID，回傳專用 500 頁。頁面只顯示 correlation ID，不顯示 bucket、object path、stack trace 或 service 細節。

## 多頁資訊架構

- `/`、`/dashboard`：今日市場摘要、雙報告卡、3 至 5 個焦點、四個主要入口與 AI 研究狀態。
- `/market`：市場實況、今日焦點、資料品質與時間。
- `/industries`：產業熱圖與產業觀察。
- `/stocks`：個股搜尋、異常事件、ETF 觀察。
- `/reports`：報告歸檔。
- `/ask`：既有 Ask ABSORB 對話介面。
- `/learn`：既有術語與方法限制。
- `/market-map` 302 轉址 `/industries`；`/stock/<code>` 保持不變。
- 桌面與手機導覽改用真正 route，並以 endpoint 標示 active state。舊 hash 只用固定 allowlist 轉到新 route，禁止任意 redirect。

## 資料與前端邊界

- 所有頁面重用同一個已驗證 Observation dashboard snapshot loader；不新增 request-time 模型運算或重型 import。
- Server-rendered 首屏提供可讀內容；既有 `/api/dashboard` 只負責漸進增強。
- 沿用 `static/app.js` 與 `static/app.css`，以頁面上存在的容器決定初始化，不建立新 bundle。
- 每頁只有一個 H1；canonical URL、導覽 active state、空資料與錯誤狀態均由模板明確呈現。

## 驗證與發布

- 先用脫敏但保留 Production schema 形狀的 fixture 重現 500，再實作修復。
- 驗證 focused tests、完整 Python suite、PowerShell parser、secret／路徑／XSS 邊界及 import cold-start。
- 本機以 1440、1024、768、390 px 驗證主要頁面；no-traffic Cloud Run revision 使用真實 GCS 驗證報告、路由、OAuth 與 Observation-only 狀態。
- 只有 no-traffic 所有 gate 通過才切 100% traffic；失敗時流量回到先前 revision，GCS pointers 不變。

## 非目標

- 不修改模型、回測公式、Prediction flags、GCS schema 或發布順序。
- 不建立產業 detail route、不新增 sitemap、不大規模改寫 CSS／JavaScript。
- 不發送 LINE push、broadcast 或任何主動對外訊息。
