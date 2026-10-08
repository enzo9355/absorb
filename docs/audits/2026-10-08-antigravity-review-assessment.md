# Antigravity 評價與核對

日期：2026-10-08（Asia/Taipei）。受審提交：`fa1cf7c8cd02b5dfed092ded5ad5f74eabe9978d`，基底：`90535c104d2e55c69e1992bcd1e4b06e07451036`。

## CLI 原始結論

- 工具：本機 Antigravity CLI；模型：`gemini-3.8-flash-high`，effort high。
- 結果：SUCCESS；conversation `2624610e-7427-46a7-9304-ce0fb47f89e6`；分析約 361 秒。
- 評分：**7.0／10**。判定：**條件式暫緩上線／要求修改**。
- 肯定：交易日曆與保守時效判定、安全邊界、呈現副本避免污染快取、原生日期／展開控制項、揭露未部署及資料阻擋的限制。
- 批評：日期意圖攔截過寬、多標的遺漏、空值容錯及測試邊界覆蓋不足。
- 審查僅讀取提交差異與附帶程式前後文；未執行工具、重跑測試、查看截圖或驗證正式站。輸入並未包含所有既有資料驗證器，因此部分推論需要核對。

[完整原文](2026-10-08-antigravity-review.md)；[原始串流輸出與用量](2026-10-08-antigravity-review-output.jsonl)；[審查輸入](2026-10-08-antigravity-review-input.md)。原文保留其評分與主張，未改寫成作者的結論。

## 作者核對結果

以下核對未修改產品程式；兩項對話問題已使用既有合成快照在本機重現。[重現輸出](2026-10-08-antigravity-findings-check.json)。

| Antigravity 意見 | 核對結果 |
| --- | --- |
| P1-1：`daily_focus`／`summary` 為 null 導致正式頁面 500 | 路由若直接注入 null，新增迭代確實不容錯；但正式 dashboard loader 呼叫 `validate_observation_dashboard`，report index loader 呼叫 `validate_report_index`，均拒絕 null／錯誤型別。尚未成立為正式資料可觸發的 P1；可作額外防禦改善。 |
| P1-2：含「最新資料」的行情問題被日期回答吞掉 | **已重現。**「根據台積電最新資料，目前價格與均線如何？」命中日期模板；實質價格／均線意圖未被回答。 |
| P2-1：多標的日期問題只回答第一檔 | **已重現。**兩檔快照都有效時，「2330 和 AAPL 最新資料日？」只回台積電，引用亦只有 `/stock/2330`。原先首檔失敗測試旨在驗證成功標的市場，未涵蓋兩檔都成功；不能據此推定有意規避。 |
| P2-2：成功觀察缺少 market | **目前不成立。**`build_stock_observation` 的 regular 與官方狀態分支都提供 market，亦已用 fixture 核對 TW／US；任意 fallback 至第一個原始 entity 可能重新引入市場錯配。 |
| P2-3：比較頁漏讀 observation_as_of | **官方交易狀態標的確實存在呈現缺口。**此類 view 有 observation_as_of、沒有 as_of。一般美股 view 同時提供兩欄，不能概括為所有美股都失敗。模板此欄讀法在基底已存在，屬既有問題。 |
| P3-1：明確台股問題仍繼承 AAPL | **未證實。**既有 `resolve_entities` 在未找到個股時會把「台股／大盤」解析為 TAIEX，後續已轉回 TW；原文缺少能繞過此路徑的實際案例。 |
| P3-2：unavailable 時仍標「最新收盤」 | **程式條件確認。**目前只將 stale／updating 改為最近可用收盤；無法驗證新鮮度也宜採保守標籤。尚未做額外瀏覽器重現。 |
| P3-3：美股支援僅語法驗證 | 與既有個股路由的語法支援政策一致，不能直接當成新增回歸；仍可另訂資料涵蓋政策。 |
| P3-4：每日焦點非字串使 JS replace 失敗 | **確認驗證缺口。**dashboard 驗證器只檢查 daily_focus 是 list，實測接受 `[None]`；前端對項目直接呼叫 replace，遇 null 會失敗。正常發布器目前產生字串，但不能據此視為完整型別防護。 |
| P3-5：research_time 初始化與 us_presentation 命名耦合 | 維護性建議；未提供實際初始化失敗或產品行為回歸。 |

## 當前狀態

本節記錄 fa1cf7c 當次審查時的狀態；後續已依討論修正，最新結果見 [修正與驗收](2026-10-08-antigravity-fixes-result.md)。

本次只完成外部審查、核對及保存評價。**沒有據此修改產品程式，也沒有部署。**日期意圖與多標的遺漏是已確認需要處理的問題；比較頁官方日期、unavailable 報價標籤與每日焦點項目型別亦應納入後續修正。原先 297 項測試通過不能排除這些未覆蓋情境。
