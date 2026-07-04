# Stock Papi 本地選擇權資料管線設計

## 目標

在不增加 Cloud Run 1GB 記憶體與冷啟動風險的前提下，使用公開 API 與本地批次運算補充美股選擇權、利率及波動率曲面特徵。完整 Option Chain 不進入網頁請求流程；Cloud Run 只讀取已聚合、通過驗證的小型歷史特徵。

本階段維持所有台股與美股查詢。個股選擇權特徵只套用於有選擇權、流動性與歷史覆蓋達標的美股；其他股票使用現有模型與缺漏旗標，不因資料不足而拒絕預測。

## 資料來源

### Alpaca Market Data

- 使用免費 Basic 帳號的 Indicative options feed。
- 歷史選擇權資料自 2024 年 2 月開始。
- 本地批次程式讀取合約清單、歷史日 K、成交量及可用報價。
- `ALPACA_API_KEY_ID` 與 `ALPACA_API_SECRET_KEY` 只存在本機環境變數或作業系統憑證儲存，不寫入 repo、輸出檔或 Cloud Run。
- 免費方案不宣稱為完整 OPRA 即時資料；所有輸出保留 `source=alpaca_indicative` 與資料時間。

### 美國財政部利率

- 優先使用美國財政部公開的 Daily Treasury Par Yield Curve 資料，不增加第三方 SDK。
- 使用 10 年期殖利率建立利率水準、五日變化與個股報酬／殖利率變化的滾動相關性。
- 為避免發布時間造成回測偷看，模型一律使用前一個已完成交易日的利率資料。

### 現有來源

- FinMind、TWSE／TPEx、yfinance 與既有 VIX／VIX9D／VIX3M 特徵保留。
- 新來源是補充，不取代既有價格與籌碼主來源。
- 台股第一階段只使用市場級 VIX 與利率環境，不假設每檔台股都有可用個股選擇權。

## 架構

```text
本機排程
  -> 取得 Alpaca 合約與歷史日資料
  -> 取得官方美國公債殖利率
  -> 驗證、去重、按日期排序
  -> 本地計算 IV、Smile、期限結構與量能聚合
  -> 產生逐股 gzip JSON + SHA-256 manifest
  -> 使用目前 gcloud 使用者登入上傳私人 GCS
  -> 最後上傳 manifest，原子切換版本

Cloud Run
  -> 讀取 manifest
  -> 按查詢股票下載單一小型 gzip JSON
  -> 驗證 schema、大小、雜湊、日期與有限數值
  -> 向後對齊價格資料
  -> 缺漏或失效時回到中性值
```

不新增公開匯入路由。上傳端不使用長效 service-account JSON；本機使用既有 `gcloud` 使用者 OAuth。Cloud Run 服務帳號只取得指定 bucket 的 `storage.objectViewer`，沒有上傳或刪除權限。

## 儲存格式

私人 bucket 由環境變數 `OPTION_FEATURE_BUCKET` 指定：

```text
gs://<bucket>/option-features/v1/manifest.json
gs://<bucket>/option-features/v1/symbols/AAPL.json.gz
gs://<bucket>/option-features/v1/symbols/MSFT.json.gz
```

manifest 最少包含：

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-04T12:00:00Z",
  "source": "alpaca_indicative",
  "symbols": {
    "AAPL": {
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "rows": 500,
      "first_date": "2024-07-01",
      "last_date": "2026-07-02"
    }
  }
}
```

逐股檔案只保存日期與聚合特徵，不保存完整合約、逐筆成交、LINE userId 或使用者持股。格式使用 JSON + gzip，不使用 pickle 或其他可執行序列化格式。

## 第一階段特徵

### 利率特徵

- `US_RATE_10Y_LEVEL`：10 年期美國公債殖利率。
- `US_RATE_10Y_CHG_5`：殖利率五個交易日變化。
- `STOCK_RATE_CORR_20`：個股日報酬與殖利率日變化的 20 日相關性；不使用股價水準直接計算相關性。

### 個股選擇權特徵

- `OPTION_ATM_IV`：接近 30 天到期、最接近價平合約的聚合隱含波動率。
- `OPTION_PUT_CALL_IV_SKEW`：相近到期日下，價外 Put 與價外 Call 的 IV 差。
- `OPTION_IV_TERM_SLOPE`：約 90 天 IV 減約 30 天 IV。
- `OPTION_CALL_PUT_VOLUME_LOG_RATIO`：`log((Call volume + 1) / (Put volume + 1))`。
- `OPTION_PREMIUM_IMBALANCE`：Call 與 Put 的成交量乘日均價之標準化差值。
- `OPTION_LOCAL_DATA_MISSING`：該日沒有合格資料時為 1。

`OPTION_PREMIUM_IMBALANCE` 明確稱為權利金不平衡，不冒充 Net Premium Flow。真正的 Net Premium Flow 需要逐筆成交與當時 bid／ask 判斷主動買賣方向，第一階段不以不完整資料偽造。

## Black-Scholes 與 Greeks 的角色

- 本地端以 Python 標準函式庫實作 Black-Scholes 與有限範圍二分法，從合約日價格反推 IV。
- Delta 只用於挑選相近 moneyness；Vega 用於排除不穩定反解；不把每個合約的所有 Greeks 直接塞入模型。
- Charm surface、dealer GEX、Vanna flow 與完整 Net Premium Flow 延後，直到有可靠的歷史 OI、逐筆成交方向與報價資料。
- 不新增 SciPy、QuantLib 或大型資料科學套件。

## 本地批次範圍

- 第一次回補以 500 檔最活躍、具選擇權且歷史覆蓋足夠的美股為上限。
- 全市場股票查詢仍可使用；不在這 500 檔內或沒有選擇權的股票回到既有模型。
- 排名以標的成交金額、Option volume 與資料完整度決定，不寫死公司名單。
- 批次工具提供明確的 `--limit`、`--start-date`、`--resume` 與 `--dry-run`，方便在 API 限額下續跑，不在 Cloud Run 內回補。
- 日更只處理新日期；原始回應可暫存在本機 gitignore 目錄，完成聚合後不必上傳。

## 安全控制

- 所有外部請求設定連線與讀取 timeout、有限重試及指數退避。
- 限制回應大小、頁數、合約數與單一輸出解壓後大小，防止異常回應耗盡記憶體或磁碟。
- 僅接受標準美股代碼、ISO 日期、有限浮點數與已知欄位；NaN、Infinity、重複日期及未來日期拒絕發布。
- 每個逐股檔案計算 SHA-256；Cloud Run 必須先驗證 manifest 與檔案雜湊。
- 資料檔先上傳，manifest 最後上傳；失敗時舊 manifest 仍可使用。
- manifest 過期、雜湊不符、schema 不符或 GCS 無法連線時，回傳中性特徵並標記缺漏，不影響 LINE webhook。
- 日誌只記錄來源、symbol、日期、狀態與錯誤類型，不記 API key、Authorization header 或完整外部回應。
- `0.26.0`、本地 cache、原始 Option Chain 與輸出包均不得進入 git 或 Docker build context。

## 回測與啟用門檻

新特徵先以候選模式執行，不因資料存在就直接改變正式機率：

1. 使用現有 walk-forward 與五日 gap，比較 baseline 與候選模型。
2. 每個 fold 只使用該日期當時已發布的特徵；禁止用目前 Option Chain 回填過去。
3. 主要指標為 OOS Brier score；同時檢查 accuracy、最大回撤、交易數與產業分布。
4. 候選模型只有在測試股票的 median Brier 改善，且 accuracy 沒有明顯惡化時才啟用。
5. 若結果未改善，資料仍可供 Web 解釋，但不加入 `MODEL_FEATURES`。

回測報告在本機產生，不放在使用者網頁請求內。網頁只顯示已發布的模型版本、資料日期及是否有個股選擇權覆蓋。

## 錯誤處理與回復

- Alpaca 401／403：立即停止，不重試並提示本機憑證問題。
- Alpaca 429／5xx：遵守退避與 `Retry-After`，保留 checkpoint 後停止或續跑。
- 單一股票資料異常：隔離該 symbol，不影響其他輸出。
- 上傳中斷：不更新 manifest；Cloud Run 繼續讀舊版本。
- 新模型上線後指標異常：停用候選特徵開關並保留資料檔，不需回滾整個應用。

## 測試

- Black-Scholes、IV 二分反解及不可解價格的純函式測試。
- Option symbol、到期日、moneyness、Smile、期限斜率與量能聚合測試。
- 利率資料延後一日與 backward-only 對齊測試。
- JSON schema、gzip 解壓大小、SHA-256、未來日期與非有限數值拒絕測試。
- 429 checkpoint／resume、單股隔離及 manifest-last 發布測試。
- baseline／candidate walk-forward 比較測試。
- Cloud Run 缺 bucket、缺 symbol、過期 manifest 與 GCS 失敗時的中性降級測試。

## 實作階段

1. 建立本地安全抓取、利率解析、聚合與 dry-run，不上傳、不改模型。
2. 建立私人 GCS、最小 IAM、manifest-last 上傳與 Cloud Run 唯讀載入。
3. 回補最多 500 檔美股並產生 baseline／candidate 回測報告。
4. 只啟用通過門檻的特徵，部署後驗證台股、美股、LINE webhook 與缺資料降級。
5. 未來若需要 2008 年後完整 Greeks／IV 歷史，再評估 Alpha Vantage premium，不先增加付費依賴。
