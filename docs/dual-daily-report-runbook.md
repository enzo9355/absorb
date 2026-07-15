# 雙每日報告操作手冊

## 產品節奏

- `post_close`：收盤後使用指定交易日資料與已 promotion 的完整回測，快速重訓 final model、產生五日預測與盤後主報告。
- `pre_market`：開盤前只疊加已保存、具 `source`／`as_of`／HTTPS attribution 的隔夜風險；不修改盤後模型機率。
- `weekly_model`：只接受 promoted backtest 與 matured prediction ledger。沒有新 promotion 時保留上一份週報。
- `full_backtest`：逐檔在背景執行，checkpoint 綁定 immutable manifest，可在 daily lock 出現時 yield。逐檔結果只是 candidate evidence，不會自動 promotion。

Cloud Run 只讀 `reports/v1`／`reports/v2` 的已驗證成品，不執行模型、回測、PDF 或外部隔夜資料抓取。

## 必要資料

本機資料根目錄固定為 `D:\AbsorbData`。年度交易日曆預設位置：

```text
D:\AbsorbData\publish\calendars\v1\TW-<year>.json
```

artifact 必須符合 `stock_papi.batch.calendar.TradingCalendar`，來源固定為 TWSE 官方 OpenAPI。缺年度、SHA、日期範圍或 schema 任一項時 fail closed。可用 `TWSE_CALENDAR_ARTIFACT` 指向同一資料根目錄內的替代檔案。

盤前來源以分號分隔的 `TW_PREMARKET_SOURCE_FILES` 提供。每個 JSON 都必須通過大小、時間、新鮮度與欄位驗證；沒有保存歷史 point-in-time 來源時不得事後回補。

## 手動執行

```powershell
# 盤後：fast lane -> schema v2 -> upload/read-back -> optional LINE notification
.\scripts\run_tw_post_close_pipeline.ps1 -DataRoot D:\AbsorbData

# 盤前：只做 overnight overlay
.\scripts\run_tw_pre_market_pipeline.ps1 -DataRoot D:\AbsorbData

# 背景完整回測，每次最多 25 檔；重跑會從 checkpoint 繼續
.\scripts\run_full_backtest.ps1 -DataRoot D:\AbsorbData -MaxItems 25

# 美股獨立批次
.\scripts\run_us_daily.ps1 -DataRoot D:\AbsorbData

# 模型週報；亦可手動觸發，不依賴特定星期
.\scripts\run_weekly_model.ps1 -DataRoot D:\AbsorbData

# 狀態
python -m stock_papi.batch.cli status --root D:\AbsorbData
```

若 `REPORT_NOTIFICATION_ENABLED` 不是 `true`，報告仍會發布，但通知命令會明確回報 disabled。正式啟用前須由 Secret Manager 注入 `LINE_CHANNEL_ACCESS_TOKEN`、`REPORT_ADMIN_USER_ID`，並設定 HTTPS `REPORT_PUBLIC_BASE_URL`。腳本參數與 Task Scheduler argument 不保存 secret。

## 安全 backfill

預設不寫入：

```powershell
python -m reporting.backfill `
  --root D:\AbsorbData `
  --market TW `
  --report-type post_close `
  --source-market-date 2026-07-13 `
  --source-manifest quant/v1/manifests/TW-20260713T090000Z-<id>.json `
  --source-manifest-sha256 <64-hex> `
  --model-version lgbm-5d-v1 `
  --calendar-artifact D:\AbsorbData\publish\calendars\v1\TW-2026.json
```

只有確認 dry-run 輸出、manifest hash、`market_as_of`、model version 與交易日曆後，才加 `--apply`。正式模式寫入 content-addressed PDF／metadata、index、latest 與 `logs/backfill-audit/<sha256>.json`；既有同 logical key 但內容不同時拒絕覆寫。`pre_market` 回補固定拒絕。

## Shadow 安裝與 cutover

先檢查定義，不修改 Task Scheduler：

```powershell
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode InstallShadow -WhatIf
```

確認 wrapper、D 槽 ACL、calendar、promoted backtest、GCP 與 LINE 設定後才正式安裝：

```powershell
.\scripts\migrate_stock_papi_tasks_to_absorb.ps1 -Mode InstallShadow
```

新工作：

- `ABSORB-TW-PostClose` 17:10
- `ABSORB-TW-PreMarket` 07:30
- `ABSORB-FullBacktest` 22:30
- `ABSORB-US-Daily` 05:30
- `ABSORB-WeeklyModel` 週六 18:00
- `ABSORB-ReportUploadRecovery` 09:35

遷移器不刪除舊 `StockPapi-*` 工作。先讓停用狀態的 ABSORB shadow tasks 通過定義驗證，再於變更窗口明確執行 Cutover；本 repository 變更不代表已完成 production cutover。

## 驗證清單

每次 shadow run 至少核對：

1. `latest-TW.json` 的 manifest hash、market date 與 failure rate。
2. `reports/v2` 的 immutable PDF／metadata 先於 index／latest 上傳。
3. uploader 遠端回讀的 index count 與 latest metadata identity 一致。
4. `pre_market.content.core` 與 base post-close content byte-equivalent。
5. notification receipt 依 content hash + audience 去重。
6. `logs/pipeline-status` 不包含 token、header、user id 或上游原始錯誤。
7. desktop 與 390px mobile 的 `/reports/trading-day/<date>`、盤前頁與 weekly 頁。

## 故障與 rollback

- daily source date、calendar、promoted backtest 或 manifest hash 不符：保持上一份成功 latest，不繼續通知。
- v2 upload/read-back 失敗：wrapper 非零退出；immutable local artifact 保留供 recovery，遠端 latest 不應被當作成功。
- 盤前來源全失敗：發布「資料不足，維持盤後判斷」；base 不存在則完全不發布。
- full backtest 被 daily job 打斷：保留 checkpoint，下次從 symbol boundary 繼續；未通過六個 gate 不得 promotion。
- rollout 異常：停用五個新工作，重新啟用原 `StockPapi-LocalQuant` 與 `StockPapi-QuantUpload`。不要刪除 immutable objects、prediction ledger、audit 或 checkpoint；Web reader 仍兼容 v1。

不要以手動覆寫 `latest`、關閉 SHA／size／uncompressed-size／schema 驗證、公開 GCS bucket、SAMPLE 資料或現在資料替代歷史資料作為修復手段。
