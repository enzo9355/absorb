# 專案測試與說明報告

測試日期：2026-05-17  
測試環境：Windows / PowerShell / Python 3.12.10  
專案位置：`C:\Users\User\OneDrive\Desktop\linestockbot-test`

## 一句話結論

這是一個以 Flask 寫成的 LINE 股票分析機器人與網頁報告服務。使用者可以在 LINE 輸入股票代碼、股票名稱、大盤指令或產業分類指令，系統會抓取台股歷史價格、計算技術指標、用 LightGBM 做簡易機器學習預測與回測，並產生一個可由瀏覽器查看的股票分析頁。

## 專案檔案

- `app.py`：主程式，包含 Flask app、LINE webhook、資料抓取、AI 模型、回測、HTML 報告渲染。
- `requirements.txt`：Python 套件依賴。
- `templates/stock.html`：一個 Bootstrap 股票分析頁模板，但目前主程式沒有使用它；目前頁面是由 `render_template_string()` 直接在 `app.py` 內產生。
- `taipei_sans.ttf`：字型檔，目前在 `app.py` 中沒有看到被使用。
- `.venv/`：本次測試建立的本地虛擬環境。

## 主要功能

### 1. LINE Bot 指令

`app.py` 使用 `line-bot-sdk` 建立 LINE webhook：

- `POST /callback`：LINE webhook 入口。
- 使用者輸入 `大盤` 或 `大盤預測`：分析台股加權指數。
- 使用者輸入 `預測`：回傳產業分類 Quick Reply。
- 使用者輸入 `分類第_N頁`：切換產業分類頁面。
- 使用者輸入 `產業列表`：列出產業分類。
- 使用者輸入 `選產業_分類名稱`：列出該分類前 10 檔股票。
- 使用者輸入股票代碼，例如 `2330`：分析該股票。
- 使用者輸入股票名稱，例如 `台積電`：搜尋股票代碼後分析。
- 使用者輸入 `免責聲明`：回傳投資風險聲明。

### 2. 網頁分析報告

Flask 提供這些主要路由：

- `GET /market`：產生台股大盤分析頁。
- `GET /stock/<code>`：產生指定股票分析頁，例如 `/stock/2330`。
- `GET /broadcast_weekly?token=...`：發送 LINE 群發週報。
- `POST /callback`：LINE webhook。

分析頁會顯示：

- 股票名稱與代碼
- 最新收盤價
- 多頭/空頭趨勢
- AI 預測勝率
- MA20、RSI 等技術摘要
- Lightweight Charts 互動 K 線圖
- AI 5 日預測線
- AI_P 歷史機率柱狀圖
- LightGBM 特徵重要度
- 回測報告：策略報酬、買進持有報酬、勝率、交易次數、最大回檔、夏普值
- Google News RSS 相關新聞
- Gemini 文字觀點；如果沒有設定 `GEMINI_API_KEY`，會顯示「未設定 API Key，無法生成觀點。」

## 資料與模型流程

### 資料來源

`get_data(code, days=730)` 會抓近 730 天資料：

1. 優先使用 FinMind API：`TaiwanStockPrice`
2. 如果 FinMind 失敗，改用 `yfinance`
   - 大盤：`^TWII`
   - 個股：`<code>.TW`，例如 `2330.TW`

`get_news(name)` 會從 Google News RSS 搜尋 `股票名稱 股票`，最多取 5 則新聞。

### 指標計算

`calc_all(df)` 會計算：

- `MA_5`：5 日均線
- `MA20`：20 日均線
- `RET_1`：單日報酬率
- `RSI`：14 日 RSI
- `Volat`：20 日報酬率波動度

### AI 模型

`run_ai_engine(df)` 使用 `LightGBM LGBMClassifier`：

- 特徵：`MA_5`、`MA20`、`RET_1`、`RSI`、`Volat`
- 目標：未來 5 天收盤價是否高於今天
- 訓練/測試切分：前 80% 訓練，後 20% 回測
- 輸出每一天的上漲機率 `AI_P`
- 當 `AI_P > 60` 時視為策略進場訊號

### 快取

`analyze(code)` 會使用 `_SYSTEM_CACHE` 做記憶體快取：

- 快取 key：股票代碼
- 快取時間：3600 秒，也就是 1 小時
- 目的：降低外部 API 呼叫與 LINE webhook 超時風險

## 環境變數

必要：

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`

可選：

- `FINMIND_USER`
- `FINMIND_PASSWORD`
- `GEMINI_API_KEY`
- `BROADCAST_TOKEN`，未設定時預設為 `default_secret`
- `PORT`，未設定時預設為 `5000`

重要：目前 `app.py` 在 import 階段就會建立 `LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)` 和 `WebhookHandler(LINE_CHANNEL_SECRET)`。如果沒有設定 LINE 相關環境變數，程式會直接 import 失敗。

## 本次測試步驟

### 1. 建立虛擬環境

```powershell
python -m venv .venv
```

### 2. 安裝依賴

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

安裝成功，主要套件包含：

- Flask
- line-bot-sdk
- requests
- pandas
- numpy
- twstock
- yfinance
- lightgbm
- scikit-learn
- google-generativeai

### 3. 語法編譯檢查

```powershell
.\.venv\Scripts\python.exe -m py_compile .\app.py
```

結果：通過。

### 4. 無環境變數匯入測試

直接 import：

```powershell
python -c "import app"
```

結果：失敗。錯誤原因是 `LINE_CHANNEL_ACCESS_TOKEN` 為 `None`：

```text
TypeError: can only concatenate str (not "NoneType") to str
```

### 5. 使用假 LINE 環境變數匯入測試

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN='dummy-token'
$env:LINE_CHANNEL_SECRET='dummy-secret'
.\.venv\Scripts\python.exe -c "import app; print(app.app.url_map)"
```

結果：成功。

偵測到的路由：

- `/broadcast_weekly`
- `/callback`
- `/market`
- `/stock/<code>`
- `/static/<path:filename>`

### 6. 股票搜尋測試

測試結果：

- `2330` => `('2330', '台積電')`
- `台積電` => `('2330', '台積電')`
- `TAIEX` => `('TAIEX', '台股大盤')`
- 不存在的股票名稱 => `(None, None)`

### 7. 產業分類測試

`twstock.codes` 可建立產業分類。

本次測到：

- 分類數：40
- 全市場：2104 檔
- 電子零組件業：211 檔
- 半導體業：200 檔
- 生技醫療業：151 檔
- ETF 專區：123 檔
- 光電業：117 檔

### 8. Flask test client 路由測試

測試結果：

- `GET /stock/0000`：HTTP 200，回傳 `查無資料`
- `GET /market`：HTTP 200，成功回傳 HTML 分析頁
- `GET /broadcast_weekly?token=wrong`：HTTP 403，回傳 `身份驗證失敗`
- `POST /callback` 並給錯誤簽章：HTTP 400，符合預期

### 9. 實際分析測試

測試時未設定 `GEMINI_API_KEY`，所以文字觀點回傳「未設定 API Key，無法生成觀點。」這是預期行為。

#### TAIEX 大盤

- 分析成功：是
- 耗時：約 2.03 秒
- 名稱：台股大盤
- 最新點位：41172.36
- AI 預測勝率：45%
- 趨勢：多頭
- RSI：67.27
- 回測天數：93
- 策略交易次數：2
- AI 策略報酬：2.22%
- 買進持有報酬：48.66%
- 進場勝率：100.0%
- 最大回檔：0.0%
- 夏普值：2.12
- 新聞數：5
- K 線資料筆數：462

#### 2330 台積電

- 分析成功：是
- 耗時：約 1.34 秒
- 名稱：台積電
- 最新收盤價：2265.00
- AI 預測勝率：9%
- 趨勢：多頭
- RSI：56.45
- 回測天數：93
- 策略交易次數：2
- AI 策略報酬：4.20%
- 買進持有報酬：58.39%
- 進場勝率：100.0%
- 最大回檔：0.0%
- 夏普值：2.32
- 新聞數：5
- K 線資料筆數：462

注意：以上行情數字是本次測試當下外部資料源回傳的結果，之後會隨資料源更新而改變，不應視為固定值或投資建議。

## 如何本機啟動

PowerShell 範例：

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN='你的 LINE Channel Access Token'
$env:LINE_CHANNEL_SECRET='你的 LINE Channel Secret'
$env:GEMINI_API_KEY='你的 Gemini API Key'
$env:BROADCAST_TOKEN='自訂廣播密碼'
.\.venv\Scripts\python.exe .\app.py
```

啟動後預設網址：

```text
http://127.0.0.1:5000/market
http://127.0.0.1:5000/stock/2330
```

如果只是本機測網頁，LINE token 可以先用假值：

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN='dummy-token'
$env:LINE_CHANNEL_SECRET='dummy-secret'
.\.venv\Scripts\python.exe .\app.py
```

但若要真的接 LINE webhook，一定要填入有效 token，並且需要把本機服務透過 ngrok、Cloudflare Tunnel 或正式部署網址公開給 LINE 呼叫。

## 部署注意事項

`requirements.txt` 包含 `gunicorn`，看起來是準備部署到 Linux 平台，例如 Render。

Linux/Render 類平台可使用類似：

```bash
gunicorn app:app
```

Windows 本機不適合用 gunicorn，直接用：

```powershell
.\.venv\Scripts\python.exe .\app.py
```

## 目前看到的問題與風險

### 1. 沒有 LINE 環境變數會直接啟動失敗

目前 `app.py` 在 import 階段直接建立 LINE API 物件，所以只要沒設 `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_CHANNEL_SECRET` 就會炸掉。這對本機測試、CI、健康檢查都不太友善。

建議改善：

- 啟動時明確檢查必要環境變數並給出好懂錯誤訊息。
- 或延後到真正需要呼叫 LINE API 時才建立 client。

### 2. 依賴沒有鎖版本

`requirements.txt` 只有套件名稱，沒有固定版本。這次測試時安裝到非常新的套件版本，例如 pandas 3.x、numpy 2.x。未來如果套件 API 變動，專案可能突然壞掉。

建議改善：

- 產生固定版本的 `requirements.txt`
- 或使用 `pip-tools` / Poetry / uv 管理 lock file

### 3. `google.generativeai` 已出現棄用警告

匯入時看到警告：

```text
All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package as soon as possible.
```

短期仍可跑，但中長期建議改到新版 Gemini SDK。

### 4. 沒有自動化測試

目前專案沒有 pytest 或其他測試檔。本次測試是手動用 `py_compile`、匯入測試、函式呼叫與 Flask test client 完成。

建議新增：

- `tests/test_app.py`
- mock 外部 API，避免測試依賴 FinMind、Yahoo、Google News
- 測 `search_stock_code`
- 測 `calc_all`
- 測 `run_ai_engine` 在資料不足時回傳 `None`
- 測 `/market`、`/stock/<code>` 路由

### 5. 外部服務很多，正式環境需要容錯

專案依賴：

- FinMind
- Yahoo Finance
- Google News RSS
- Gemini
- LINE Messaging API
- CDN：Google Fonts、Lightweight Charts

目前多數函式用 `try/except: pass` 吃掉錯誤，雖然使用者體驗較不會崩，但正式維運時不容易知道到底是哪個 API 壞了。

建議改善：

- 加上 logging
- 區分資料抓不到、API timeout、格式變更、模型失敗
- 在頁面或 LINE 訊息中給出較明確狀態

### 6. 回測結果容易被誤讀

本專案的 AI 預測與回測比較像研究展示，不是完整交易系統。尤其目前回測交易次數可能很少，例如本次 TAIEX 和台積電都只有 2 次進場訊號，勝率 100% 不代表模型可靠。

建議在頁面上更明確標示：

- 僅供研究參考
- 不構成投資建議
- 回測不代表未來績效
- 交易次數過少時，勝率參考價值有限

### 7. `templates/stock.html` 目前未被使用

主程式沒有使用 `render_template()`，而是用 `render_template_string()` 在 `app.py` 直接組 HTML。`templates/stock.html` 目前像是舊版或備用頁面。

建議：

- 如果不用，移除避免混淆。
- 如果要保留，改成真正使用 Flask template，讓 HTML 與 Python 邏輯分離。

## 總結

這個專案目前可以成功執行核心流程：抓台股資料、計算指標、訓練 LightGBM、回測、產生網頁報告，並具備 LINE Bot 指令入口。  

本次測試確認 `/market`、`/stock/<code>`、`/callback`、`/broadcast_weekly` 基本行為都可運作或符合預期。主要阻礙是本機環境一開始沒有依賴套件，以及沒有設定 LINE 環境變數時會直接 import 失敗。若要正式部署，最優先應補上環境變數檢查、版本鎖定、logging 與基本自動化測試。
