# AI Quant Investment LINE Bot

一個面向股票新手的台股與美股量化分析 LINE Bot。它把技術指標、模型機率、新聞／輿論情緒、法人籌碼與回測結果整理成容易理解的 LINE 卡片與 Web 分析頁，讓使用者可以先在 LINE 快速操作，再到 Web 查看完整圖表與細節。

> 本專案提供的資訊僅供研究與學習參考，不構成投資建議；投資決策與盈虧需由使用者自行承擔。

## 主要功能

- LINE 股票查詢
  - 輸入台股代碼、名稱或標準美股代碼，例如 `2330`、`台積電`、`AAPL`、`NVDA`
  - 回覆最新收盤價、五日上漲機率、趨勢、新聞／輿論情緒與操作按鈕
  - 情緒採 0～100 分與五級標籤，並顯示正負比例、來源數及資料可信度

- 六格 Rich Menu
  - 看大盤
  - 找機會
  - 查自選
  - 設提醒
  - 算報酬
  - 深度分析

- 關注清單與提醒
  - 在 LINE 內加入 / 移除關注股票
  - 支援股價門檻、機率門檻、趨勢提醒
  - 使用 Firestore 保存每位 LINE 使用者狀態

- 強勢訊號
  - 針對使用者自己的關注清單排序
  - 依五日上漲機率挑出目前較強的標的

- 全市場產業預測
  - 每日從證交所與櫃買中心整批行情涵蓋上市、上櫃股票
  - 先依成交金額與成交量挑出活躍候選，再執行完整模型與回測
  - LINE 顯示排序後前 10 檔，避免 1GB Cloud Run 對全市場逐檔重算

- 投資試算
  - 股票卡內可點「投資試算」
  - 預設金額：1 萬、5 萬、10 萬
  - 也支援自訂文字格式：`試算 2330 100000`
  - 估算約可買股數、AI 策略歷史損益、買進持有歷史損益

- Web 完整分析頁
  - `/`、`/dashboard`：股票搜尋、市場摘要、LINE 管理關注說明、產業預測、精選標的、新手投資小辭典
  - 搜尋支援台股代碼／名稱與美股代碼，例如 `2330`、`台積電`、`AAPL`
  - `/stock/<code>`：快速導覽、Papi 判讀、互動式 K 線圖、五日預測軌跡、技術指標、投資金額快捷試算、歷史回測、外資買賣超、情緒量化拆解、新聞篩選與風險提示
  - `/market`：台股大盤分析

## 技術架構

```text
LINE 使用者
  │
  ▼
LINE Messaging API
  │
  ▼
Flask / Gunicorn on Cloud Run
  ├─ 股票資料：FinMind、twstock、yfinance、TWSE／TPEx OpenAPI
  ├─ 輿論資料：Google News RSS、選用 MarketAux、美股 StockTwits
  ├─ 量化模型：LightGBM + scikit-learn
  ├─ 狀態儲存：Firestore REST API
  ├─ 定時提醒：Cloud Scheduler → /tasks/check-alerts
  └─ Web UI：Jinja templates + Vanilla JS + Lightweight Charts
```

設計原則：

- LINE 負責快速互動：關注、提醒、強勢訊號、投資試算入口。
- Web 負責完整分析：搜尋、圖表、回測、模型解釋、籌碼、情緒與風險提示。
- 避免增加重型 NLP / ML 套件，降低 Cloud Run 冷啟動與記憶體壓力。
- Webhook 路徑保持輕量，避免 LINE 5 秒 timeout。

## Web 與 LINE 分工

- LINE：加入關注、提醒管理、產業預測入口
- Web：股票搜尋、完整圖表、新聞／輿論情緒拆解、回測與白話解讀

Web 不建立第二套登入、關注清單或提醒狀態。使用者在 LINE 管理個人功能，網站只呈現可分享的詳細分析，避免兩端資料不同步。

## 核心檔案

| 檔案 | 說明 |
| --- | --- |
| `app.py` | Flask app、LINE webhook、股票分析、Flex Message、Web routes |
| `line_state.py` | LINE 使用者狀態、Firestore REST 存取、關注與提醒規則 |
| `templates/` | Dashboard 與個股分析頁 |
| `static/app.js` | Dashboard 載入、K 線圖、投資金額即時計算、新聞情緒篩選 |
| `static/app.css` | Web UI 樣式 |
| `tests/` | unittest 測試 |
| `Dockerfile` | Cloud Run 部署映像 |
| `docs/line-to-web-map.md` | LINE 與 Web 分工規格 |

## 環境變數

必要：

| 變數 | 說明 |
| --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API access token |
| `LINE_CHANNEL_SECRET` | LINE webhook signature secret |
| `GEMINI_API_KEY` | Gemini API key，用於生成摘要觀點 |

選用：

| 變數 | 說明 |
| --- | --- |
| `FINMIND_USER` | FinMind 帳號，用於取得 token |
| `FINMIND_PASSWORD` | FinMind 密碼 |
| `MARKETAUX_API_TOKEN` | 選用的 MarketAux 金鑰；啟用第二新聞來源與外部情緒交叉驗證 |
| `GCP_PROJECT_ID` | 啟用 Firestore 關注與提醒功能 |
| `QUANT_SNAPSHOT_BUCKET` | 私有 GCS 回測快照 bucket；設定後優先讀取本地發布結果 |
| `ALERT_TASK_TOKEN` | Cloud Scheduler 呼叫 `/tasks/check-alerts` 的 Bearer token |
| `BROADCAST_TOKEN` | 週報廣播端點驗證 token |
| `HOST` | 本機開發綁定 host，預設 `127.0.0.1` |
| `PORT` | 服務 port，Cloud Run 會自動注入 |

不要把任何 token、密碼或金鑰提交到 Git。

## 本機開發

建議使用 Python 3.10。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:LINE_CHANNEL_ACCESS_TOKEN="test"
$env:LINE_CHANNEL_SECRET="test"
python app.py
```

預設啟動於：

```text
http://127.0.0.1:5000
```

## 測試

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN="test"
$env:LINE_CHANNEL_SECRET="test"
python -m unittest discover -s tests -v
python -m py_compile app.py line_state.py
node --check static/app.js
git diff --check
```

如果使用外部依賴安裝目錄，例如 `.deps`：

```powershell
$env:PYTHONPATH="C:\Users\enzo\Documents\line bot\.deps"
python -m unittest discover -s tests -v
```

## 部署

目前專案以 Dockerfile 部署到 Google Cloud Run。

```powershell
gcloud run deploy line-stock-bot `
  --source . `
  --region asia-east1 `
  --project line-stock-bot-498908 `
  --allow-unauthenticated
```

正式服務會由 Cloud Run 注入 `$PORT`，Dockerfile 透過 Gunicorn 綁定：

```text
gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
```

## LINE 使用方式

常用文字：

| 輸入 | 行為 |
| --- | --- |
| `2330` | 查詢台積電 |
| `今日盤勢` | 查看台股大盤；圖文選單顯示為「看大盤」 |
| `預測` | 查看產業分類與每日產業預測；圖文選單顯示為「找機會」 |
| `我的關注` | 查看關注清單；圖文選單顯示為「查自選」 |
| `提醒管理` | 查看與取消提醒；圖文選單顯示為「設提醒」 |
| `投資試算` | 查看試算操作說明；圖文選單顯示為「算報酬」 |
| `試算 2330 100000` | 以 100000 元試算 2330 |
| `完整分析` | 開啟 Web 儀表板；圖文選單顯示為「深度分析」 |
| `功能選單` | 預覽六格功能選單 |

## 資料與模型說明

- 預測目標：未來五個交易日方向。
- 模型：LightGBM binary classifier。
- 驗證：時間序列切分，避免用未來資料訓練過去。
- 回測：使用五日報酬，並扣除估計交易成本。
- 輔助特徵：
  - 均線、RSI、MACD、KD、波動率
  - 成交量變化
  - 法人 / 外資買賣超
  - 融資與融券變化
  - Cboe VIX 水準、1 日／5 日變化與 VIX9D／VIX3M 期限結構

外資買賣超目前作為輔助判讀與模型特徵之一，不會單獨構成買賣建議。
VIX 特徵只使用該交易日或前四個日曆日內已公布的歷史值，並同時套用於台股與美股模型；資料缺漏時改用中性值及缺漏旗標，不會使用未來資料補值。

## 安全與維運注意事項

- `/callback` 會驗證 LINE signature。
- `/tasks/check-alerts` 僅接受 `Authorization: Bearer <ALERT_TASK_TOKEN>`。
- Firestore 資料只保存 LINE userId 對應的關注、提醒與快照，不保存使用者個人投資紀錄。
- Rich Menu 可透過 LINE Messaging API 更新；若只改 LINE Official Account Manager 後台圖片，repo 不會自動同步。
- 若 Cloud Run source deploy 發生暫存 bucket 權限問題，需確認 Cloud Run / Compute service account 是否具備必要的 Storage object 讀取權限。

### 本地量化建置器

- 所有本地市場資料、cache、checkpoint、候選模型與發布產物固定放在 `D:\StockPapiData`，不寫入 C 槽 repo。
- Windows 排程 `StockPapi-LocalQuant` 每日台北時間 02:30 啟動台股；台股完成後若尚未到 05:30，先等待美股收盤緩衝時間，再開始美股。09:20 停止領取新股票，09:30 強制結束；錯過時段不在白天補跑。
- 每晚依序處理台股與美股 universe，直到兩個市場完成或時段結束；逐檔產生 730 日特徵、五日預測、回測與 gzip JSON 快照，未完成時隔日從各市場 checkpoint 續跑。台股若占滿時段，美股會安全延至隔日，不使用未收盤資料。
- 台股 artifact 位於 `artifacts/stocks/TW`，美股位於 `artifacts/stocks/US`；台股進度使用 `progress.json`，美股使用 `progress-US.json`，互不覆蓋。
- 美股清單每日取自 SEC 官方 company ticker/exchange JSON，只保留 Nasdaq、NYSE、CBOE，排除 OTC 與明確虛擬貨幣標的；下載失敗時使用 D 槽前次成功快取。
- 每檔完成即原子寫入並保存 checkpoint。單檔資料源失敗會隔離記錄，磁碟寫入失敗則立即停止，避免錯誤略過或產物損壞。
- 前一批失敗股票會在同市場下一次執行時優先重試；成功後才從 checkpoint 移除，避免全市場回補期間長期遺漏個股。
- 市場 universe 全部嘗試後，只要失敗率嚴格低於 5%，就會在 `publish/quant/v1` 建立內容雜湊物件、immutable manifest 與原子 `latest-TW.json`／`latest-US.json`；manifest 會列出覆蓋率與缺漏代碼。失敗率達 5%、gzip 損壞、schema 不符或 SHA 驗證失敗時保留上一版。
- Windows 排程 `StockPapi-QuantUpload` 每日 09:35 執行，只讀取 `D:\StockPapiData\publish\quant\v1`，依物件、manifest、`latest` 順序上傳到私有 GCS。上傳器不刪檔、不遞迴同步，也不保存 service-account key。
- Cloud Run 每次只下載單一股票 artifact，驗證 SHA-256、大小、gzip、schema、日期及 manifest 覆蓋率後使用；缺漏或過期股票自動改用即時計算。個股頁會標示「本地回測快照」或「即時計算」。
- 排程本身不保存 API key；TEMP、Python、yfinance 與模型 cache 都由 wrapper 指向 D 槽。
- 每次正式執行會先清除 `cache/tmp` 超過 1 天、`cache/pycache`、`raw`、`logs`、`publish` 超過 30 天，以及超過 7 天的 stale lock。清理固定限制在 `D:\StockPapiData` allowlist，且不跟隨 symlink／junction。
- `secrets`、股票 artifact、`progress.json` 與目前的 runner lock 不會自動刪除。
- 安裝或重新驗證：`powershell -ExecutionPolicy Bypass -File .\scripts\install_local_quant_task.ps1`。可用 `Get-ScheduledTaskInfo 'StockPapi-QuantUpload'` 查看下次上傳時間。

## 目前限制

- 預測與回測不代表未來績效。
- 新聞／輿論情緒是輔助資訊，不會直接覆蓋模型機率。除五級方向外，系統另計算情緒動能、加權波動、正負分歧、有效樣本數、發布者覆蓋與 metadata 缺漏率，先作為候選因子累積驗證。
- 情緒資料限制在可判定日期的近 30 日，依標題詞組、否定詞、事件類型、時間與來源完整度加權；預設使用 Google News RSS，設定 `MARKETAUX_API_TOKEN` 後會合併 MarketAux 結構化新聞並去重。
- 經驗證的美股代碼會額外讀取 StockTwits 公開 symbol stream，只保存匿名 Bullish／Bearish 彙總。這是自陳的散戶情緒，來源權重低於新聞，端點失敗時安全略過。
- 近 30 日、多來源、互動量與來源品質的設計參考 [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)；未將完整 agent 引擎或其額外依賴放進 Cloud Run。
- FinMind 或 Yahoo 資料缺漏時，部分籌碼或價格資訊可能暫時不可用。
- VIX 期限結構是整體市場風險偏好的代理指標，不等同個股即時 options flow、未平倉量、GEX、Vanna flow 或 0DTE 流量。
- 美股目前支援標準英文字母代碼直接查詢；本地建置器會依 SEC universe 逐夜增量掃描。美股外資、融資融券欄位會顯示資料不足。
- Cloud Run scale-to-zero 會有冷啟動；新增功能時應避免模組載入階段做重運算或網路請求。
