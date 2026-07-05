# 本地量化完整時段執行設計

## 問題

排程 wrapper 固定傳入 `--limit 200`，今日 05:30 開始後於 05:37 完成 200 筆並正常結束，剩餘工作時段未被使用。

## 設計

- 排程專用 wrapper 將每次上限調整為 5,000，高於目前 2,076 檔台股 universe。
- 保留 `run_market_batch()` 每檔開始前的 09:20 時間檢查，以及 Windows Task Scheduler 的 4 小時硬上限。
- 當天未完成時沿用 `progress.json` 的 `next_index` 續跑；完成全市場後，隔日重新從第一檔開始更新。
- CLI 預設 200 不變，避免人工執行未明確指定上限時意外啟動全市場工作；只有受控排程 wrapper 使用 5,000。
- 今天已過 09:30，不繞過時間限制補跑；新設定從下一次 05:30 生效。

## 驗證

- 靜態測試確認 wrapper 傳入 `--limit 5000`，不再包含 `--limit 200`。
- 既有批次測試確認 09:20 停止與 checkpoint resume 行為不變。
- 完整單元測試、PowerShell parse 與 `git diff --check` 通過後推送。
