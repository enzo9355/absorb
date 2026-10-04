# 每日摘要、公告更正與觀點審核

## 使用者功能

- `/account/watchlist` 登入後顯示台北時間當日公告及當日新核對觀點，僅匹配自己的關注清單。原文公開日、核對日分開顯示；待審、未到公開時間及未到核對時間的資料不進摘要。
- `/events` 增加公告分類。分類依主旨關鍵字整理，不代表官方分類或利多／利空判斷。
- 更正公告只在相同市場、公司且明示原公告日期／主旨唯一匹配，或已有明確 `correction_of` 時顯示前後摘要。模糊更正不猜測，摘要對照不是全文差異。
- `/perspectives` 讀取已核對的獨立公開版本；取得失敗保留前次成功資料並標示。冷啟動且無可讀取版本時退回部署資料並明示來源。

## 本機審核工作台

網站服務身分仍只讀公開資料。審核工具使用本機 gcloud 登入身分，監聽 `127.0.0.1`，不部署管理路由或擴張網站 IAM。

在本工作樹根目錄執行（Python 使用專案既有 `.venv`）：

```powershell
$python = 'C:\Users\enzo\Documents\absorb-production-runner-v2\.venv\Scripts\python.exe'
& $python -m stock_papi.batch.research_review_cli fetch --workspace .research-review/batch-20261005
& $python -m stock_papi.batch.research_review_cli serve --workspace .research-review/batch-20261005
```

開啟終端顯示的本機網址。逐筆確認來源、摘要、市場、代碼、內容類型、立場、建議性質、審核者及引用依據，再按「核對並發布到正式網站」。工具不會自動核准候選。略過只在本次工作階段隱藏。

私有工作目錄只能位於 `.research-review/` 子目錄，已排除 Git 與 Cloud Run 上傳；不得改用 `static/`。每批 fetch 建立新目錄，不覆蓋旧批。重啟 serve 讀取原子 checkpoint，跳過已發布 ID；另有人先發布時拒絕覆蓋，請重新 fetch 新批。

發布到 `research/v1/public/reviewed-opinions.json`；每版另有 SHA-256 命名 archive。使用 GCS generation precondition 並讀回核對。私有候選原文不寫入公開版本；新紀錄的 text/summary 都是審核者填入的摘要。網站快取 60 秒，發布後至多需等一次快取刷新。

每日 research-refresh Job 使用新版程式讀取當前審核版本，只更新事件及候選 metadata，不寫審核指標。待審數量排除已在 catalog 的 ID。三個來源仍為有頁数上限的部分涵蓋，不能據此宣稱完整資料。

## 驗證與發布

測試：`python -m unittest tests.test_research_digest tests.test_event_context tests.test_research_review tests.test_research_refresh tests.test_opinion_review_cli tests.test_research_routes tests.test_research_catalog tests.test_watchlist_events tests.test_line_login -q`。

部署沿用 `capture_observation_lkg.ps1`、無流量候選、HTTP/瀏覽器驗收與 `verify_cutover.ps1 -ObservationOnly`。網站發布後，以同一容器 digest 更新 `absorb-research-refresh` Job，保留其身分、資源、環境與既有排程，手動試跑核對；自然排程成功須另查 execution。

本批不增加 SEC 資料、法說／除息專用來源、LINE 推播或付費 API。公告歷史仍受既有 1,000 筆／檔案大小限制。
