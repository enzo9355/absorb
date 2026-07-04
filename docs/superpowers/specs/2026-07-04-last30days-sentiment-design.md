# Last 30 Days 輿論分析整合設計

## 目標

參考 `mvanhorn/last30days-skill` 的近 30 日、多來源、時間衰減、互動量與來源可信度方法，強化 Stock Papi 的輿論分析，同時維持 Python 3.10、1GB Cloud Run、低冷啟動與既有 LINE 操作流程。

## 採用方案

不把完整 agent skill、Node、瀏覽器或其多來源執行引擎放進 Cloud Run。該專案目前要求 Python 3.12，完整流程也包含大量非股票來源、選用 API 與代理合成，不適合 LINE webhook 即時路徑。

本階段只移植與股票判斷直接相關的最小能力：

- 所有可判定日期的資料限制在近 30 日。
- 保留既有 Google News RSS 與選用的 MarketAux。
- 美股額外讀取 StockTwits 公開 symbol stream；台股不硬套稀疏的英文社群資料。
- 將 StockTwits 自行標記的 Bullish／Bearish 貼文彙總成一筆社群證據，不逐篇塞進 LINE。
- 社群訊號採較低來源權重，並依有效標記數小幅調整權重，避免少量或炒作貼文壓過新聞事件。
- 計算並輸出來源數、社群樣本數與資料窗口，讓可信度可被解讀。

## 資料流程

```text
Google News RSS ─┐
MarketAux ───────┼─> 正規化／30 日過濾／去重 ─> 單篇評分 ─> 加權彙總
StockTwits(美股) ┘                                      │
                                                        ├─> LINE 精簡摘要
                                                        └─> Web 詳細分析
```

StockTwits 回傳失敗、逾時、格式錯誤、無 ticker 或無有效多空標記時回傳空清單；既有新聞流程繼續工作。

## 評分規則

- 新聞維持既有中文金融詞組、否定詞、事件、時間與來源權重。
- StockTwits 原始方向：`(bullish - bearish) / tagged_count`，範圍 -1～1。
- 社群原始方向乘以 0.6，避免自陳標籤與機器人噪音形成過度確定的分數。
- StockTwits 來源權重固定 0.6；有效標記數越多，互動權重由 0.7 漸進至最高 1.0。
- 最終權重：`time × source × event × engagement`。
- 情緒仍只作輔助資訊，不修改 LightGBM 五日上漲機率。

## 輸出

- 原本「新聞情緒」改為「新聞／輿論情緒」。
- 摘要增加來源數；美股有 StockTwits 資料時增加社群樣本數。
- Web 新聞清單可顯示 StockTwits 近 30 日多空摘要與原始連結。
- 沒有社群資料時不顯示空的社群欄位。

## 安全與資源限制

- 不新增套件、資料庫或背景 worker。
- StockTwits 只對已通過既有美股 ticker 驗證的 1～5 碼英文字母呼叫。
- 使用固定 API host、URL 編碼、識別用 User-Agent、短逾時與 `raise_for_status()`。
- 外部文字沿用既有 HTML 跳脫與 LINE JSON 結構，不送入指令執行。
- 不保存作者、帳號或完整貼文；只保留彙總數字，降低隱私與記憶體負擔。

## 測試

- 解析近 30 日 Bullish／Bearish，排除過期、無標記與異常資料。
- StockTwits 只在美股執行，失敗時安全回傳空清單。
- 社群權重低於同等重大新聞，樣本增加時權重不超過上限。
- 跨來源結果保留一筆社群摘要，且近 30 日之外的資料不進入評分。
- LINE／Web 顯示來源與社群樣本，模型機率不受情緒值反向修改。
- 完整測試、`git diff --check`、部署後健康檢查與公開股票頁驗證。

## 本階段不做

- 不整合 X、TikTok、Instagram、YouTube、Reddit 或 Hacker News。
- 不加入 LLM 逐篇分類、FinBERT、斷詞器、向量資料庫或完整 agent 合成。
- 不把社群情緒加入模型訓練；待每日快照累積足夠樣本並完成樣本外回測後再評估。

