# 免費研究來源維護紀錄

2026-10-15：沿用每日台北時間 08:00 排程、1 CPU / 512 MiB 工作，不新增付費 API、代理、訂閱或 AI 摘要。既有雲端帳單不等於零費用。

| 來源 | 取得方式 | 本次實測候選 |
|---|---|---:|
| Aswath Damodaran | 官方 Musings on Markets RSS | 25 |
| Ben Carlson | 官方 A Wealth of Common Sense RSS | 10 |
| Meb Faber | 官方 Meb Faber Research RSS | 10 |
| Nick Maggiulli | 官方 Of Dollars And Data RSS | 10 |
| Barry Ritholtz | 官方 The Big Picture RSS | 10 |
| Alpha Architect | 官方機構 RSS，保留各篇作者 | 5 |
| 股市貴公子／鍾崑禎 | 官方 YouTube 頻道公開 feed | 15 |
| Serenity、Michael Sikand、Unusual Whales | 既有 FxTwitter 流程 | 沿用既有排程 |

來源 URL 與頻道 ID 固定於 `stock_papi/services/free_research_feeds.py`。新增七個可用來源，加上既有三個 X 來源，共十個每日來源。人物目錄另保留財經皓角，共十一筆；G MONEY 的近期 feed 沒有可確認的財經皓角節目，因此不混入其他節目，也不納入每日擷取。

首次新增 85 筆候選保存在忽略版本控制與部署的 `.research-review/free-expansion-review.json`。所有候選維持 pending_review；影片標題不代表已核對完整內容，機構文章不歸為單一人物立場。只有既有管理審核流程確認的摘要能公開。

排除來源：Michael Batnick 與 Josh Brown feed 非有效 XML、Cullen Roche feed 停留舊日期、Lyn Alden 回傳 403、綠角 feed XML 無法解析；Mr. Market 的近期樣本偏信用卡，未採用。未繞過封鎖，也未增加付費備援。

## 失敗與隱私邊界

- 每次最多讀取 2 MB、25 筆；拒絕跳轉、不符網站或頻道身分、無時區、未來日期與 XML 外部實體。
- 空來源或讀取失敗保留前次私有候選與成功時間，公開頁顯示來源失敗；不把失敗檢查時間當成成功抓取。
- 公開更新檔僅含數量、提供者、成功時間與健康狀態，不包含候選文章或影片文字。
- 免費 feed 只保證可取得其近期清單，不代表完整歷史、全文授權或永久可用。

## 發布順序與回復

先部署支援 RSS／YouTube 與健康狀態的新網站，再更新既有 research Job 的映像；排程不變。部署前確認 `research/v1/public/reviewed-opinions.json` 是否存在：本次檢查為 404；若出現新指標，需重新核對來源清冊，不得覆寫他人已審成果。

新 metadata 不相容舊 reader。若已執行新 Job 後回復舊網站，必須先停止新 Job 寫入，依保存的 generation 與內容核對回復 research public snapshot，再回復 Job 與網站；不得盲目覆寫後續公告或已審資料。新映像需加 `protected-` 前綴保留標籤，避免重演映像被清理後排程無法啟動。

本次手動觸發 Scheduler 成功與下一次自然 08:00 執行是不同證據，分別驗證。
