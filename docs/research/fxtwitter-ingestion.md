# 免費 X 貼文匯入

2026-09-17：`x_opinions_cli` 預設使用 FxTwitter 公開 JSON API。無需 X 帳號、Cookie、API key 或付費方案；即使環境中有 X token，也不會讀取它或自動回退到付費 API。

## 自動抓取（2026-09-17 使用者追加授權）

Windows 工作 `ABSORB-X-Opinions` 每五分鐘執行 `stock_papi.batch.x_watch_cli`，自動檢查 `unusual_whales`、`aleabitoreddit`、`michaelsikand`。使用既有 `run_hidden.vbs` 隱藏執行，不啟動 AI，也不使用付費 API。每帳號每次最多三頁；不是 X 即時推播，供應端延遲、限流或停機可能使取得時間超過五分鐘。

本機須開機、連網且使用者已登入；鎖定螢幕可執行，關機／睡眠／登出期間無法抓取。恢復後補一次檢查，再繼續輪詢；長時間離線或發文量超過三頁時，不能保證補齊所有漏文。這些候選檔只留在本機，不隨 Cloud Run 發布；正式站只讀取已審核 catalog。

- `data/research/x-candidates/<handle>.json`：最近一次成功取得的待審快照，供現有本機創作者頁讀取。
- `data/research/x-history/<handle>/<post_id>.json`：首次取得的永久本機存檔；移出最近時間線仍保留，已取得 ID 不重複新增。文字改動另存雜湊版本，僅互動數變動不建立版本；不是完整刪文／編輯事件重播。
- `data/research/x-watch-status.json`：每個帳號的最後嘗試／成功時間、新增數、錯誤及下次重試時間。
- 一個帳號失敗不影響其他帳號；保留原成功快照，重試間隔依失敗次數由五分鐘增加，最多一小時。排程禁止重疊，程式另有作業系統檔案鎖。
- 原始候選與機器分類仍待審，不自動納入已審核共識；六筆經使用者確認後已 promotion，既有候選會先補存歷史再刷新。

重新安裝／更新：`powershell.exe -NoProfile -File scripts/install_x_watch_task.ps1`。暫停：`Disable-ScheduledTask -TaskName ABSORB-X-Opinions`；恢復：`Enable-ScheduledTask -TaskName ABSORB-X-Opinions`。安裝器只管理這個工作，不更動其他排程。

首次自然觸發驗證：2026-09-17 20:58:25 台北時間執行，工作結果為 0，三帳號全部成功；較原本兩頁快照新收錄 57 筆（含第三頁歷史貼文，不代表都是剛發布）。158 項相關測試通過。證據：`.superpowers/sdd/2026-09-16-absorb-feature-expansion-plan/evidence/x-watch-natural-run-20260917.json`。

## 手動批次更新

在專案根目錄執行：

```powershell
$sources = @(
    @('unusual_whales', 'unusual-whales'),
    @('aleabitoreddit', 'candidate_serenity'),
    @('michaelsikand', 'michael-sikand')
)
foreach ($source in $sources) {
    .venv\Scripts\python.exe -m stock_papi.batch.x_opinions_cli --username $source[0] --creator-id $source[1] --max-pages 3 --output "data/research/x-candidates/$($source[0]).json"
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to refresh $($source[0]); previous file retained" }
}
```

這是單次手動刷新命令；自動模式見上一節。單次最多十頁，預設三頁，每頁請求 100 筆（供應端實際可能回傳較少或更多）。後續頁間隔一秒。時間條件可加 `--start-time 2026-09-10T00:00:00Z --end-time 2026-09-18T00:00:00Z`，開始含、結束不含；不因遇到舊置頂文就提前停止。

## 取得與審核分開

- 依 cursor 翻頁與貼文 ID 去重；跨作者轉貼及明確 repost 標記排除，同 handle 出現不同 author ID 則拒絕整批。
- 無法存取的 tombstone 計入 `fetch_meta.skipped.unavailable`；其他格式錯誤、HTTP 錯誤、限流均以非零退出碼結束，不覆寫上次成功檔。
- `fetch_meta` 保存時間、頁數、跳過數、停止原因；頁數上限及重複 cursor 都保留 `has_more=true`，不宣稱全量覆蓋。
- 原子替換候選快照；相同 creator、post ID 與 payload hash 保留原 `first_seen_at`。這是最新批次快照，並非完整歷史資料庫，也未實作刪文／改文的歷史重播。
- 候選均為 `pending_review`，未指定市場／證券時為 `unmapped`。不自動確認帳號身分、推薦立場或證券。
- 創作者頁讀取本機候選檔，僅顯示待審數量、最後成功抓取時間與覆蓋缺口；不在 HTTP 頁面請求中向外抓資料，也不將候選原文送入共識／ASKsorb。
- 候選不能覆寫 `data/research/public-opinions.json`。人工核對內容、日期、證券、立場和使用權利後，才走原有已審核 catalog 流程。

## 實測

### 單篇查核與共識修正（2026-09-17）

六筆機器查核草稿保存於 `data/research/x-review-draft.json`，官方 oEmbed 回應證據保存於 `.superpowers/sdd/2026-09-16-absorb-feature-expansion-plan/evidence/x-oembed/`。原始候選與公開 catalog 未被改寫，124 筆仍為待審；機器查核不等於人工確認或取得轉載授權。

| 帳號 | 貼文 ID | 建議對照 | 建議分類 | 官方文字範圍 |
|---|---|---|---|---|
| Michael Sikand | 2099872529141919849 | US META | 看多觀點／一般提及 | 全文 |
| Michael Sikand | 2098515061384114221 | US SONY | 看多觀點／一般提及 | 截斷摘要 |
| Serenity | 2099411795131924487 | TW 3006 | 看多觀點，含持倉及保留意見／一般提及 | 截斷摘要 |
| Serenity | 2097348486635368686 | TW 3006 | 看多觀點，含持倉／一般提及 | 截斷摘要 |
| Unusual Whales | 2100329124883726481 | US AMZN | 新聞轉述 | 全文 |
| Unusual Whales | 2100277786254672173 | US UAL | 新聞轉述 | 全文 |

六筆作者連結與原始貼文連結一致。長文完整內容仍來自 FxTwitter，不能宣稱已由官方全文交叉驗證；所有建議仍待人工核對。新聞中的條件不當作投資條件，作者估值與上漲推論不當作公司承諾。

共識方法升為 `opinion-consensus-v2`：同一帳號、證券、期限只計視窗內最新有效立場；時間軸保留所有合格貼文。比例分子與分母都只使用明確多空推薦，一般提及不混入比例；不足兩個明確方向帳號維持資料不足。新增測試先重現 150% 比例與同帳號重複計票，再驗證修正。另修正最新立場撤回後回退舊觀點的問題；撤回前的歷史 cutoff 仍保留當時可見立場。相關 155 項測試通過。

2026-09-17 本機每帳號抓取兩頁：Unusual Whales 49 筆、Serenity 36 筆、Michael Sikand 39 筆，共 124 筆候選。三者 `has_more=true`，不代表完整歷史或所有近期貼文；網站仍不宣稱已有已審核選股共識。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_fx_twitter tests.test_x_api tests.test_research_catalog tests.test_research_routes -q
```

FxTwitter 是第三方來源，免費存取不代表永久可用或取得轉載授權。[API 文件](https://docs.fxembed.com/api/twitter/operations/2profilehandlestatuses/)、[RSS 文件](https://docs.fxembed.com/guide/advanced/rss-atom-feeds/)。X 官方 [oEmbed](https://docs.x.com/x-for-websites/oembed-api) 可供已知單篇連結嵌入，本輪不依賴它批次列出帳號貼文。
