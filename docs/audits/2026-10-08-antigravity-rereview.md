### 程式碼複核結論

**審查結果**：**通過（No Actionable P1/P2 Defects Found）**  
本批次補丁精確修正了前次複核指出的缺陷，邏輯收斂乾淨且未引入新的回歸。**同意進入下一步驗收流程**（執行全量單元測試、建置驗證與本機瀏覽器驗收）。此為交付前程式碼複核，非正式部署許可。

---

### 八大重點檢查點靜態查驗結果

1. **純日期與混合分析意圖分離**（[`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195-L2210)）：
   - 實作 [`_observation_date_intent`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2195)，僅在具明確日期詞且不含價格／均線／走勢等分析詞時回傳 `"only"` 短路；含分析詞或泛稱「最新資料」時判定為 `"mixed"`。
   - 混合問句不再被日期短路吞沒，而是完整執行 Grounded 分析或觀測 Fallback，並透過 [`_with_observation_freshness`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2207) 於文末附加確定之日期與時效警示。

2. **逐檔市場行事曆核對**（[`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2351-L2356)）：
   - 迴圈遍歷 `entities` 時，各標的依其觀察物件之 `data.get("market")` 分別調用日曆核對，台美股各自獨立計算新鮮度，不再共用錯誤市場時區與邊界。

3. **多標的一成一敗、全失敗與多日期處理**（[`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2334-L2370)）：
   - **一成一敗**：查無資料者明列「無已驗證觀察資料」，整體 `data_quality` 降為 `"partial"`，成功標的仍完整列出。
   - **全失敗**：當 `not observations`，直接回傳條列回答，`data_quality="unavailable"` 且不發送無效引用。
   - **不同日期**：`dates` 集合大於 1 時，頂層 `data_as_of` 設為 `None`，不假裝單一日期，各自日期完整保留於內文。

4. **引用來源僅指向成功觀察**（[`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2343-L2350)）：
   - `citations` 僅在 `data` 成功取回且代碼合法時才收集，失敗或查無資料標的不會進入 `stock_citations`，杜絕壞死連結。

5. **Grounded 與 Fallback 均具備確定時效**（[`stock_papi/application.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2387-L2410)）：
   - Grounded 之上下文傳入 `evidence["observation_freshness"]`；回傳時無論是 LLM 成功或走 Fallback，均經 [`_with_observation_freshness`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/application.py#L2207) 保證包含資料日與 Stale 註記。

6. **Null 陣列防禦與發布校驗**：
   - 發布端 [`validate_observation_dashboard`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/batch/observation_products.py#L850) 新增 `all(isinstance(text, str)...)`，拒絕非字串。
   - 呈現端 [`dashboard.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/dashboard.py#L41-L45) 與 [`reports.py`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/stock_papi/web/routes/reports.py#L466) 加入 `or []` 及 `isinstance(text, str)` 守門；前端 [`app.js`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/static/app.js#L128) 過濾非字串，徹底消除 `TypeError` 隱患。

7. **個股狀態未知之保守標籤**（[`templates/stock_detail.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/stock_detail.html#L24)）：
   - 標籤改為 `== 'current'` 顯示「最新收盤」，其餘所有狀態（包括 `unavailable`、`stale`、`updating`）一律保守標示為「最近可用收盤」。

8. **官方狀態比較日期相容**（[`templates/stock_compare.html`](file:///C:/Users/enzo/.codex/worktrees/719b/absorb-production-runner-v2/templates/stock_compare.html#L6-L14)）：
   - 優先取用 `observation_as_of`，再取 `as_of`，修正台股官方狀態標的在比較表顯示「資料不足」的基底問題。

---

### 限制與後續步驟

靜態審查無新增 P1/P2，但受限於未親自執行全量測試集與未查驗瀏覽器渲染截圖，本結論以現有 diff 及其配套單元測試為限。建議**待專案 `unittest discover` 全量測試通過**後，即可提交驗收成果，並維持美股維運阻斷事項之原始註記。

