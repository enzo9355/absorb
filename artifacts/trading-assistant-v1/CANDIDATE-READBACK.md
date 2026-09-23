# 候選版 read-back（授權 A 執行結果）

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
