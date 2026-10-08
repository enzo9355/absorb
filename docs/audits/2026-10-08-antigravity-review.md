# 獨立資深代碼審查報告

**審查範圍**：`BASE 90535c104d2e55c69e1992bcd1e4b06e07451036` 至 `HEAD fa1cf7c8cd02b5dfed092ded5ad5f74eabe9978d`  
**分支**：`codex/web-review-fixes-20261007`  
**審查性質**：靜態源碼獨立審查（Read-Only，未重跑測試、未檢視截圖、無執行任何工具或指令）  
**評分**：**7.0 / 10**（評分依據見文末）

---

## (1) 整體判定與上線準備度 (Overall Verdict and Readiness)

**整體判定**：**條件式暫緩上線 (Conditionally Blocked / Changes Requested)**

### 上線準備度評估：
1. **防護邊界與合約保持良好**：本提交嚴格遵守現有安全規則，未更動或削弱私有資料存取控制、Prompt Injection 防護、交易計畫試用守門（Trade Plan Beta Guard）以及不可變產物雜湊比對（SHA-256 Binding）。
2. **存在引入性缺陷與例外崩潰風險 (P1/P2)**：
   - 路由中針對 `dict.get()` 回傳 `None` 進行串列迭代，在特定報告或摘要欄位為 JSON `null` 時將引發伺服器 500 `TypeError`。
   - ASKsorb 日期回答機制關鍵字範圍過寬，會攔截使用者帶有「最新資料」或「更新時間」實質內容提問。
   - 多標的查詢時強制截斷僅回答第一檔標的，且單股新鮮度推算存在 `market` 遺失即判定為不可用的脆弱點。
3. **背景維運阻斷事項持續存在**：美股盤後因 SUNC 缺收盤價及 Nasdaq 備援無效而觸發發布門檻，研究候選亦未審核。雖然這是既有維運限制，但結合上述程式碼缺陷，本分支尚未達到無條件部署正式站之水準。必須先修復 P1 與 P2 缺陷後方可進入預發佈測試。

---

## (2) 源碼具體優點 (Strengths Grounded in Source)

1. **資料新鮮度合約設計嚴謹 (Fail-Closed Freshness)**：
   在 [`stock_papi/web/routes/system.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/system.py#L54-L100) 的 [`classify_data_freshness`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/system.py#L54) 中，透過交易日曆 [`TradingCalendarSet`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/system.py#L8) 精確計算跨週末與國定假日的下一個交易日 (`updating_boundary`)，避免了單純以日曆天計算過期（Stale）的誤判，且在任何例外或格式錯誤時維持 Fail-Closed（回傳 `unavailable`）。
2. **報告語意與免責聲明真實性校正**：
   在 [`templates/reports/post_close_professional.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/reports/post_close_professional.html#L149-L156) 中，修正了將非正面事件一律判定為「風險」的瑕疵，將未分類項目調整為「觀察」；並在法規免責宣告中新增條件判斷（僅在 `quant_sec.status == 'available'` 時才宣稱採用量化回歸研究模型），杜絕虛假揭露。
3. **避免快取資料就地篡改 (No In-Place Mutation)**：
   在 [`stock_papi/web/routes/reports.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/reports.py#L463-L468) 的 [`_history_reports`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/reports.py#L463) 與 [`stock_papi/web/routes/dashboard.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/dashboard.py#L38-L44) 中，對快取物件建立淺拷貝副本解構 `{**row, ...}` 處理呈現用語，不再直接修改全域快取的報告與快照物件。
4. **原生摺疊控制與無障礙觸控區改善**：
   在 [`templates/reports.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/reports.html#L50-L67) 與 [`templates/events.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/events.html#L25) 採用 HTML5 原生 `<details>`/`<summary>` 取代複雜 JS 控制；在 [`static/app.css`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/static/app.css#L1480-L1495) 中落實主要點擊目標 `min-height: 44px` 與 `min-width: 0` 容器自適應，解決行動端排版溢出問題。

---

## (3) 具體缺陷清單 (Findings Ranked P0–P3)

### P0：無

---

### P1-1: 字典值為 `None` 時迭代引發 500 伺服器例外 (Server 500 TypeError Crash)
- **檔案與符號**：
  - [`stock_papi/web/routes/dashboard.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/dashboard.py#L38-L44)（`dashboard_page`）
  - [`stock_papi/web/routes/reports.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/reports.py#L463-L468)（[`_history_reports`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/reports.py#L463)）
- **觸發條件**：
  當儲存於 GCS 或快取中的快照／報告資料，其 `daily_focus` 或 `summary` 鍵存在但值為 JSON `null`（Python 對應為 `None`），例如新生成的空報告或舊格式報告。
- **預期行為**：
  若欄位值為 `None`，應安全視為空串列 `[]`，不應導致頁面渲染崩潰。
- **實際行為**：
  Python 字典之 `dict.get("summary", [])` 在鍵存在且值為 `None` 時，會回傳 `None` 而**非**預設值 `[]`。後續執行 `for text in None` 將直接拋出 `TypeError: 'NoneType' object is not iterable`，導致 `/dashboard`、`/reports`、`/reports/us` 噴出 HTTP 500 錯誤。
- **最小建議修復**：
  ```python
  # dashboard.py:
  snapshot = {**snapshot, "daily_focus": [localize_us_key_event({"headline": text})["headline"]
                                         for text in (snapshot.get("daily_focus") or [])]}
  daily_cards = {kind: {**item, "summary": [localize_us_key_event({"headline": text})["headline"]
                                           for text in (item.get("summary") or [])]} if item else None
                 for kind, item in daily_cards.items()}

  # reports.py:
  return [{**row, "summary": [localize_us_key_event({"headline": text})["headline"]
                              for text in (row.get("summary") or [])]}
          for row in rows ...]
  ```

---

### P1-2: 寬鬆關鍵字比對造成對話意圖攔截 (Conversational Intent Hijacking in ASKsorb)
- **檔案與符號**：
  [`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195-L2215)（[`_observation_date_answer`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195)）
- **觸發條件**：
  使用者提問實質行情問題，但句中帶有「最新資料」或「更新時間」作為時間修飾詞。例如：「根據台積電最新資料，目前價格與均線如何？」或「美股最新資料中標普表現如何？」。
- **預期行為**：
  系統應將提問傳送至量化觀察或 Grounded 生成引擎，回答實質的價格、均線、指數表現。
- **實際行為**：
  [`_observation_date_answer`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195) 執行於 [`_asksorb_grounded_answer`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2170) 之前，其條件 `if not any(term in question for term in ("資料日", "資料截至", "過期", "最新資料", "更新時間"))` 命中「最新資料」，直接攔截對話並回傳：「台積電（2330）最近一次已驗證資料日：...資料狀態：資料最新...」，使用者的價格與均線問題被完全吞沒。
- **最小建議修復**：
  收窄觸發模式，僅在使用者詢問主詞為「日期/時效」本身時觸發（如配合正規表達式或意圖檢查），或在問句包含「價格/均線/表現/走勢」等實質分析字眼時不單獨短路攔截。

---

### P2-1: 多標的日期查詢強制截斷，僅處理首檔標的 (Silent Drop of Subsequent Entities)
- **檔案與符號**：
  [`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2330-L2350)（[`_observation_conversation`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2200)）
- **觸發條件**：
  使用者在同一問句中查詢多檔標的（例如「2330 和 AAPL 最新資料日？」），且兩檔標的皆存在已發布觀察資料時。
- **預期行為**：
  系統應回傳兩檔標的之資料日與狀態，或交由支援多個案觀察的生成回答處理。
- **實際行為**：
  程式碼執行 `data = observations[0]`，只取第一檔標的建立 `stock_citations` 與呼叫 [`_observation_date_answer`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195)，導致第二檔標的被完全靜默忽略。
  *(註：作者新增的單元測試藉由 mock `fetch.side_effect = [None, us]` 刻意使第一檔失敗，掩蓋了此截斷邏輯。)*
- **最小建議修復**：
  若 `len(observations) > 1`，不可單獨由單標的模板短路回傳；應循環組合多標的日期狀態，或交由多標的 Grounding 提示詞生成回答。

---

### P2-2: 個股對話新鮮度檢查缺少市場 fallback (Fragile Market Context Fallback)
- **檔案與符號**：
  [`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2341)（[`_observation_conversation`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2200)）
- **觸發條件**：
  當 `build_stock_observation` 產出之字典中未包含頂層 `"market"` 鍵（如部分台股個股觀察格式僅在原始實體中帶有 market）。
- **預期行為**：
  呼叫 [`_observation_date_answer`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195) 時應 fallback 至 `entity["market"]` 或 `market_context`。
- **實際行為**：
  傳入 `market=data.get("market")` 為 `None`。[`create_data_freshness_loader`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/system.py#L136) 檢查 `market not in _MARKET_TIMEZONES`，直接回傳 `unavailable`，導致正常個股被誤判為「暫時無法核對新鮮度」。
- **最小建議修復**：
  ```python
  market = data.get("market") or entity.get("market") or market_context
  ```

---

### P2-3: 公司比較頁面對 `observation_as_of` 支援遺漏 (False Insufficient Data in Stock Compare)
- **檔案與符號**：
  [`templates/stock_compare.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/stock_compare.html#L6-L14)
- **觸發條件**：
  在 `/compare?symbols=...` 比較官方交易狀態標的或美股個股（美股回傳欄位為 `observation_as_of`）。
- **預期行為**：
  表格中的「資料日」與「資料品質」應正確呈現標的之觀察日期。
- **實際行為**：
  模板僅讀取 `row.get('as_of')`。若標的資料將日期儲存於 `observation_as_of`，將全部落入 `'資料不足'`。
- **最小建議修復**：
  將模板中 `row.get('as_of')` 替換為 `row.get('observation_as_of') or row.get('as_of')`。

---

### P3-1: 個股頁面情境繼承之市場覆寫不對稱 (Asymmetric Market Context Override)
- **檔案與符號**：
  [`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2271-L2275)
- **說明**：
  作者加入了 `explicit_us_market` 避免台股頁面繼承台股標的，但未加入對稱的 `explicit_tw_market`。若使用者在美股頁面（如 AAPL）提問「台股最新資料日？」，在實際環境（`search_stock_code` 未被 mock 為 None）下，仍可能錯誤繼承 AAPL 標的上下文。

### P3-2: 新鮮度無法驗證時個股報價標籤誤稱「最新收盤」 (Improper Quote Label Fallback)
- **檔案與符號**：
  [`templates/stock_detail.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/stock_detail.html#L25)
- **說明**：
  `quote_label` 邏輯為：`'最近可用收盤' if status in ['stale', 'updating'] else '最新收盤'`。當新鮮度無法核對 (`status == 'unavailable'`) 時，標籤仍顯示為「最新收盤」，違背保守誠實原則。應調整為 `status != 'current'` 即採用「最近可用收盤」。

### P3-3: 產業關係圖支援標的驗證僅採語法檢查 (Syntax-Only US Ticker Validation)
- **檔案與符號**：
  [`stock_papi/web/routes/research.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/research.py#L57-L60)（[`supported_symbol`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/research.py#L57)）
- **說明**：
  美股標的使用 `is_us_ticker(symbol)`（僅為 1-5 碼字母正則驗證），而非校驗是否屬於系統涵蓋之美股母體清單。若關係圖出現非收錄的美股代碼，仍會產生無效的個股頁面連結與加入比較按鈕。

### P3-4: 前端 `app.js` 型別安全隱患 (Potential TypeError on Non-String Focus Item)
- **檔案與符號**：
  [`static/app.js`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/static/app.js#L128)
- **說明**：
  在渲染每日焦點時直接調用 `text.replace(...)`。若 API 傳入之項目為 `null` 或非字串，會直接觸發 JS 例外並阻斷客戶端儀表板渲染。建議改為 `typeof text === 'string' ? text.replace(...) : String(text)`。

### P3-5: 跨模組架構耦合與命名洩漏 (Architectural Filter & Naming Coupling)
- **檔案與符號**：
  [`stock_papi/web/routes/research.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/research.py#L54-L56)、[`stock_papi/web/routes/dashboard.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/dashboard.py#L7)
- **說明**：
  全域模板過濾器 `research_time` 被註冊於子路由 `research.py` 內，卻被頂層模板 `dashboard.html` 使用，造成隱式初始化順序依賴；此外，台股儀表板與報告廣泛調用來自 `us_presentation` 的 `localize_us_key_event` 來處理中文標籤，存在職責倒置與模組邊界混淆。

---

## (4) 缺失的驗收證據 (Missing Acceptance Evidence)

1. **缺少全量測試集執行紀錄**：
   作者僅執行了 297 項特定選取之單元測試，未執行全儲存庫回歸測試，無法排除對批次排程、CLI 工具與整合流水線的潛在破壞。
2. **缺乏真實環境 / 外部依賴之整合執行驗證**：
   作者所有的手動驗證均基於 `visual_qa_server.py` 之合成資料與本機伺服器，缺乏與真實 GCS 物件存取、真實快取層以及實際生產環境資料格式對接的測試證據。
3. **單元測試存在以 Mock 規避真實缺陷的假陽性 (Tautological Mocks)**：
   在 [`test_observation_public_surfaces.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/tests/test_observation_public_surfaces.py#L385) 中，測試將 `search_stock_code` mock 為 `(None, None)`，人為切斷了代碼解析路徑，使得宣稱「個股情境不干擾大盤問答」的斷言並非經由產品真實流程達成。
4. **邊界情境之負面測試覆蓋不足 (Negative Testing)**：
   測試案例僅驗證了理想結構，未測試 `daily_focus: null`、`summary: null`、或者 `data_as_of` 不合法時的路由容錯性。
5. **視覺與觸控驗證無客觀自動化證據**：
   報告宣稱達成 1280×720 與 390×844 無水平溢出及 44px 觸控區，但僅附靜態截圖檔名，審查人員無法直接查驗截圖，亦無無障礙檢測（如 axe-core）或 Headless 瀏覽器 DOM 快照斷言作為客觀佐證。
6. **美股發布阻斷未解**：
   2026-10-06 SUNC 缺收盤價及 Nasdaq 備援無效為已知阻斷，但本分支無法證明在修復資料問題後美股發布流程能正常跑通。

---

## (5) 對作者實作與報告的簡明中立評估 (Neutral Assessment)

作者在此次變更中展現了對**業務規範與法規免責揭露**的高度嚴謹性，準確辨識了過去將中立事件硬性標示為風險、以及未提供量化研究章節時仍宣稱採用回歸模型的實務瑕疵，並成功實作了原生報告日期篩選、週末跨日交易時效判斷與行動端樣式調整。

然而，實作在**程式防禦性細節與邊界邏輯處理**上稍欠周延：
1. 對 Python `dict.get()` 在 `None` 值的邊界處理產生盲點，留下潛在 500 錯誤；
2. 對話關鍵字路由過於激進，未考慮自然語言包含「最新資料」副詞或查詢多檔標的之實質情境；
3. 部份單元測試設計透過刻意編排的 Mock 繞過真實業務路徑，造成測試通過但實際功能存在破綻。

報告撰寫誠實且不誇大（明確揭露未跑全量測試、承認正式站未部署及美股仍受限於外部資料阻斷），展現良好的工程品德，但在程式碼交付水準上，仍須將上述 P1/P2 實作缺陷完全修正後方具備合規發布資格。

