# ABSORB 多頁資訊架構與報告可靠性實作計畫

1. 保存 Production revision、traffic、Observation env、GCS pointers 與實際 500 trace 證據。
2. 加入脫敏 Production-shaped post-close／pre-market fixture；先讓 canonical route 與 legacy index regression tests 失敗。
3. 建立 typed report view model，依 report type 正規化 content；新增盤後、盤前與當日索引模板。
4. 實作 404／503／500 報告錯誤映射、route-level structured log 與安全 correlation ID。
5. 更新 `/reports`、首頁與 notification URL 產生器到 canonical routes，不執行通知。
6. 將既有 dashboard 區段投影到 `/market`、`/industries`、`/stocks`、`/ask`、`/learn`，縮減首頁並更新導覽及 legacy hash allowlist。
7. 執行 focused tests、完整 suite、靜態安全檢查、PowerShell parser、import cold-start 與多尺寸 browser QA。
8. 以小步 commit 保存 report fix、multipage IA 與驗證／部署腳本調整，完成唯讀深度審查。
9. 部署 no-traffic revision，用真實 GCS 驗證 canonical reports、全部新路由、OAuth callback 邊界與 Observation-only gates。
10. 通過後切換 Production，重查 revision／traffic／env／GCS pointers／HTTP；若驗證失敗立即恢復先前 traffic。
