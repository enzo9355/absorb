# Stock Papi 安全部署手冊

## 前置條件

- Python 3.10、`gcloud`、Windows Task Scheduler 與可用的 D 槽 NTFS。
- Cloud Run 服務 `line-stock-bot` 位於 `asia-east1`、專案 `line-stock-bot-498908`。
- 本機發布帳號與 Cloud Run 服務帳號均採最小權限；不要建立或下載 service-account JSON key。

## Secret Manager

部署只引用 secret 名稱，不讀取或印出 secret 值。現有文件列出的名稱為：

- `stock-papi-line-channel-access-token`
- `stock-papi-line-channel-secret`
- `stock-papi-gemini-api-key`
- `stock-papi-finmind-user`
- `stock-papi-finmind-password`
- `stock-papi-alert-task-token`

更新 secret 時使用 `docs/SECRETS.md` 的 `printf "%s"` 流程，避免換行字元被寫入憑證。

## Cloud Run

目前容器以一個 Gunicorn worker、八個 threads 啟動：

```text
gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
```

部署前先完成 Quality Gate 與 cutover 檢查，再執行既有部署命令：

```powershell
gcloud run deploy line-stock-bot `
  --source . `
  --region asia-east1 `
  --project line-stock-bot-498908 `
  --allow-unauthenticated
```

部署後確認 latest ready revision、100% traffic、`/health`，以及 TW 與 US 各一筆讀取路徑。不要把全市場回測或模型訓練移入 Cloud Run。

## Windows 本機批次

資料根目錄固定為 `D:\StockPapiData`。安裝命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local_quant_task.ps1
```

- `StockPapi-LocalQuant`：02:30 啟動、7 小時限制、`IgnoreNew`、Limited run level。
- `StockPapi-QuantUpload`：09:35 啟動、1 小時限制、`IgnoreNew`、Limited run level。
- Python runner 在 09:20 停止接收新標的，09:30 結束運算。

驗證命令：

```powershell
Get-ScheduledTaskInfo 'StockPapi-LocalQuant'
Get-ScheduledTaskInfo 'StockPapi-QuantUpload'
Get-Content 'D:\StockPapiData\logs\runner-status.json'
Get-Content 'D:\StockPapiData\logs\upload-status.json'
```

## GCS 與發布

bucket `line-stock-bot-498908-quant-snapshots` 必須維持 private、uniform bucket-level access、public access prevention 與生命週期規則。正式發布順序為 object、manifest、latest；latest 是唯一可變指標。

手動回滾只能更新 `latest-<market>.json`，並必須使用 `scripts/manual_rollback.ps1` 的 generation precondition。不要刪除歷史 manifest 或 object。

## 上線前驗證

1. 生成並保存 Quality Gate Markdown 與 evidence JSON。
2. 以 `scripts/verify_cutover.ps1` 驗證 GCS、IAM、Secret、hash、排程與 latest 指標。
3. 於變更窗口執行部署，並保留上一個 Quality Gate `PASS` manifest 作為 LKG。
4. 如有異常，依 `docs/runbook_incident_response.md` 回滾，不修改資料庫或策略。
