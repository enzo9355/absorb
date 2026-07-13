# Stock Papi 安全部署手冊

## 前置條件

- Python 3.10、`gcloud`、Windows Task Scheduler 與可用的 D 槽 NTFS。
- Cloud Run 服務 `line-stock-bot` 位於 `asia-east1`、專案 `line-stock-bot-498908`。
- 本機發布帳號與 Cloud Run 服務帳號均採最小權限；不要建立或下載 service-account JSON key。

## Secret Manager

部署只引用 secret 名稱，不讀取或印出 secret 值。現有文件列出的名稱為：

- `stock-papi-line-channel-access-token`
- `stock-papi-line-channel-secret`
- `stock-papi-line-login-channel-secret`
- `stock-papi-session-secret`
- `stock-papi-gemini-api-key`
- `stock-papi-finmind-user`
- `stock-papi-finmind-password`
- `stock-papi-alert-task-token`

更新 secret 時使用 `docs/SECRETS.md` 的 `printf "%s"` 流程，避免換行字元被寫入憑證。

`LINE_LOGIN_CHANNEL_ID` 與 `LINE_LOGIN_REDIRECT_URI` 不是 secret，可作為 Cloud Run 環境變數；`LINE_LOGIN_CHANNEL_SECRET` 與 `SESSION_SECRET` 必須由 Secret Manager 注入。正式環境必須設定 `AUTH_COOKIE_SECURE=true`。

## LINE Login 與 Firestore

### LINE Developers Console

1. 在現有 Messaging API channel 的**同一個 Provider**下建立 LINE Login channel。只有同一 Provider 下的 channel 才會取得相同的 LINE user ID，才能讓 Web 與 LINE 共用自選股。
2. 在 LINE Login channel 設定正式 callback URL：

   ```text
   https://<Cloud-Run-domain>/auth/line/callback
   ```

3. 本機測試可另加 `http://localhost:5000/auth/line/callback`。callback 必須與 `LINE_LOGIN_REDIRECT_URI` 完全相同，不接受萬用字元或任意轉址。
4. 不要把 LINE Login Channel Secret 放入 `.env`、Docker image、GitHub Actions log 或前端 JavaScript。

### Firestore 與 IAM

使用原生模式 Firestore。Cloud Run service account 僅需資料存取權限，例如 `roles/datastore.user`；不要建立 service-account JSON key。程式使用下列 collections：

- `oauth_attempts`：短效、單次使用的 state／nonce／PKCE verifier。
- `web_sessions`：雜湊後的 session ID、CSRF token、到期時間與撤銷狀態。
- `users`：Web 登入資料、同意版本與最後登入時間。
- `line_users`：既有 LINE Bot 使用者與共用自選股；document ID 與同一 Provider 的 LINE user ID 一致。

應替 `oauth_attempts.expires_at`、`web_sessions.expires_at` 建立 Firestore TTL policy。TTL 是清理機制，不是授權判斷；應用程式仍會在每次讀取時檢查到期與撤銷狀態。

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
  --set-env-vars "LINE_LOGIN_CHANNEL_ID=<channel-id>,LINE_LOGIN_REDIRECT_URI=https://<Cloud-Run-domain>/auth/line/callback,AUTH_COOKIE_SECURE=true" `
  --set-secrets "LINE_LOGIN_CHANNEL_SECRET=stock-papi-line-login-channel-secret:latest,SESSION_SECRET=stock-papi-session-secret:latest" `
  --allow-unauthenticated
```

若現行服務已綁定其他 secrets，部署時必須保留原有對應，不可用上述範例覆蓋。部署後確認 latest ready revision、流量、`/health`，以及 TW 與 US 各一筆讀取路徑。不要把全市場回測或模型訓練移入 Cloud Run。

### LINE Login 上線驗證

1. 未設定登入 secret 時，`/`、`/dashboard`、`/reports` 與 `/health` 仍須可用；`/auth/line/login` 應安全回覆 `503`。
2. 點選登入，確認 LINE 授權頁的 channel 名稱與 Provider 正確，callback 僅回到本站允許路徑。
3. 登入後確認 `/account` 顯示正確帳號，cookie 為 `HttpOnly`、`Secure`、`SameSite=Lax`，私有 API 回覆 `Cache-Control: private, no-store`。
4. 從 Web 新增自選股，再由同一 LINE 帳號查詢；兩端應讀到同一份 `line_users/{line_user_id}` 資料。
5. 登出後重送舊 cookie；`/api/account/state` 應回覆 `401`。
6. 以不同 LINE 帳號登入，確認無法讀寫前一個帳號的自選股。

### 回滾

若登入異常但公開頁正常，先移除新 revision 的流量，回到上一個已驗證 revision。不要刪除 `line_users` 或既有使用者自選股。若只需暫停登入，可部署未設定 LINE Login secrets 的 revision；公開功能會維持服務，登入入口則 fail closed。SESSION secret 輪替會使既有 Web session 失效，應在維護公告中說明需要重新登入。

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
