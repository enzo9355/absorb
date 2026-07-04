# Stock Papi 本地量化建置器設計

## 決策

將先前因 Cloud Run 1GB RAM、冷啟動、Webhook 時限或 API 配額而縮減的批次工作移至使用者的 Windows 本機。Cloud Run 保留 LINE、Web、提醒、即時輕量查詢與現有降級功能；本機只在 Asia/Taipei 05:30 至 09:30 執行資料建置、模型訓練、回測與上傳。

本文件擴充 `2026-07-04-local-option-data-pipeline-design.md`。選擇權特徵定義沿用該文件；排程、儲存、發布與安全邊界以本文件為準。

## 目標

- 把全市場資料清洗、特徵工程、逐股模型訓練、walk-forward 回測、產業排序、歷史情緒與選擇權聚合移到本機。
- Cloud Run 不再需要為產業排名一次重算多檔股票，也不在使用者請求內啟動重型 NLP 或完整 Option Chain 處理。
- 本機停機、排程超時或上傳失敗時，線上服務仍維持目前功能。
- 所有發布資料可追蹤來源、模型版本、資料日期與完整性，不使用部分寫入或未完成交易日。

## 移至本機的工作

### 市場資料

- 台股 TWSE／TPEx 全市場代碼、OHLCV、成交金額、FinMind 籌碼、外資及融資融券。
- 美股所有資料供應商可驗證的 active common stock 與 ETF；無效、下市、測試代碼及資料不足標的排除。
- 大盤、ETF、VIX、VIX9D、VIX3M、SKEW、美國公債殖利率及市場相關性。
- Alpaca 選擇權日資料、IV Smile、期限結構、Call／Put 量能與權利金不平衡。
- 原始資料在本機依來源與日期快取，Cloud Run 不保存完整原始市場資料。

### 特徵、模型與回測

- 現有技術、成交量、籌碼、市場、資料品質與選擇權特徵。
- 每檔股票 LightGBM 五日方向模型、五日 gap walk-forward、OOS Brier、accuracy、最大回撤、Sharpe、交易數與特徵重要度。
- baseline 與候選特徵比較；候選未通過門檻時只發布解釋資料，不更換正式機率。
- 上傳預測結果與必要的歷史機率，不上傳可執行模型或 pickle。

### 全市場與產業預測

- 台股不再限制每個產業只對前 20 檔做完整回測；本機以逐股、固定記憶體方式處理所有合格標的。
- 美股建立全市場可查詢 universe；個股選擇權特徵只覆蓋有合約與足夠流動性的子集合。
- 產業與主題排名由本機已發布的逐股結果產生，Cloud Run 只讀取排序快照。
- 如果四小時無法每日完成全美股，本機按「最久未更新優先、流動性次之」輪替；每檔結果保留自己的 `as_of`，不把舊資料標成今日資料。

### 新聞與社群情緒

- 本機保存去重後的新聞／社群必要欄位與時間戳，建立逐日情緒歷史。
- 規則分數、來源權重、時間衰減、情緒動能、波動與極端旗標在本機計算。
- 重型中文／英文金融情緒模型只在本機候選流程執行；未通過樣本外回測前不加入正式機率。
- Cloud 只接收逐股每日彙總，不接收完整文章、貼文、作者、帳號或互動者資料。
- 不自動執行未審核模型的 remote code。任何外部模型必須固定版本、確認授權、記錄 SHA-256，且 `trust_remote_code` 保持關閉。

## 保留在 Cloud Run 的工作

- `/callback` LINE webhook、Postback、關注、提醒與推播。
- `/dashboard`、`/stock/<code>` 與 API 顯示。
- Firestore 使用者狀態與提醒資料。
- 讀取最新本地發布的逐股、產業與市場快照。
- 收盤價提醒所需的輕量報價與資料新鮮度檢查。
- 本地資料缺漏、過期或驗證失敗時，沿用目前單股 `analyze()` 流程，不讓服務中斷。
- Papi 的即時自然語言互動；預先計算資料只能作為上下文，不能取代使用者當下問題。

## 每日執行時段

### 硬性時間限制

- 時區固定為 `Asia/Taipei`。
- Windows Task Scheduler 每日 05:30 觸發。
- 只有 `05:30:00 <= 現在 < 09:30:00` 才允許啟動高負載工作；程式本身再次檢查時間，不能只依賴排程器。
- 09:20 停止領取新的股票或批次單元。
- 09:25 完成目前原子單元、寫入 checkpoint、關閉檔案與停止網路重試。
- 09:30 Task Scheduler 強制終止仍未結束的程序，最長執行時間四小時。
- 錯過 05:30 不在白天補跑；等下一個排程窗口。
- 同一時間只允許一個實例；既有 lock 尚有效時新實例立即退出。
- 排程使用 Below Normal 優先權、限制並行數，且不在非 AC 電源狀態啟動重型工作。

### 美股收盤處理

NYSE 一般交易時段於美東時間 16:00 收盤，換算台北時間為夏令時間 04:00、冬令時間 05:00。Alpaca Indicative trades 另有 15 分鐘延遲，因此固定從 05:30 開始，全年均晚於一般尾盤與資料延遲。流程仍不得只靠固定時鐘猜測資料完整：

- 查詢交易日曆與資料來源 watermark。
- 只有交易所 session 已結束、供應商延遲時間已過且 OHLCV 完整時，才把該美股日期標記為 completed。
- 05:30 仍未確認完整的美股交易日先處理台股、歷史回補與新聞，該美股日期延至下一晚。
- 09:20 前仍未確認完整的美股交易日不發布，不把盤中資料當成日資料。
- 台股與美股各自保存 `market_as_of`，不能共用一個看似最新的日期。

## 工作優先順序

每晚依序執行，時間不足時低優先工作保留 checkpoint：

1. 安全前置檢查、憑證存在性、磁碟空間、時間窗、lock 與來源健康度。
2. 台股與已完成美股交易日的增量資料。
3. 既有 universe 的特徵更新、正式模型預測與必要回測。
4. 產業、主題與市場排名快照。
5. 新聞／社群每日彙總與已核准情緒候選模型。
6. 選擇權聚合與個股選擇權候選特徵。
7. 新股票初始回補、長期歷史補洞與候選模型研究。
8. 完整驗證後發布；09:20 後不開始發布以外的新工作。

初始全市場建置允許跨多個夜晚完成。未達發布條件前只保留本機 checkpoint，線上服務繼續使用既有版本。

## 本地執行模型

### 固定記憶體處理

- universe 只保存代碼與輕量 metadata。
- 每次讀取、清洗、訓練並輸出一檔股票，完成後釋放 DataFrame 與模型。
- 不把全市場歷史同時載入記憶體。
- I/O 可使用少量有界執行緒；模型訓練預設單進程，避免記憶體與 CPU 同時暴增。
- 每完成一檔寫入 checkpoint；程序中斷後從下一檔續跑。

### 更新策略

- 價格、籌碼、新聞與選擇權資料採增量追加，不每晚重新下載全部歷史。
- 沒有新增完成交易日的股票不重訓。
- 正式 LightGBM 設定與 feature schema 產生穩定版本號。
- 深度情緒模型與新特徵先跑 candidate，不覆蓋 production。
- 只有資料 schema、模型版本、回測門檻及完整性檢查全部通過才進入發布集合。

## 發布資料

Cloud Run 需要的逐股檔案包含：

- `market`、`symbol`、`name`、`sector`、`as_of`。
- 最新價格、正式五日機率、趨勢、技術指標、籌碼與外資摘要。
- OOS 回測指標、特徵重要度、歷史機率與資料覆蓋率。
- 新聞／社群情緒彙總、來源覆蓋與資料日期。
- 利率、VIX、SKEW 與可用的個股選擇權聚合特徵。
- `data_quality`、`missing_features`、`model_version` 與 `generated_at`。

產業快照只保存排序、分數拆解、資料日期與逐股物件的版本引用，不重複保存完整歷史。

## 私有 GCS 版本格式

採內容定址物件，避免部分上傳覆蓋線上版本：

```text
gs://<bucket>/quant/v1/objects/<sha256>.json.gz
gs://<bucket>/quant/v1/manifests/<run_id>.json
gs://<bucket>/quant/v1/latest.json
```

發布順序：

1. 產生逐股與市場 JSON，gzip 後計算 SHA-256。
2. 上傳不存在的 `objects/<sha256>.json.gz`；物件不可原地覆寫。
3. 產生 manifest，引用新物件與可沿用的舊物件。
4. 驗證 manifest 中每個物件的大小、SHA、schema、日期與市場。
5. 上傳 immutable manifest。
6. 使用 GCS generation precondition 最後更新 `latest.json`。

中斷發生在第 6 步以前時，Cloud Run 仍讀舊版本。`latest.json` 只保存 manifest 路徑、雜湊、產生時間與各市場 watermark。

## 安全邊界

### 憑證

- Alpaca 等 API 金鑰不寫入 repo、Task Scheduler XML、命令列參數或日誌。
- Windows 排程以專用使用者執行；秘密使用 Windows DPAPI 綁定該使用者與機器，由啟動 wrapper 只在子程序環境中注入。
- 本機使用既有 gcloud 使用者 OAuth 上傳，不建立或下載長效 service-account JSON。
- 本機 principal 只有指定 GCS prefix 的建立權限；Cloud Run service account 只有 object viewer。
- 不建立公開上傳 HTTP endpoint。

### 外部資料

- 所有 HTTP 請求有 timeout、回應大小、頁數、重試次數與 `Retry-After` 上限。
- 401／403 不重試；429／5xx 有界退避並保存 checkpoint。
- symbol、日期、URL、檔名與 GCS object path 使用 allowlist 驗證，禁止 path traversal。
- XML 使用現有 defusedxml；JSON 只接受固定 schema、有限數值與合理日期。
- 不把未完成交易日、未來日期、NaN、Infinity、重複主鍵或異常價格發布。

### 產物

- 僅使用 JSON + gzip，不使用 pickle、joblib 或可執行模型反序列化。
- Cloud Run 解壓前檢查壓縮大小，串流解壓並限制最大輸出。
- Cloud Run 依 manifest 驗證 SHA-256，驗證失敗即拒絕該物件並降級。
- 本地原始資料、cache、checkpoint、DPAPI 秘密及輸出目錄加入 `.gitignore` 與 `.dockerignore`。
- `0.26.0` 保持未追蹤，不納入任何提交、資料發布或 Docker context。

### 隱私

- 本機批次不讀取 LINE userId、關注清單、提醒或使用者投資金額。
- 股票處理優先順序只依資料新鮮度、流動性與市場 universe，不依個別使用者行為。
- 新聞與社群上雲前移除作者、帳號、完整內文與互動者，只保留聚合數值與來源類別。

## Cloud Run 讀取與降級

- 啟動時不下載全市場資料。
- `latest.json` 與 manifest 有短期記憶體快取；逐股物件按需取得並限制 cache 數量。
- snapshot 新鮮且 schema 相容時，`analyze()` 優先使用預先計算結果。
- snapshot 缺失、過期、雜湊錯誤、網路失敗或模型版本不支援時，沿用目前即時單股流程。
- 產業頁在本地快照不可用時沿用目前 Firestore sector snapshot。
- UI 顯示每個市場與個股的實際資料日期，不把 fallback 描述成最新本地模型。
- 本地建置器不是線上服務依賴；電腦關機不會讓 LINE webhook 或 Web 失效。

## 發布門檻

一次 run 只有符合下列條件才更新 `latest.json`：

- 所有必要市場基準資料通過 schema 與日期驗證。
- 正式 universe 已完成本次排程要求的增量資料，或 manifest 明確沿用上一版物件。
- 新物件 SHA-256、gzip、JSON 與行數驗證成功。
- 正式模型測試通過，候選模型沒有未核准地取代 production。
- 產業快照引用的逐股版本存在。
- `generated_at` 在 05:30 至 09:30 允許時間窗內，且各市場 watermark 不超過資料來源完成日期。

部分股票失敗可以沿用上一版逐股物件，但 manifest 必須列出 `stale_symbols` 與原因；不能用空值覆蓋有效舊資料。

## 失敗與復原

- 本機停機或錯過時段：不補跑，Cloud 使用上一版。
- 09:25 仍在處理：完成目前原子寫入、checkpoint 後退出，不更新 `latest.json`。
- API 限流：記錄下次 page token 與 symbol，下一晚續跑。
- 磁碟空間低於安全門檻：停止下載與訓練，只保留 checkpoint，不刪除上一版必要資料。
- 單股資料損壞：隔離該 symbol，沿用線上舊物件。
- manifest 或 GCS 發布失敗：不切換 latest。
- 新版本線上異常：把 latest 指回上一個已驗證 manifest，不需重新部署 Cloud Run。

## Windows 排程驗證

- 05:29 手動啟動必須拒絕高負載工作。
- 05:30 可取得單一 lock 並開始。
- 第二個實例必須立即退出。
- 09:20 後不得領取新 symbol。
- 09:25 必須產生可續跑 checkpoint。
- 09:30 排程器終止殘留程序。
- 白天開機或錯過排程不得自動補跑。
- 本機時區錯誤、時間倒退或 DST 對美股日期造成疑義時不得發布。

## 測試

- 時間窗、deadline、lock、checkpoint、resume 與單一實例純函式測試。
- 台股／美股 universe、下市代碼、重複資料與未完成 session 測試。
- 逐股固定記憶體處理與中斷續跑測試。
- 現有 LightGBM baseline 與本地結果一致性測試。
- 情緒去重、時間衰減、來源權重與無 PII 聚合測試。
- 選擇權、利率及 backward-only 對齊測試。
- gzip 大小、JSON schema、SHA-256、content-addressed object 與 generation precondition 測試。
- manifest 沿用舊物件、stale symbol、部分失敗與 rollback 測試。
- Cloud Run snapshot 優先、過期、缺漏、損壞及現有流程 fallback 測試。
- LINE callback、提醒、台股、美股與產業頁完整回歸測試。

## 分階段實作

1. 建立 Windows 05:30–09:30 安全 runner、lock、checkpoint、時間 guard 與 dry-run。
2. 把現有台股／美股資料取得、特徵、LightGBM 與回測封裝成逐股本地批次，先不改 Cloud Run。
3. 建立內容定址 GCS、最小 IAM、manifest-last 發布與 Cloud Run 唯讀降級載入。
4. 先完成台股全市場增量與產業排名，取代 Cloud Run 每產業 20 檔重算。
5. 建立美股全市場輪替、官方利率與 Alpaca 選擇權子集合。
6. 建立新聞／社群每日歷史與本地重型情緒候選流程。
7. 執行 baseline／candidate 回測，只啟用通過門檻的新增特徵。
8. 部署 Cloud Run 並驗證本機關機、資料過期、GCS 故障與 rollback 時仍維持目前功能。

## 時段依據

- NYSE Trading Information：Core Trading Session 為美東時間 09:30–16:00，Closing Auction 為 16:00。<https://www.nyse.com/trade/trading-information>
- Alpaca Historical Option Data：免費 Indicative trades 為衍生資料且延遲 15 分鐘。<https://docs.alpaca.markets/us/docs/historical-option-data>
