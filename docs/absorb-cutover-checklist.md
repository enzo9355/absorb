# ABSORB 外部 Cutover 與 Rollback Checklist

本文件只描述外部操作順序。Repository 變更不代表 production 已改名；每個階段必須在維護窗口取得明確核准，保存前後 revision／resource ID／hash 與驗證證據。

## 共同前置條件

- 完整測試、route inventory、cold-start heavy-import、secret scan、desktop／390px visual QA 與 `git diff --check` 均有當次證據。
- 新 revision 只讀既有 private GCS artifacts；不得關閉 SHA-256、size、uncompressed-size、path allowlist 或 schema 驗證。
- 記錄上一個 Cloud Run ready revision、GitHub repository URL、LINE rich menu ID、Windows task 狀態與 `ABSORB_DATA_ROOT`，作為 rollback 基準。
- 不刪除舊 repository redirect、service、secret、bucket、task、資料 root 或 compatibility shim。

## GitHub repository rename

1. 先確認 Actions、branch protection、Deploy trigger、webhook、badge、Cloud Build 與本機 remote 的實際引用。
2. 在 GitHub 執行 rename 前取得一次人工核准；名稱建議使用 `absorb`，但以可用性與組織規範為準。
3. rename 後確認舊 URL redirect、clone、Actions、required checks 與 deployment integration。
4. 最後才更新本機 `origin`、文件與外部連結。不要在 redirect 尚未驗證前刪除任何 integration。

Rollback：將 repository 名稱改回原值，恢復原 remote／webhook，確認 required checks 再開放合併。

## Cloud Run 與 GCP

1. 保留現有 `line-stock-bot` service 與 `stock-papi-*` Secret resource ID；resource ID 不等於顯示品牌。
2. 若建立新 ABSORB service，先以 0% traffic shadow deploy，沿用最小權限 service account 與 private bucket reader 權限。
3. 驗證 `/health`、TW／US 讀取、LINE webhook signature、LINE Login state／nonce／PKCE、session／CSRF、公開與私人 cache、`/api/conversation` 降級。
4. 若要複製 Secret，逐一建立新 secret、IAM 與 revision binding；不得讀值到 log，也不得先刪舊 secret。
5. traffic 逐步切換；每一步確認 error rate、latency、memory、LLM timeout 與 fixed-command availability。
6. GCS 與 Firestore 不因顯示品牌搬移。若另案遷移，必須有 immutable copy/hash/read-back、雙讀與 generation precondition 計畫。

Rollback：立即把 traffic 切回先前 ready revision；不要修改或刪除 GCS objects、Firestore user state、latest pointer 或 secrets。

## LINE Official Account／Login

1. 上傳 `static/brand/line-profile-640x640.png` 作為候選頭像；確認白底、比例與辨識度後才套用。
2. 使用 `assets/rich-menu.svg` 或 `scripts/apply_rich_menu.py` 產生候選，逐一核對固定 action text 與 URL；套用前取得核准。
3. 顯示名稱改為 ABSORB，但不建立新的 Provider／Messaging API channel／LINE Login channel。
4. callback URL、Channel ID、Channel Secret、同 Provider user ID 關聯保持不變；若 domain 另案變更，先加新 callback、驗證，再移除舊 callback。
5. 實測固定指令、股票代碼、自然中文、寫入確認、登入後自選共用、LLM unavailable fallback。

Rollback：重新綁定舊 rich menu／頭像／顯示名稱；Messaging API、Login channel 與 user state 不需搬移。

## Windows data root 與 tasks

```powershell
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -Copy -WhatIf
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -Copy
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -VerifyOnly
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -SwitchConfig -WhatIf
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -SwitchConfig

.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode Inventory
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode InstallShadow -WhatIf
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode InstallShadow
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode Cutover -ConfirmCutover -WhatIf
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode Cutover -ConfirmCutover
```

Shadow 驗證需包含 action、working directory、principal、Limited、retry、StartWhenAvailable、WakeToRun、IgnoreNew、資料 root、candidate hash 與上一份 latest 未被替換。

Rollback：

```powershell
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode Rollback -WhatIf
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode Rollback
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -Rollback -WhatIf
.\scripts\migrate_stock_papi_data_to_absorb.ps1 -Rollback
```

Rollback 只切設定與 task enablement；不刪 `D:\AbsorbData`、`D:\StockPapiData`、舊 task、audit、checkpoint 或 immutable artifact。

## Observation Production

正式 Observation 上線必須使用同一份 LKG receipt 串接 pointer、Cloud Run 與 rollback 證據，不得手動跳過中間步驟。

1. 執行 `capture_observation_lkg.ps1`，保存 dashboard 與 reports v2 mutable pointer 的 generation、內容與 SHA-256。
2. 發布並 read-back immutable Observation dashboard／report，再以 generation precondition 更新 index 與 latest。
3. 在所有 Observation pointers 已發布且可 read-back 後，以 `deploy_observation_production.ps1 -ApplyTraffic` 啟動受控上線。腳本先部署 no-traffic revision，明確設為 research、Observation 開啟、所有 Prediction flags 關閉，並移除正式 revision 的 preview prefix。
4. 對 tagged candidate 執行 `/health`、首頁、`/api/dashboard`、`/reports`、`/market-map`、`/stock/2330` smoke。任何非 200、非 Observation schema 或 API 出現 prediction fields，立即停止。
5. 腳本在切流量前以獨立 PowerShell process 執行 `verify_cutover.ps1 -ObservationOnly -BaseUrl <candidate-url>`，驗證 Cloud Run env、GCS generation／hash／schema、source manifest 與 HTTP；只有 `READY` 才會繼續。
6. 同一執行流程將已驗證 revision 切到 100%，並以正式 URL 重跑 HTTP smoke；完成後另以 `verify_cutover.ps1 -ObservationOnly` 保存正式狀態證據。
7. 保留 deployment receipt、前一 revision／traffic／env、LKG receipt、candidate／production smoke hashes 與正式驗證 JSON。

停止條件：preview prefix 未清空、任何 Prediction flag 不為 false、dashboard／report 不是 `product_mode=observation`、pointer generation 或 immutable hash 不符、API 含 prediction fields、任一 smoke 非 200，均不得切流量。

實際失敗時執行 `manual_rollback.ps1 -ObservationDeploymentReceipt <deployment-receipt.json>`。它先恢復前一 Cloud Run traffic，再呼叫 `rollback_observation.ps1` 依 applied generation 恢復或刪除本次新建 pointer；immutable objects 保留。正常演練只使用 `-WhatIf` 與 receipt/hash 驗證，不為了演練改動正式狀態。
