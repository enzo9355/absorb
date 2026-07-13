# Stock Papi 發布 Blocker 與風險紀錄

## Blocker

| ID | 狀態 | 內容 | 關閉條件 |
| --- | --- | --- | --- |
| B-01 | Open | Phase 3B 通用 `manifest.json` 與現行 `quant/v1/latest-<market>.json` 尚未整合 | 指定單一正式控制面，並完成 adapter、測試與回滾演練 |
| B-02 | Open | 監控 collector 尚未由 `local_quant.py` 實際 runner 建立與送出 | 正式批次輸出 SUCCESS、WARNING、CRITICAL 事件並驗證通知 |
| B-03 | Open | 工作區未見 CI workflow、coverage artifact 與 security scan artifact | CI 產生四份 Quality Gate artifact，缺失時 fail-closed |
| B-04 | Open | GCS、Cloud Run 與 Secret Manager 的實際 IAM 尚未在目標專案驗證 | `verify_cutover.ps1` 全部輸出 READY |
| B-05 | Open | 手動回滾尚未在 production-like bucket 完成 10 秒演練 | 保存演練時間、前後 latest SHA-256 與 Cloud Run 健康證據 |

任何 Open Blocker 都禁止標示為可 cutover。

## 資料與發布風險

| 風險 | 影響 | 防護 | 剩餘處置 |
| --- | --- | --- | --- |
| FinMind、Yahoo 或新聞 API 429 | 資料過期或覆蓋率下降 | 快取、降級、95% 覆蓋率門檻 | On-call 依 Runbook 觀察兩個排程窗口 |
| latest 指標併發覆寫 | 指向非預期 manifest | 回滾腳本使用 generation precondition | 正式上傳器也必須採等效條件式更新或單一發布者鎖 |
| manifest/object 毀損 | Cloud Run 使用錯誤結果 | SHA-256、schema、gzip、大小驗證 | 保留最後 Quality Gate PASS manifest 作為 LKG |
| Universe 歷史不足 | 生存者偏差 | Gap Marker 與 fallback warning | 匯入歷史成分、下市資料後再關閉風險 |
| coverage artifact 缺失 | 假性品質通過 | Quality Gate fail-closed | 在 CI 建立可信 coverage 輸出 |

## 安全與營運風險

| 風險 | 防護 | Cutover 要求 |
| --- | --- | --- |
| Secret 外洩 | Secret Manager、日誌脫敏、文件僅列名稱 | 驗證 secret 名稱與 IAM，絕不讀取值 |
| GCS 公開或過度授權 | private bucket、uniform access、public access prevention | Cloud Run 僅 Object Viewer；發布主體最小寫入權限 |
| 本機資料遺失或 ACL 變更 | 固定 D 槽、受保護 ACL、低權限排程 | D 槽空間至少 100 GB，兩個排程未停用 |
| Cloud Run 冷啟動 | webhook 延遲 | 保持重運算於本機 | 部署後驗證 `/health` 與代表性 TW/US 查詢 |

## Cutover 停止條件

- Quality Gate 不是 `PASS`。
- 任一 manifest SHA-256、schema、market 或 coverage 驗證失敗。
- `verify_cutover.ps1` 任一檢查為 `BLOCKED`。
- 無法指定已驗證 LKG manifest。
- 回滾演練超過 10 秒、latest 指標未正確切換，或 Cloud Run 健康檢查失敗。
