# 交接文件：ABSORB 交易助手 v1（給下一個模型／開發者）

日期：2026-09-24。分支：`codex/tw-premarket-verified-overlay`（已 push，最新見遠端）。
計畫書：`docs/superpowers/plans/2026-09-24-trading-assistant-v1.md`（0→9 任務制）。

## 0. 先看的三件事（按順序）

1. **正式站 LINE 登入目前是壞的**：LINE Developers Console（Login channel）的
   Callback URL 被換成了候選版網址（驗證所需）。驗證結束後必須換回
   `https://line-stock-bot-1067991373149.asia-east1.run.app/auth/line/callback`。
2. **卡點**：候選版 LINE 登入在「換 token」步驟 503（詳 §3），已備好診斷，下一步是重建候選＋重試。
3. **紅線**：正式流量 `00281-qeq` 100% 未動；beta 名單空；排程未改；不要切流、不要動 GCS。

## 1. 系統狀態

| 項目 | 值 |
|---|---|
| 正式流量 | `line-stock-bot-00281-qeq` 100%（`asia-east1`，專案 `line-stock-bot-498908`） |
| 候選版 | `line-stock-bot-00285-goc`，tag `trading-35898b1`，0% 流量（plan 預覽舊碼 503＋無 callback 修復） |
| 診斷版（待建） | 含 allowlist callback 修復＋token 狀態碼日誌，已 commit `71a5e98`，尚未部署 |
| 本機驗收 | `LOCAL_VERIFIED`（§13.1 目標 323 項全過；真實 Chrome 13 截圖在 `browser/`） |
| 全量 | 1774 項；4 項證偽為基線預存（乾淨 HEAD 同樣失敗，見 `preexisting-failures-head-clean.log`） |
| 排程 | `line-stock-alert-check` 平日 14:30（僅台股）；無美股時段排程（見 `scheduler-inventory.txt`） |
| 試用 | beta 名單空；真實推播未驗；2 週觀察未開始 |

## 2. 已完成（全在分支上）

- 任務 0–9：操作紀錄契約、種子資料（Serenity TW 3006 自述 1 筆；Pelosi pending；Berkshire source_only）、
  `us_daily_breakout_v1` 規則、assistant state＋私人 API、Web／ASK 共用建議、交易頁＋個股計畫卡、
  plan checks＋5/20 後續觀察、check-alerts 串接＋opt-in 推播狀態機、ACCEPTANCE＋TRIAL-GUIDE。
- 生產快照轉接：`build_verified_us_trade_plan`（唯一來源＝已驗證 quant artifact＋真實 digest；
  真實 INTC 產物 `fcc39dcb…` 端到端測試，`tests/test_trade_plan_market.py`）。
- 候選 OAuth 修復：`login_callback_hosts` allowlist（預設空＝正式行為不變；測試 18 項）。
- 關鍵新檔：`stock_papi/services/trade_plans.py`、`trade_plan_checks.py`、`trade_plan_market.py`、
  `stock_papi/batch/public_activity_cli.py`、`templates/account_trading.html`、`subject.html`。

## 3. 卡點：候選版登入 503（完整證據鏈）

- 現象：候選版按 LINE 登入 → 「LINE Login 暫時無法完成」。
- 日誌：`00285` 上 `.../auth/line/callback?code=... 503`（state／cookie／attempt 檢查已過，死在 token 交換）。
- 根因（已排除）：PKCE 實作標準；cookie／state；redirect_uri（線上驗證已帶候選 host）；
  env 接線（`LINE_LOGIN_CHANNEL_ID=2010717237`、`..._SECRET→stock-papi-line-login-channel-secret@3`、
  prod redirect URI）；channel_id 自洽。过去 7 天正式站零成功登入，無人注意過。
- 診斷缺口：舊碼把 LINE 回的確切碼吞成通用 503。`71a5e98` 已加**只記狀態碼**日誌
  （`line_token_status=`／`line_verify_status=`，無 secret／code／body）。
- 待做：`gcloud run deploy ... --no-traffic --tag trading-71a5e98`（＋沿用
  `--update-env-vars ABSORB_LOGIN_CALLBACK_HOSTS=<新tag host>`）→ 使用者重按登入 →
  讀 `line_token_status`：
  - `invalid_client` → secret 值對不上 console：照 `docs/SECRETS.md` printf 流程建新版，
    service pin 從 `@3` 改過去，再重建一次。
  - `invalid_grant` → 查 code／redirect／PKCE（把 callback 日誌時間給模型）。
  - 逾時／例外 → 偶發，重試。
- 注意：service 的 secret 綁定是 pin `@3` 不是 `:latest`（部署指南寫 `:latest`，現況是 pin；
  動它等于改服務配置，想清楚再碰）。

## 4. 之後順序（都要使用者逐項批准）

1. 上述診斷重建＋重試登入（前方已有兩次批准模式：零流量重建可直接做）。
2. 單人驗證（使用者已選項 2）：403 鎖定 → 加 beta → 200＋真實 INTC 計畫 → 移除恢復 403。
   beta 名單設定＝授權 B（需先從 Firestore `users` 找其 User ID，只取 ID 不記名）。
3. **立刻把 LINE console Callback URL 換回正式站**（§0.1）。
4. 授權 C（美股排程）、D（切流）才繼續；命令與 read-back 點見 `RELEASE-CHECKLIST.md`。

## 5. 環境坑（已踩過，直接避開）

- PowerShell 5.1：無 `tail`、`head`、`SkipHttpErrorCheck`；`npx`／`gcloud.ps1` 被執行原則擋，
  改用 `gcloud.cmd`；`traffic.txt` 存成 UTF-16，解析指定編碼。
- `edit` 工具疑似保留 mtime → `__pycache__` 幽靈：除錯先刪 `__pycache__`，或換檔名。
- 佔 port 的殘留行程：`netstat -ano | Select-String 8765` 查 PID 後 `Stop-Process`。
- 二進位下載勿經 PowerShell 轉向（會變 UTF-16）：用 `gcloud storage cp <gs> <local>`。
- 本機 harness（`C:\Users\enzo\AppData\Local\Temp\opencode\bh2.py`，**不在 repo**）：
  真實模板＋真實 catalog＋真實 builder，`?_test_as=beta|nonbeta` 後門僅 harness；
  Chrome 用 `"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless --screenshot`。
- `git worktree` 建乾淨部署源，避免把主工作樹他人未提交檔摻入（發生過一次，已處理流程）。
- 測試B：`test_notification_gate` 不存在（推播狀態機在 `test_trade_plan_checks`）。

## 6. 敏感守則

- 永不印出 secret 值、CSP token 以外的憑證、完整 LINE User ID（进 repo 只留前綴或 `U***`）。
- `ABSORB_TRADING_BETA_USERS`、`ABSORB_LOGIN_CALLBACK_HOSTS` 用 env 注入，不進 repo。
- 推播只有 opt-in 才發；unknown 狀態不盲重發、不謊報 sent。
