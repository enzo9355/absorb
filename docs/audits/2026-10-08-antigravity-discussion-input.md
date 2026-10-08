# Follow-up discussion before implementation

請延續 conversation 2624610e-7427-46a7-9304-ce0fb47f89e6，對你審查 fa1cf7c 的意見進行技術討論。使用者已要求我們討論後開始修正。我會負責實作；你本次只審閱以下證據與修正方案，不使用工具、不修改檔案、不部署。請以繁體中文在 1000 字內回覆，給出實際同意／撤回／仍待證明的意見，不要迎合作者。不需要重新評分。

## 已重現並接受

1. `_observation_date_answer` 用 any substring 命中「最新資料」，使「根據台積電最新資料，目前價格與均線如何？」直接只回答日期。
2. 兩檔觀察都成功時，「2330 和 AAPL 最新資料日？」只回答 2330，citation 也只有 /stock/2330。
3. 官方 TW 狀態 view 使用 observation_as_of 而沒有 as_of，比較表漏日期。一般 US regular view 同時提供兩個日期欄位，並非所有美股失敗。此比較欄位在 BASE 已存在，但會一併修正。
4. 個股 freshness unavailable 時，quote_label 仍顯示最新收盤，應保守顯示最近可用收盤。
5. dashboard validator 只檢查 daily_focus 是 list，實測 `[None]` 通過；新增前端 text.replace 對非字串會錯。正常 writer 產生字串不足以證明信任邊界安全。

## 請重新評估的意見

A. P1-1 的 null list 正式路徑：`stock_papi/repositories/dashboard_snapshots.py::load_dashboard_snapshot` 在 hash/identity 校驗後呼叫 `validate_observation_dashboard`。後者拒絕 `not isinstance(document.get("daily_focus"), list)`。`stock_papi/repositories/report_store.py::load_report_index` 呼叫 `reporting/web.py::validate_report_index`，v1/v2 拒絕 summary 非 list 及其中非字串。因此 daily_focus:null／summary:null 無法通過正式 loader；路由可增加 `or []` 防禦，但沒有可達路徑證據時不應定為已證實 P1。請區分 daily_focus 為 null 與 list 中元素為 null。
B. P2-2 market fallback：`stock_papi/services/observation_view.py::build_stock_observation` regular result 固定含 `"market": snapshot["market"]`，成功條件要求 market 為 TW/US；官方狀態 branch 固定含 `"market":"TW"`。本機已用 fixture 核對兩分支。不能使用迴圈最後的 entity 或第一檔 entity 作 fallback，因首檔失敗時會把 AAPL 套用 TW 行事曆。
C. P3-1 明確台股問題：既有 `absorb/conversation/tools.py::resolve_entities` 對沒有個股結果而含台股／大盤／加權指數／盤勢的問題，回傳 TAIEX；conversation 在繼承頁面 context 前已取得該 entity，並於後段移除 TAIEX、設定 TW。除非有可繞過此路徑的具體例子，不能說缺 explicit_tw 分支即有 bug。
D. US ticker 語法支援沿用現行 stock route 政策；research_time 全域 filter 在建立 app 時註冊。這些可作維護或產品政策建議，但未證明本次引入功能回歸。
E. 首檔失敗的新增測試是針對成功觀察市場錯配的回歸，未涵蓋兩檔都成功屬覆蓋不足，不能推定作者刻意掩蓋。你未看過截圖也不能等同作者沒有量測 DOM；它不在你收到的 evidence bundle 內。

## 擬採最小修正

- 收窄「只有日期／時效」短路意圖；只有泛稱「最新資料」且含價格／均線／表現等分析內容時，走既有 grounded observation 回答。真正資料日／是否過期問題仍使用 deterministic 日期與日曆。
- 對純日期問題逐一回應所有已辨識標的，各自日期、market、freshness 和 citation；無資料標的也明示，不靜默遺漏。混合台美股不要共用錯誤行事曆或宣稱同日；混合問題保留來源與時效說明。
- 比較頁日期優先 observation_as_of，再 as_of；未知新鮮度採最近可用收盤。
- 防禦 null list；dashboard 來源驗證／前端對非字串焦點維持保守行為，不把 null 轉成顯示文字、不修改 canonical objects 或放寬其他驗證。
- 先補會失敗的真實流程回歸，再實作；測試保留公開／私人／注入／交易限制與不同市場日曆。完成後把差異與結果送你複核。

請回答：哪些原意見撤回或降級？上述方案還有哪些具體漏洞，尤其純日期／混合分析意圖及兩檔一成功一失敗的處理？若有不必要的擴張請指出。
