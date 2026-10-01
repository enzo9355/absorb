# 每日研究更新

## 範圍

沿用官方公告批次、FxTwitter watcher、人工觀點審核與既有 GCS 讀取器。預定以獨立 Cloud Run Job `absorb-research-refresh` 每天台北時間 08:00 執行；Cloud Scheduler 同名工作以 OAuth 呼叫 Job。網站不執行抓取，也不需要每天重新部署。

目前本機真實來源試跑成功（240 筆公告、185 筆候選），相關 58 項測試通過。雲端專用服務帳號已建立但尚未授予研究目錄權限；自動核准審核擋下 IAM 授權，正等待使用者明確同意。Job、每日排程與網站讀取功能尚未啟用。

全套回歸執行 1,868 項，1 項跳過、2 項既有排程器失敗（abandoned mutex ownership、US PostClose PT5H／PT12H 契約差異），另 7 項 uploader preflight 因等待發布鎖超過 120 秒而逾時。零等待探針確認 `Global\ABSORB-Observation-Publication-Writer` 當時已被占用；指定專案 Python 的重跑未解除等待，已停止該組重跑。相關排程器／uploader 程式未修改，沒有宣稱全套通過。完整失敗名稱與日誌位於本次 artifacts。

- TWSE／TPEx 重大訊息驗證後合併前次公告，維持 1000 筆／1 MB 上限。任何來源失敗保留前次公告，發布失敗狀態。
- 三個既有 X 帳號每次最多三頁，來源 ID 變更拒絕更新；候選保持 pending。私有快照保留原文及首次取得時間，不自動發布觀點。
- 私有候選：`research/v1/private/latest/<handle>.json`，另存 SHA-256 命名快照。
- 公開快照：`research/v1/public/latest.json`，只含公告、公告更新狀態及版本綁定的觀點抓取數量／時間。整份快照以 GCS generation 條件寫入、讀回比對；並行衝突拒絕覆蓋。
- 網站環境 `ABSORB_RESEARCH_REFRESH_ENABLED=true` 時讀公開快照，快取 60 秒。儲存讀取失敗時保留程序中前次成功資料；冷啟動時保留部署快照並標示更新失敗。前次核對時間仍保留，不假裝最新。
- 網站服務身分維持唯讀。獨立 Job 身分預定僅可讀寫 `research/v1/`，無市場產品寫入權限，也不配置 LINE 或付費 X API 金鑰。

## 試跑與驗收

```powershell
gcloud run jobs execute absorb-research-refresh --project line-stock-bot-498908 --region asia-east1 --wait
gcloud scheduler jobs run absorb-research-refresh --project line-stock-bot-498908 --location asia-east1
gcloud scheduler jobs describe absorb-research-refresh --project line-stock-bot-498908 --location asia-east1
```

確認 Job execution 成功、公開快照 generation／SHA 與日誌一致、正式 `/events` 的核對時間及筆數更新、`/perspectives` 的抓取時間更新且已核對觀點維持人工 catalog。Scheduler 手動觸發能證明呼叫鏈路；首次自然觸發仍需獨立查看 execution 與快照。

## 暫停／回退

```powershell
gcloud scheduler jobs pause absorb-research-refresh --project line-stock-bot-498908 --location asia-east1
gcloud run services update line-stock-bot --project line-stock-bot-498908 --region asia-east1 --update-env-vars ABSORB_RESEARCH_REFRESH_ENABLED=false
```

停排程不刪快照；關閉讀取功能回到部署資料。回退公開快照需經 schema 驗證並指定當前 generation，不直接覆蓋市場產品指標。觀點核對沿用 `opinion_review_cli`；來源缺漏／免費來源限制與人工審核不能由排程消除。

技術依據：[Cloud Run 定時執行 Job](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)、[GCS 條件與重試](https://docs.cloud.google.com/storage/docs/retry-strategy)。
