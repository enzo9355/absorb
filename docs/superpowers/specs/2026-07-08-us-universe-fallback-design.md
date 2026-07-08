# Stock Papi 美股 Universe 啟動備援設計

## 問題

本機排程會在 05:30 執行美股批次，但首次建立 universe 時只依賴 SEC `company_tickers_exchange.json`。該端點目前對本機回傳 403，且系統尚無舊快取，因此美股批次在建立 checkpoint 與 artifact 前即結束。

## 設計

- SEC 維持第一來源，避免改變既有正常路徑。
- SEC 失敗且沒有可用快取時，讀取 Nasdaq Trader 官方 `nasdaqlisted.txt` 與 `otherlisted.txt`。
- 解析器只接受固定欄位、非測試證券及既有安全 ticker 格式；去重後排序。
- 成功結果沿用 `raw/us-universe.json` 快取，不新增資料庫或依賴。
- 若兩個官方來源都失敗，沿用既有舊快取；完全沒有快取才安全停止。

## 安全與資源限制

- 每個回應限制 5 MB、設定逾時，不接受重新導向到非 HTTPS 主機。
- 不記錄上游回應內容、憑證或私人資訊。
- 所有檔案只寫入 `D:\StockPapiData` 既有白名單路徑，維持原子寫入。
- 不在 02:30–09:30 以外強制執行市場下載或回測。
- Cloud Run 不執行此流程，因此不增加 1 GB 執行個體負擔。

## 驗證

- 單元測試涵蓋 Nasdaq 兩種格式、測試證券與危險 ticker 過濾。
- 回歸測試證明 SEC 失敗時使用 Nasdaq，兩者失敗時使用舊快取。
- 完整測試與 PowerShell 語法檢查通過後重註冊排程。
- 白天僅驗證官方清單可讀與排程設定；下一個 05:30 再確認 `progress-US.json` 與首批 artifact。
