# 觀點與揭露、公司事件：現況與改善範圍

檢查日期：2026-10-01，Asia/Taipei。使用者已確認第一階段方向；本工作樹已完成程式、台股官方公告快照與本機驗收。正式站尚未部署；下方「本次查到的事實」保留修改前的診斷。

## 目標

讓使用者能查到有來源與時間的公司公告、公開觀點及交易揭露，並理解資料的新舊與涵蓋範圍。保留原始來源、交易日／揭露日區分及待審狀態。

## 本次查到的事實

| 項目 | 目前狀況 | 影響 |
| --- | --- | --- |
| 正式 `/events` | 顯示 2 筆收錄，實際只有 TWSE／TPEx 官方來源入口；過去與未來事件都是空白 | 來源入口數被當作事件數；未匯入個別公司公告，不能聲稱沒有事件 |
| 正式 `/perspectives` | 8 筆觀點、1 筆動態；最近核對時間空白 | 有頁面但內容薄弱，使用者無法判斷更新狀態 |
| 公開觀點紀錄 | 主目錄 catalog 有 6 筆 confirmed、2 筆 legacy_unverified；正式頁將 8 筆放在「公開觀點／REVIEWED RECORDS」 | 未核對的舊紀錄應清楚分開，不能混入已核對清單 |
| X 候選 | 本機 10/01 01:48 抓取：Serenity 52、Michael Sikand 57、Unusual Whales 71，共 180 筆，全為 pending_review，均 has_more=true | 抓取正在產出候選；問題包含核對與正式發布銜接，且候選不代表完整覆蓋 |
| 機構持倉 | 正式分頁為 0 筆，但仍列 Berkshire 等對象 | 人物／機構身分存在不代表持倉資料已接入 |
| 篩選與時間 | 觀點清單程式未套用 activity_window、subject_id 或 cutoff 的完整條件；tab 連結只保留 market、symbol、activity_window | 不同清單受不同篩選影響，換 tab 丟失人物／創作者等條件 |
| 分頁 | 後端切出每頁資料；模板顯示頁數但沒有前後頁連結 | 超過一頁後無法透過頁面瀏覽完整內容 |
| 部署工作版本 | 本 chat 工作目錄是 9/23 的 `8f42b93`，沒有這兩個功能；主目錄有新程式及大量未提交修改 | 實作須先取得包含目前功能的獨立基線，保留主目錄既有工作 |

## 建議第一階段設計

### 觀點與揭露

- 沿用既有 catalog、候選抓取與追蹤 API；不另建一套資料系統。
- 以「公開觀點／交易揭露／機構持倉」分類，各自顯示最後抓取、最後核對、最後發布與涵蓋缺口；沒有時間則明寫未提供。
- 人物與創作者統一使用可理解的名稱，技術 ID 不作為一般使用者的輸入或主要內容。
- 同一頁的日期、市場、公司與對象篩選使用一致語意；切換分頁保留條件，提供清除篩選與前後頁連結。
- 已核對清單只列合格紀錄，舊版未核對紀錄另標示；截止時間以前尚未可用的資料不進入當時的清單。
- 抓取候選到公開 catalog 的核對與發布沿用現有契約；先提供可核對候選批次及其來源，不把全部 pending 改成 confirmed。
- 交易揭露與持倉若尚未接入，直接說明未接入／未涵蓋，不用「沒有交易」代替。

### 公司事件

- 台股先接目前已有 allowlist 的 TWSE／TPEx 官方個別公司重大訊息，沿用現有事件 schema、驗證器與批次讀取方式。
- 顯示公司、公告主旨、公告時間、已明確提供的生效日期、摘要及原始來源；只有公告時間的事件歸入公告清單，不能推測法說或除息日期。
- 已確認日期才進入未來行事曆；來源入口另列，不計入公司事件數。
- 來源失敗、資料過期、公司未涵蓋、篩選無結果及完整範圍確實無公告，分別標示。取得失敗時保留前次成功資料與時間。
- 第一階段只承諾台股官方公告；美股及新增財報／除息／法說資料源須另確認實際來源後接入。

## 預期修改及驗收

沿用較新基線的 `stock_papi/web/routes/research.py`、`stock_papi/services/research_catalog.py`、`stock_papi/services/company_events.py`、研究頁模板及既有 batch/promotion 工具；只有缺少的公司公告批次入口需要新增。

驗收必須包括：真實公告批次的来源與日期核對、失敗不覆蓋前次資料、候選不進已核對清單、截止時間與篩選一致、換 tab 保留條件、多頁可瀏覽，以及桌機／手機顯示。部署前另核對正式來源版本與流量，不以本機檢查代替正式站驗收。

## 證據位置

- 正式觀點頁：https://line-stock-bot-3visrvv4yq-de.a.run.app/perspectives
- 正式事件頁：https://line-stock-bot-3visrvv4yq-de.a.run.app/events
- 本工作目錄：`artifacts/perspectives-events-audit-20261001/events.png`、`events-dom.txt`。
- 主目錄：`data/research/events.json`、`data/research/public-opinions.json`、`data/research/x-candidates/*.json`。
- 程式：`stock_papi/web/routes/research.py`、`stock_papi/services/research_catalog.py`、`templates/perspectives.html`、`templates/events.html`。

正式 DOM 已確認上述呈現；主目錄程式用於定位對應原因。本次沒有下載並比對正式部署封存，不宣稱主目錄所有程式與正式版本完全相同。

## 已實作與驗收

- 使用現有工作樹，以 `0f476b91352c2230a4df758ad9a09a6adbe4a1f9` 為基線；原主目錄未修改。
- 公司事件已透過 TWSE／TPEx 官方 API 匯入 240 筆個別公告（157／83）。公告、生效日期及資料入口分開呈現；來源未提供生效日期時保留空值。每頁 20 筆，篩選、切頁及清除可操作。
- 觀點清單只列截止前已核對且來源可用的紀錄。共用查詢涵蓋主頁、創作者頁、個股觀點頁及個股摘要；主頁、相關頁與共識皆套用對象篩選，時間窗口及換頁條件一致。
- 畫面顯示最後候選抓取／核對／發布時間，並明示待審及資料缺口。實際公開清單仍是 6 筆已核對觀點與 1 筆動態；2 筆舊紀錄未列入已核對清單。
- 10/01 16:53 候選快照有 183 筆 pending。建立 182 筆新增候選的本機待審稿（1 筆已在公開 catalog）；公開 metadata 只含抓取時間、數量等欄位。沒有將候選批次改為 confirmed。
- 相關測試最終 **85 項通過**。第一次全套 1,862 項有 5 項失敗；已更新中文標籤斷言，另 2 項排程器探針在允許系統探針權限後通過。
- 擴充後全套 **1,864 項，exit 0，3 項跳過**。其中 2 項為本基線未修改且重現的排程器失敗：abandoned mutex 探針，以及 US PostClose 測試仍要求 PT5H00M、基線程式已為 PT12H00M。沒有為讓本次功能通過而修改排程器契約。剩餘 1 項是既有跳過項。
- 本機瀏覽器確認 Serenity 篩選、公告公司 3447 篩選、公告第 2 頁、桌機及 390px 手機無橫向溢出。截圖與測試日誌位於本工作樹 `artifacts/perspectives-events-audit-20261001/`；這是本機證據。
- `git diff --check` 通過。未增加套件；沿用 schema、驗證器及原子 JSON 寫入方式。

## 更新公告

在專案根目錄，使用專案既有 Python 執行：

```powershell
python -m stock_papi.batch.company_events_cli --output data/research/events.json
```

任一官方來源抓取／日期或 schema 驗證失敗時，不覆蓋前次 catalog；寫入 `events-status.json`，頁面顯示更新失敗並保留前次公告。兩日未更新顯示過期。檔案最多 1000 筆並受 1 MB 上限限制，不承諾完整歷史。

## 候選核對與發布

```powershell
python -m stock_papi.batch.opinion_review_cli prepare --candidates data/research/x-candidates/aleabitoreddit.json data/research/x-candidates/michaelsikand.json data/research/x-candidates/unusual_whales.json --output data/research/x-review-draft.json --status-output data/research/public-opinions-status.json
python -m stock_papi.batch.opinion_review_cli publish --review data/research/x-review-draft.json --output data/research/public-opinions.reviewed.json
```

先核對原文、證券、來源、立場與時間；待審稿保留欲發布紀錄，填 `reviewer`、`rights_note`、人工 `summary`、含時區的 `reviewed_at`，並逐筆明確設定 `review_status=confirmed`。未核對紀錄移出本次發布清單，保留原候選檔。發布命令驗證基線 SHA、每筆 confirmed、來源與時間、重複 ID 及大小上限；輸出必須是新檔，原 catalog 不被直接覆蓋。修訂用新 ID 與 `supersedes_id`。

待審稿有候選原文，不進 Git 或 Cloud Run 部署包；候選與草稿沿用忽略規則。本次 artifacts 下的待審稿另加入 Git ignore，整個本次 artifacts 排除於部署包。

## 尚未包含

本階段未接入美股公司事件、完整機構持倉、法說／財報／除息專用日曆，也未安裝新的自動排程。批次程式及讀取狀態已可使用；下一次正式發布必須驗證實際來源版本、設定及 Cloud Run 流量，再做正式站瀏覽器驗收。不能把本機成功或這份公告快照當作持續更新或正式站完成證據。
