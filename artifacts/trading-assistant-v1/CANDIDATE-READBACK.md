# 候選版 read-back（授權 A 執行結果）

## 第一版（旧 wiring，plan 預覽 503；已取代，保留紀錄）

- 建候選命令：`gcloud run deploy line-stock-bot --source . --region asia-east1
  --project line-stock-bot-498908 --no-traffic --tag trading-ffda040`
  （未帶 env/secret flags＝保留現行對應；`.gcloudignore` 排除 `.venv` 等；
  來源＝已審查 rev `ffda040` 工作樹＋既有未追蹤舊 artifacts 檔，無程式影響）
- 候選 revision：`line-stock-bot-00283-zif`，Ready，tag `trading-ffda040`
- 候選 URL：`https://trading-ffda040---line-stock-bot-3visrvv4yq-de.a.run.app`
- 流量：`line-stock-bot-00281-qeq` 100%（未動）；`00283-zif` 0%（tag、無 percent）
- `latestReadyRevisionName` 已指向 `00283-zif`（零流量 revision 照常成為 latestReady；流量未動）
- 候選版讀回：
  - `/health` 200；`/perspectives` 200（含「大咖動態」、種子 `serenity-tw-3006-self-001`、Pelosi pending）
  - `/stock/2330` 200；`/stock/INTC` 200；`/us` 200
  - 未登入 `/api/account/state` 401＋`Cache-Control: private, no-store`
  - `/auth/line/login` 302 往 LINE（secrets 保留）
- GCS（唯讀查核，候選未寫入）：`quant/v1/latest-US.json` generation `1790098161355678`；
  `quant/v1/latest-TW.json` generation `1790171279181920`
- catalog：`public-opinions-v2-c2-2026-09-18-x-review`（SHA 前 16 `78828183410b33cf`，與本機一致；候選頁已見種子）

下一步需授權 B（beta 名單＋兩個測試帳號）才可繼續；C（排程）、D（切流）亦未授權。

## 第二版（當前；含 verified builder wiring）

- 建候選命令：同 §1，`--tag trading-09fc8e1`，來源＝乾淨 worktree `@09fc8e1`
  （主工作樹另有他人未提交的 5 檔變更，未納入；見部署紀錄）。
- 候選 revision：`line-stock-bot-00284-hif`，Ready True，tag `trading-09fc8e1`
- 候選 URL：`https://trading-09fc8e1---line-stock-bot-3visrvv4yq-de.a.run.app`
- 流量：`line-stock-bot-00281-qeq` 100%（未動）；`00284-hif` 0%
- 候選版讀回：
  - `/health` 200；`/perspectives` 200（種子＋Pelosi pending 皆在）
  - `/stock/2330` 200；`/stock/INTC` 200
  - 未登入 `/api/account/trade-plan/US/INTC` 401（路由存在；登入後驗證待單人登入步驟）
- GCS 指標：沿用前次唯讀值（US `1790098161355678`／TW `1790171279181920`）；本次僅建 container revision，未寫資料。

## 第三版（當前；allowlist callback 修復）

- 建候選命令：同 §1，`--tag trading-35898b1`，外加
  `--update-env-vars ABSORB_LOGIN_CALLBACK_HOSTS=trading-35898b1---line-stock-bot-3visrvv4yq-de.a.run.app`
  （其餘 env／secrets 原樣保留；beta 名單仍空）。
- 部署源為乾淨 worktree `@35898b1`；主工作樹他人未提交變更未納入。
- 候選 revision：`line-stock-bot-00285-goc`，Ready，tag `trading-35898b1`
- 候選 URL：`https://trading-35898b1---line-stock-bot-3visrvv4yq-de.a.run.app`
- 流量：`line-stock-bot-00281-qeq` 100%（未動）；`00285-goc` 0%
- 候選版讀回：
  - `/health` 200；`/perspectives` 200（種子在）；`/stock/2330`、`/stock/INTC` 200（沿用前版方法）
  - `/auth/line/login` 302，其 authorize `redirect_uri` 已為候選 host
    （allowlist wiring 線上生效；正式站預設行為不變）
- 待使用者：在 LINE Developers Console 的 Login channel 加
  `https://trading-35898b1---line-stock-bot-3visrvv4yq-de.a.run.app/auth/line/callback`，
  然後重按登入（單人驗證步驟見 ACCEPTANCE）。
