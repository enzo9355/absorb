# 試用發布清單（執行前需逐項授權；本文件僅備妥命令與查核點，不執行部署）

## 0. 狀態

- 本機：`LOCAL_VERIFIED`（產品＋本機瀏覽器通過；殘留見 ACCEPTANCE）。非 `BETA_READY`，更非生產切流。
- 候選版：**已建**（授權 A，2026-09-24）：revision `line-stock-bot-00283-zif`，
  tag `trading-ffda040`，0% 流量；read-back 見 `CANDIDATE-READBACK.md`。
  正式流量仍為 `00281-qeq` 100%，未動。

## 1. 候選版（~~需授權 A：建候選~~ A 已執行，見 CANDIDATE-READBACK.md）

- **重建待授權**：生產 wiring（`build_verified_us_trade_plan`）補完後，當前候選
  `00283-zif` 的 plan 預覽仍為舊碼（503）。重建命令同 §1（tag 改為新 SHA，
  如 `trading-<sha>`），零流量；重建後重做 §2 read-back（含
  `/api/account/trade-plan/US/INTC` 未登入應 401、`Cache-Control: private, no-store`）。

按 `docs/deployment_guide.md` 既有流程，保留現行 secrets 對應，另加
`--no-traffic` 建立零流量候選（以下 `<...>` 部署時填入，不寫入本文件）：

```powershell
gcloud run deploy line-stock-bot `
  --source . `
  --region asia-east1 `
  --project line-stock-bot-498908 `
  --no-traffic `
  --set-env-vars "LINE_LOGIN_CHANNEL_ID=<channel-id>,LINE_LOGIN_REDIRECT_URI=https://<Cloud-Run-domain>/auth/line/callback,AUTH_COOKIE_SECURE=true" `
  --set-secrets "LINE_LOGIN_CHANNEL_SECRET=stock-papi-line-login-channel-secret:latest,SESSION_SECRET=stock-papi-session-secret:latest"
```

## 2. Read-back（需逐項記錄，任一不符即停）

- [ ] `gcloud run revisions list`：候選 revision 為 latest ready，digest 記錄
- [ ] `gcloud run services describe ... --format yaml(status.traffic)`：候選流量 0%，正式流量未動
- [ ] 候選版 source SHA＝已審查的 git rev（`git rev-parse HEAD` 比對）
- [ ] `catalog_version`＝`public-opinions-v2-c2-2026-09-18-x-review`，catalog SHA 與本機一致
- [ ] 美股快照時間：候選端可讀 reviewed catalog；觀察一次美股快照自然更新（手動觸發只記 manual）
- [ ] auth callback、cookie（HttpOnly／Secure／SameSite=Lax）、CSRF、私人 API `private, no-store`
- [ ] TW＋US 各一筆讀取路徑 200；`/health` 200
- [ ] GCS artifact／pointer 未被候選版改動（`latest-<market>.json` generation 未變）

## 3. 小範圍試用（需授權 B：配置邀請名單）

- [ ] 經授權後設定 `ABSORB_TRADING_BETA_USERS`（兩個測試帳號先行；完整 ID 不進 repo）
- [ ] 兩個測試帳號走完：偏好→追蹤→建議→存計畫→新資料評估→站內提醒→回饋
- [ ] 首次真實 LINE 推播：僅已 opt-in 帳號，另行核對送達（本次：無同意帳號，未驗證）
- [ ] 觀察一次自然排程（手動觸發只記 manual test）

## 4. 排程差異（需授權 C；未授權前不建）

- 現況（已盤點 `scheduler-inventory.txt`）：`line-stock-alert-check` 平日 14:30
  Asia/Taipei → `POST /tasks/check-alerts`，僅涵蓋台股收盤；**無涵蓋美股快照完成
  （台北約 05:30 後）的自然排程**。
- 美股快照約台北 05:30 後可用（NYSE 16:00 ET＋15 分鐘延遲）；交易計畫檢查需另定時段。
- 在授權前：不新增、不調時段；程式端 `trade_plan_context` 預設 `enabled: False`。

## 5. 正式切流（需授權 D；另行切流指令）

- [ ] 另有正式切流授權才執行；讀回 `status.traffic`、來源標記、GCS pointer、正式網址
- [ ] ObservationOnly verifier 若不理解 beta 邊界，補驗證，不繞過、不誤報

## 6. 回滾

- 首選清空 `ABSORB_TRADING_BETA_USERS`；UI 隱藏入口；catalog 回退已驗證版本
- 禁止直接回滾到不認識 assistant 欄位的舊版後繼續寫 state（先備份、暫停寫入或相容版）
- 已推送訊息保留 event＋delivery，修正用追加更正
