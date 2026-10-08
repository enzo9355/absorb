# Antigravity 討論後修正與驗收

日期：2026-10-08（Asia/Taipei）。分支：`codex/web-review-fixes-20261007`。本批修正基底：`fa1cf7c8cd02b5dfed092ded5ad5f74eabe9978d`。

## 討論與複核

Antigravity CLI（`gemini-3.8-flash-high`）延續同一 conversation `2624610e-7427-46a7-9304-ce0fb47f89e6`。原審查 7／10、要求修改；提供重現與來源契約後，它把 null 清單 P1 降為防禦改善，撤回 market fallback、架構回歸與測試動機推論。

- [技術討論原文](2026-10-08-antigravity-discussion.md)
- [修正後複核原文](2026-10-08-antigravity-rereview.md)
- [最後語句邊界與基底失敗複核](2026-10-08-antigravity-final-followup.md)

最終結論：「**通過（無新增可操作 P1/P2 缺陷）**」，可保存本機提交。此結論是針對所提供差異的靜態審查；Antigravity 沒有親自執行測試、查看截圖或驗證正式站，不構成部署驗收。

## 已修正

1. 純日期問題才直接回應日期。混合價格／均線／強弱問題保留分析流程，提供已驗證時效作為 grounded context，並在模型成功或 fallback 回答後附上確定的日期與時效警示。未知日期後綴採保守分析路徑。
2. 多標的逐檔核對所屬市場日曆、日期及來源。缺資料標的明列「無已驗證觀察資料」，不產生虛假引用；不同日期或有缺資料時不宣稱單一共同日期。全部無資料時回傳 unavailable。
3. 比較頁優先採 observation_as_of，保留官方交易狀態的觀察日期與品質標示。
4. 個股只有 freshness current 才顯示最新收盤；其餘狀態顯示最近可用收盤。
5. 發布驗證拒絕非字串的 daily_focus 項目；前端過濾非字串，呈現副本容忍 null 清單，不修改 canonical objects 或快取原物件。沿用既有安全與資料驗證限制，未新增依賴。

## 驗收

| 項目 | 實際結果 |
| --- | --- |
| 修改前相關案例 | 145 項中 14 個失敗／subtests，確認可重現；另補的未知分析語句亦先確認失敗。 |
| 最後相關回歸 | **323 項通過**，exit 0；包含公開／私人、注入及交易限制。 |
| JavaScript | `node --check static/app.js` 與 `node tests/check_dashboard_focus.cjs` 通過；後者以 vm 執行實際 bundle，驗證 null／非字串焦點不會中斷呈現。 |
| 完整回歸 | 最新 `python -m unittest discover -s tests -q`：**1,903 項，1,899 通過、2 失敗、2 跳過**，exit 1。未宣稱完整測試全綠。 |
| 基底失敗核對 | 從 fa1cf7c 取出原 test／scripts 至臨時目錄，只跑兩個失敗案例，亦重現相同失敗；相關三檔與目前版本完全相同。 |
| 本機瀏覽器 | 合成資料，1280×720 桌面及 390×844 手機。混合問句保留行情與時效，多標的列出兩檔日期／引用；受檢 ASKsorb 頁面 client／scroll 分別為 1265／1265、375／375，無整頁水平溢出，未見 console error。 |

完整回歸的兩個既有失敗：

- `test_mutex_abandonment_and_partial_timeout_release_exactly_once`：Windows abandoned mutex 測試斷言失敗。
- `test_us_post_close_retries_through_yahoo_eod_finalization`：測試期待 5 小時重試窗口，既有腳本已為 12 小時。

證據：[相關回歸](2026-10-08-antigravity-fixes-regression.log)、[完整回歸](2026-10-08-antigravity-fixes-final-full-suite.log)、[基底重現](2026-10-08-antigravity-baseline-failures.json)、[基底完整輸出](2026-10-08-antigravity-baseline-failures.log)、[前端執行檢查](2026-10-08-dashboard-focus-check.log)。

畫面：[手機多標的問答](2026-10-08-antigravity-fixes-mobile.jpg)、[桌面混合問題](2026-10-08-antigravity-fixes-desktop.jpg)。價格、日期及名稱均為合成驗收資料，不能用來證明正式資料已更新。

## 剩餘限制

本次**未部署**，未修改或註冊正式排程、發布指標、資料門檻或研究審核狀態。兩項既有排程測試失敗仍保留。前次審查發現的 SUNC 缺收盤價／Nasdaq 備援格式問題及研究待審狀態，本次沒有重新驗證或修復；網站程式修正不代表發布資料已更新。
