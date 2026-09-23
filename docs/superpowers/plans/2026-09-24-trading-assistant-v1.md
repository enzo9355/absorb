# ABSORB 交易助手第一版 Implementation Plan

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐批執行本計畫；若使用者另選代理分工，才使用 `superpowers:subagent-driven-development`。以 `- [ ]` 勾選進度。本文同時包含產品規格與實作計畫，執行前完整閱讀，不能只抽取任務清單。

**Goal:** 交付可供同學試用的交易助手：從數據或大咖動態找到標的，取得有條件的交易建議，儲存計畫、接收條件變更提醒，再回報使用心得。

**Architecture:** 沿用 Flask/Jinja、既有行情快照、公開觀點 catalog、LINE 登入與使用者 state。增加一個純函式交易計畫服務，以及公開操作紀錄的驗證／查詢函式；Web、ASKsorb、提醒共同讀取同一份結果。第一版不另建模型平台、爬蟲平台、會員系統或資料庫。

**Tech Stack:** Python、Flask/Jinja、stdlib、既有 requests／LINE SDK、FirestoreStore／SupabaseStore、原生 JavaScript／CSS、unittest。

**Spec:** 本文件第 1–10 節為產品與資料規格，第 11–15 節為執行與驗收計畫；依據本次使用者確認的交易助手方向與「加強既有大咖操作版面、先給同學試用」要求。

**文件日期：** 2026-09-24，Asia/Taipei。  
**狀態：** 完整計畫，尚未實作、尚未部署；文中新增介面、環境設定、測試名稱都是預定契約，不代表目前已存在。  
**查核基準：** 本機 `codex/tw-premarket-verified-overlay`，HEAD `b56e9f1850f14c7bedcf663b69ca411188d9fdc6`，包含既有未提交變更。未將此 HEAD 當作正式站版本。

## Global Constraints

- 第一版提供明確的條件式交易建議；資料、來源或前提不成立時，說明缺少什麼，停止產生新的可進場建議。
- 以同學邀請試用、免收費、手動交易為預設；不自動下單、不接券商、不收集券商密碼。
- 交易計畫先支援美股普通股、日線、做多；既有台股與跨市場研究／人物觀點保留。美股優先是因本次跟隨名人與 Intel 的使用情境，不代表刪除台股。
- 「看數據」「看大咖」「一起看」是資訊入口偏好，不是三套宣稱有效的交易策略；第一版只有一套公開、可重現的日線規則。
- 保留來源、日期、反對證據、資料不足與過期狀態；不得把提及、轉述、季底持倉、期權操作混成普通股買進。
- 舊研究模式禁止所有建議的產品限制，依本次授權規劃為「僅受邀使用者可用條件式建議」；原有機率、排名、強行動、績效背書限制不一併解除。
- 所有私人讀寫以伺服器 session 的身分為準，寫入須 CSRF；使用者輸入不得指定另一人的 user ID。
- 保留本機 dirty worktree；不得 reset、clean、覆蓋既有改動、整批提交其他人的檔案。
- 本次產出僅此 Markdown 計畫；不改程式、資料 catalog、GCS、排程、Cloud Run 或 LINE 設定。

## Review Focus

1. 一位發布者轉述另一人的交易：發布者、被追蹤人物、實際交易所有人必須分開；任務 1、2 驗證。
2. 揭露晚於交易、審核又晚於揭露：查詢與後續觀察不得使用當時尚未公開／尚未可用的資訊；任務 1、3、7 驗證。
3. 相同來源有多筆交易、同一筆交易被多人轉貼、文件之後修訂：不能整份只留一筆，也不能重複計數；任務 1、2 驗證。
4. 使用者換策略偏好、其他裝置同時寫入、LINE 舊流程正更新 state：已存計畫及歷史不得消失或被改寫；任務 4、6 驗證。
5. 美股休市、提前收盤、缺棒、停牌、拆股，以及收盤後才形成的訊號：不能產生可於當日收盤成交的假紀錄；任務 3、7、9 驗證。

## 1. 第一版要解決的問題

使用者不一定從同一種理由開始買股票。有人先看量價，有人先看喜歡的創作者，也有人先注意政治人物或機構揭露。ABSORB 應讓這些入口最後回到一份看得懂、能追蹤的交易計畫。

### 1.1 完整使用流程

1. 使用 LINE 登入試用，在「我的交易」選擇資訊偏好：數據／大咖／綜合；預設綜合，可隨時切換。
2. 從「大咖動態」看既有人物的公開觀點與操作，或從個股資料頁挑選標的。
3. 查看具體交易建議：等待、可評估進場、暫不追價、檢查退出條件、暫停評估。
4. 展開原因、反對證據、觸發與失效條件、資料日，按「加入觀察」或「儲存交易計畫」。
5. 只有計畫條件變動時，在站內看到提醒；自願開啟 LINE 通知者才接收推播。
6. 回頭看原始計畫與後續變化，提交「有幫助／沒幫助／資料有問題」及一句說明。

### 1.2 明確排除

- 不做即時盯盤、當沖、期權交易建議、放空、槓桿、跟單執行。
- 不宣稱名人買入等於現在值得買，不做名人績效排行榜或「跟誰最賺」。
- 不估計名人的持倉成本、未揭露持倉、完整資產配置或精確交易金額。
- 不做個人化資產配置、推薦投入資產百分比；第一版只區分使用者自行標記的「未持有／已持有」，不是完整適合度評估。
- 不把短期同學回饋或幾筆訊號視為策略獲利能力證明。
- 不新增付費資料訂閱、付費 X API、社群自動發文、公開收費方案。

### 1.3 本計畫直接採用的預設

| 項目 | 第一版決定 | 理由／界線 |
|---|---|---|
| 試用對象 | 邀請 5–10 位同學，先跑 2 週 | 先驗證流程與理解度；人數不足也可測，不能假報達標 |
| 市場 | 新交易計畫先美股，台股保留既有服務 | 對應名人／Intel 情境，避免第一版同時驗證兩套市場規則 |
| 交易方法 | 一套日線趨勢確認規則 | 不假裝涵蓋每個人的策略；可選閱讀偏好與追蹤人物 |
| 人物 | 既有五個帳號保留；新增 Pelosi 家庭與 Berkshire 機構身分／來源入口 | Pelosi 的實際交易人依文件辨識；Berkshire 不寫成 Buffett 本人親自下單 |
| 取得方式 | 沿用 X 候選抓取；正式揭露先小量人工核對與結構化匯入 | 不先造完整 SEC／國會爬蟲 |
| 訊息 | 站內必備，LINE 自願開啟 | 不自動將同學加入推播 |
| 決策權 | 使用者確認並自行交易 | 系統記錄的是建議／條件，不是假成交 |

目前沒有需要使用者先回答才能完成計畫的問題。試用名單、來源使用依據與通知名單在開放試用前填入；它們不阻止本機實作與驗收。

## 2. 已有功能與本次差異

### 2.1 本機核對結果

| 現有入口 | 已存在 | 本次用途與缺口 |
|---|---|---|
| `stock_papi/services/public_opinions.py` | v2 creator／opinion 驗證、來源綁定、條件分類、撤回、後續觀察 | 保留；補操作紀錄的獨立欄位，不能把全文「bought」當成已核實交易 |
| `stock_papi/services/opinion_consensus.py` | 同一市場／證券／截止時間的觀點聚合 | 保留分母與時間條件；不把交易、機構持倉變化放進看多比例 |
| `stock_papi/services/research_catalog.py` | 載入本機 catalog；X 候選僅提供待審數量 | 延伸可選的 `subjects`、`activities`；候選不直接成為已核對資料 |
| `stock_papi/web/routes/research.py` | `/perspectives`、`/perspectives/<creator_id>`、`/perspectives/stocks/<market>/<symbol>` | 沿用主入口，加動態頁籤；修正時間篩選及已核對清單的一致性 |
| `templates/perspectives.html`、`creator.html` | 帳號卡、觀點清單、coverage | 改為中文資訊與操作時間線；現有表單仍有 creator_id／英文枚舉等使用門檻 |
| `data/research/public-opinions.json` | 5 個帳號、8 筆觀點 | 3 個 X 身分 verified；2 個 YouTube legacy_unverified；6 confirmed 中 2 為新聞轉述、4 為原始觀點；沒有可直接拿來展示的已確認操作紀錄 |
| `recommendation_engine.py` | 具原因、風險、已持有／未持有文案的確定性引擎 | 依賴五日機率與歷史樣本；不可為了第一版移除其門檻或假填機率 |
| `observation_view.py` | 從已驗證快照產生價格、MA20／MA60、RSI、量比 | 可重用讀取鏈；圖表 candles 會對缺失 OHLC 做展示補值，交易規則須讀原始已驗證 daily，不可讀補過的圖表資料 |
| `stock_papi/application.py` | research 對話早期攔截建議，grounded prompt 再禁買賣 | 要同時處理路由與生成契約，不能只改一句 prompt |
| `line_state.py` | FirestoreStore／SupabaseStore、樂觀並行更新、12 自選／20 提醒 | `normalize_state()` 只保留既定欄位；新增 assistant 狀態需完整 round-trip 測試 |
| `auth.py`、`/account/watchlist` | LINE session、CSRF、私人清單 | 沿用，不另建帳密或公開 user ID 查詢 |
| `line/notifications.py`、`/tasks/check-alerts` | 舊提醒排程與去重 | 同入口接新計畫評估；舊路徑的每日日期去重不能當成完整新計畫去重 |

本機 catalog 版本為 `public-opinions-v2-c2-2026-09-18-x-review`。上述數量是本機檔案核對，不代表 2026-09-24 正式服務的最新涵蓋量。

### 2.2 執行環境與歷史差異

- 本機 `.codegraph/` 不存在；本次依實際檔案查找，不建立索引。
- 本機 `scripts/build_css.py`、`scripts/check_ui.sh` 與 `.github/workflows/` 不存在，`static/app.css` 是目前可見的 tracked 樣式檔。不得直接照舊記憶寫出不存在的檢查命令。
- 開始實作時先確認選定基線：若實際來源有 CSS 產生器，改來源並執行它；若與此 checkout 相同，直接修改 `static/app.css`。不能為了沿用舊命令新增不必要的建置工具。
- 目前 dirty 檔案包括 LINE Flex／presentation、對話 policies／web、app factory、requirements、Docker 與圖表。它們可能與任務 5、6、8 重疊，先做差異對照，不整檔覆蓋。
- 撰寫結束時另觀察到 DESIGN、CSS／JS、manifest、market／system routes、base／dashboard／stock 模板及相關測試出現其他未提交變更。本次只寫此計畫；這些同步變動不在本次修改範圍，實作前須重新讀取最終基線，不能使用本文件的行號當固定定位。

## 3. 大咖動態版面

### 3.1 資訊架構

主入口沿用 `/perspectives`，導覽改為「大咖動態」，不新增第二個相似首頁。

```text
大咖動態                         [全部人物] [我追蹤的]
最近核對時間／來源涵蓋說明

[最新動態] [交易揭露] [機構持倉] [公開觀點]
[人物選單] [市場] [股票搜尋] [近 7／28／90 日]

人物／機構卡：名稱、身分、最近已核對資料、追蹤按鈕

動態卡：
  誰／哪個帳戶 → 股票或期權 → 文件記載的行為
  交易日或持倉基準日 ｜ 公開揭露日 ｜ 最近核對日
  金額區間／數量（僅文件已揭露者）
  來源摘要、限制、修訂狀態
  [查看原始來源] [查看個股] [評估交易計畫]
```

- 使用者選「我追蹤的」但未登入時，提供登入與返回目前篩選；不得顯示其他人的清單。
- 第一頁預設最新公開動態，依 `public_at` 倒序，再以穩定 ID 排序；不是依交易日排序。
- 每頁 20 筆，`page` 為正整數，查詢參數保留在換頁、人物頁、個股返回連結。
- 現有觀點共識視窗 `[1,7,28]` 維持；新增操作時間窗用 `activity_window=7|28|90|all`，不要把 90 天硬塞進原共識統計。
- 兩個舊 YouTube 帳號保留身分與待核對說明；待審文章不出現在「已核對動態」中。
- 尚未確認來源的人物可以有資料入口與說明，不得放假交易填版面。

### 3.2 四種內容必須一眼辨識

| 類型 | 可說 | 不可說 |
|---|---|---|
| 官方交易揭露 | 文件揭露某所有人在某日買入／賣出某商品 | 今天正在買、目前仍持有、使用者可以相同價格買到 |
| 當事人自述 | 本人於某日表示已買入／賣出；未獨立驗證成交 | 官方已確認成交 |
| 機構 13F 持倉 | 某季底申報持倉；可比兩期的申報數量變化 | 精確交易日、真實成交成本、某知名經理人本人下單 |
| 公開觀點／轉述 | 某人看多／看空／有條件看法／媒體轉述 | 只因看多就推定已買入；轉述者自己持倉 |

期權需顯示 call／put、買／賣、履約／到期等原文動作；strike、expiry、數量缺失就保留未揭露。期權動態可查原文，但第一版「評估計畫」只能轉到標的普通股，並明示「這是另一商品的分析」，不得預設沿用期權方向。

### 3.3 Pelosi／Intel 的處理

- 使用者的例子作為需求情境，不作為「Pelosi 已買 Intel」的資料事實。
- 建立可追溯的人物／家庭群組；保留 filer、owner（self／spouse／joint／dependent／unknown）與文件上的姓名。
- 實作時核對相關原始揭露；若找不到匹配的 INTC 紀錄，顯示「目前已核對範圍內未找到」，同時顯示檢查範圍與原始查詢入口。
- 不把「沒找到」寫成「她沒有買」，不以其他股票或其他人交易替代 INTC。
- 若為配偶交易，使用「Pelosi 家庭揭露：配偶…」；只有來源明確時才顯示實際所有人姓名。

### 3.4 人物與來源數量

第一版保留既有五帳號，新增兩個身分入口即可。人物數量不是驗收 KPI；重點是有至少一組真實、可核對的操作／持倉紀錄，以及既有原始觀點與新聞轉述的正確分類。若 Pelosi 來源使用範圍尚未確認，該入口維持來源導覽；不能聲稱政治人物交易 feed 已完成。

## 4. 公開動態資料契約

沿用 `public-opinions.json` 的 `schema_version=2` 與舊 `opinions`；新增可選 `activity_schema_version=1`、`subjects=[]`、`activities=[]`。舊 catalog 無新增欄位仍可讀。新增 validator 由 `build_catalog()` 調用，輸出活動與活動錯誤，**不修改原觀點統計語意**。

### 4.1 Subject 與 Activity

| 欄位 | 契約 |
|---|---|
| `subject_id` | 穩定人物／家庭／機構 ID；和 `creator_id` 分開，creator 是發布帳號 |
| `subject_kind` | `person`／`household`／`institution` |
| `subject_name`、`aliases` | 核對過的顯示名稱與查詢別名；不能只用「大咖」模糊歸屬 |
| `identity_source_url` | 身分核對來源；HTTPS、安全白名單 |
| `activity_id` | SHA-256 穩定鍵：來源文件 ID＋原始行定位＋修訂版本＋證券 ID |
| `activity_type` | `trade_disclosure`／`holding_snapshot`／`self_reported_trade`；公開觀點繼續留在 opinions |
| `publisher_creator_id` | 轉述發布者，可空；不是操作主體 |
| `subject_id`、`owner`、`owner_name` | 被追蹤對象、所有人類型、文件上的已核對姓名；未知不推定 |
| `market`、`symbol`、`instrument_type` | 市場與可驗證證券；`common_stock`／`option`／`other`／`unknown` |
| `security_name`、`security_identifier` | 保留原始證券名稱／CUSIP 等；無法映射代碼時顯示來源，禁個股／計畫 CTA |
| `action` | `purchase`／`sale`／`exchange`／`exercise`／`holding`／`other`；不從 call／put 直接推導買賣 |
| `transaction_date` | 交易日期，可 null；只存日期，不補午夜假精度 |
| `holdings_as_of` | 季底持倉基準日，holding_snapshot 必填，不能當交易日 |
| `public_at`、`public_time_precision` | 來源公開時間與 `timestamp|date`；只有日期時保存來源當地日期／時區，以當地日終作保守可用上界 |
| `first_seen_at`、`reviewed_at` | 含時區的實際取得／人工核對時間；不得回填成交易日 |
| `available_at` | 衍生值 `max(public_at_upper_bound, first_seen_at, reviewed_at)`；系統當時可用時間 |
| `amount_min`、`amount_max`、`currency` | 原揭露區間，缺失 null；不能用中間值冒充精確成交金額 |
| `quantity`、`quantity_unit`、`reported_value` | 僅來源提供才存；13F 市值不是投入成本，需保留原單位／報表版本 |
| `option_type`、`strike`、`expiry` | 原文已揭露的期權欄位；缺失 null |
| `source_kind`、`source_url`、`source_document_id`、`source_locator` | `house_ptr`／`sec_13f`／既有 X 等；原始文件、頁碼／行定位均可回查 |
| `source_sha256`、`reviewer`、`rights_status` | 來源證據摘要、核對者、`approved|source_only|pending`；不得以「公開」自動設 approved |
| `review_status`、`source_status` | confirmed／pending_review／rejected；available／unavailable；兩者分開 |
| `supersedes_id`、`withdraws_id` | 修訂／撤回關聯；保留原始紀錄，不覆寫歷史 |
| `summary`、`limitations` | 短摘要與限制，所有來源文字視為不可信資料；輸出自動跳脫 |

可公開作為已核對活動須：身分已核對、來源可回查、日期合理、review confirmed、使用範圍 approved、必要欄位完整；無代碼但原始證券可辨識者可作來源紀錄，不能成為交易建議輸入。交易日／季底日不得晚於公開日；修訂的公開日使用修訂版本本身。

### 4.2 去重與時間查詢

```python
# 新增於 public_opinions.py，這是固定的預定函式介面。
def validate_activity(row: dict, subjects: dict) -> dict:
    """回傳原始欄位、validation_errors、is_confirmed、available_at。"""

def query_activities(catalog: dict, *, subject_id: str | None,
                     market: str | None, symbol: str | None,
                     cutoff_at, window_days: int | None) -> list[dict]:
    """只回傳截止當時已可用的核對活動，依公開時間倒序。"""
```

- 同一份文件的不同列都是合法紀錄；活動去重不可沿用舊 `seen_sources` 的「整個來源只有一筆」。
- 同一操作被五個帳號轉貼，活動本體只有一筆，其他來源成為 supporting links；新聞仍可存在但不增加操作數。
- 修訂／撤回只有在自己的 `available_at <= cutoff_at` 時才影響當時查詢；不能用日後修訂改寫歷史視角。
- 13F 僅在同一機構、相鄰季度、同一證券／股別／期權類型／數量單位、兩期完整且可比較時顯示增加／減少／新出現／未再列示；公司行動未校正、機密申報、缺頁時不推導清倉。
- 操作紀錄不進 `build_consensus()` 的 bullish／bearish 分母；「3 位提到」不能寫成「3 位買入」。
- 修正現有 `/perspectives` 清單篩選：同時檢查 is_confirmed、時間窗口與 cutoff；不能只有統計套用截止時間，清單卻洩露未來或未審紀錄。

### 4.3 匯入與更新

新增 `stock_papi/batch/public_activity_cli.py`，只接受本機人工整理 JSON：

```powershell
.venv\Scripts\python.exe -m stock_papi.batch.public_activity_cli --input artifacts/activity-review/input.json --catalog data/research/public-opinions.json --output artifacts/activity-review/candidate.json
```

- 先檢查 1 MB 大小上限、JSON 結構、來源白名單、ID、時間、幣別與數值；失敗非零退出，保留原 catalog。
- output 必須與 input／catalog 不同；採新檔 exclusive create，已存在即失敗，不覆寫來源或舊候選。
- 回傳新增、重複、待審、拒絕數量與錯誤理由；不能自動將 pending 升為 confirmed。
- 審核人核對文件後，才以小範圍資料 diff 更新正式 catalog 並執行 validator。原始候選／來源 hash 與核對報告保留。
- 試用期間每天人工查核一次已納入來源；頁面標「最近核對時間」，不承諾即時更新。來源無新資料是 zero_new，抓取失敗是 failure，兩者不能混淆。
- 本機 X watcher 的候選不會自動出現在 Cloud Run。第一版沿用隨應用發佈的 reviewed catalog：每次對外更新均要走受控的候選版本與 read-back；不私自新增背景排程或直接改 mutable GCS pointer。
- 若人工更新成本成為試用主要問題，再另做 catalog 發佈工作；第一版不先新增一般化 ingestion 平台。

## 5. 條件式交易計畫

### 5.1 對使用者的固定輸出

每張計畫卡包含：**建議 → 適用策略／期間 → 依據 → 反對證據 → 進場條件 → 失效／退出檢查 → 資料截至日 → 儲存／提醒**。價格不可藏在聊天文字內而缺少結構化來源。

| action | 顯示文字 | 適用情境 |
|---|---|---|
| `wait` | 等待條件確認 | 必要資料完整，尚未符合進場規則 |
| `entry_review` | 條件符合，可評估進場 | 規則成立；仍須下個交易時段確認，無勝率承諾 |
| `avoid_chasing` | 暫不追價 | 超出計畫容許價格或 RSI 過熱 |
| `exit_review` | 檢查退出條件 | 已持有者的已存計畫失效；非持有者顯示「取消這份進場計畫」 |
| `insufficient` | 暫停評估 | 過期、缺資料、停牌、公司行動不可比、日期矛盾或非支援商品 |

規則觀察不直接宣稱統計優勢，介面標「日線規則試用版，尚未驗證獲利能力」。方向分數不得變成百分比勝率。

### 5.2 規則 `us_daily_breakout_v1`

本規則是試用假設，固定版本、固定條件，不以同學試用樣本尋找最漂亮的參數。

1. 輸入僅接受已驗證 `US`、普通股、`regular_price` 快照；檢查來源 hash、canonical symbol、as_of、availability、完整連續交易日與公司行動狀態。
2. 使用至少 61 個連續已完成交易日的原始 daily；數值須 finite 且 OHLC 合法，Volume > 0。停牌等狀態不能補成價格列。
3. 計畫建立日為 T；MA20／MA60 使用截至 T 的 Close；量比為 T 成交量除以前 20 交易日成交量平均。RSI 固定由最後 61 根連續原始 Close 計算：前 14 個價差的 gain／loss 算術平均作初值，後續以 `(previous * 13 + current) / 14` 平滑，最後用 `100 - 100 / (1 + avg_gain / avg_loss)`；全無漲跌為 50、只有上漲為 100、只有下跌為 0。方法命名 `rsi14_wilder_last61_v1`，不依賴尚不存在的外部 RSI 方法欄位，不假裝與其他終端的初始化完全相同。
4. `trigger_price = max(High[T-20:T])`，明確排除 T；`entry_ceiling = trigger_price × 1.03`；`invalidation_price = MA20[T]`；若 invalidation 不小於 trigger，暫不產生進場計畫。
5. 趨勢：`Close >= MA20 >= MA60`；確認條件：`Close > trigger_price`、量比 `>= 1.2`、`RSI < 70`、`Close <= entry_ceiling`。
6. 超過 entry_ceiling 或 RSI >= 70 優先 avoid_chasing；其他條件未成立為 wait；必要欄位缺失優先 insufficient，不能因其他正向條件補成 entry_review。
7. 儲存後 trigger／ceiling／invalidation 與規則版本固定；未觸發計畫自 T 起經過 5 個交易日後到期。截止當日收盤仍可評估，下一交易日起 expired。
8. 已觸發計畫後續收盤低於凍結的 invalidation_price，狀態 invalidated；20 個交易日觀察期結束則 completed。使用者亦可手動 cancelled，均保留歷史。
9. 同根日線同時碰觸上下界時只使用收盤確認語意，不推算盤中先後與停損成交；頁面明寫「收盤確認，盤中跳空風險未被消除」。
10. 任何入場建議最早適用於 `generated_at` 之後的下一個完整交易時段。開盤價若跳過 ceiling，不能說可在原價成交；本版不提供即時成交保證。

計算價位保留原始精度與價格調整基準；只在顯示時格式化，判斷不使用已四捨五入字串。拆股／合併使凍結價位不可比時暫停並要求產生新計畫，不事後改寫原計畫。當前 quote 為非正數、時間重複或亂序時拒絕新計畫，不以排序或刪列靜默修復。

門檻 20／60／1.2／70／3%／5 個交易日是產品規則設定，不是研究證明。第一版不提供自由參數搜尋；使用者可改閱讀偏好、追蹤人物、持有狀態，新增策略留給試用回饋。

### 5.3 時間與資料新鮮度

- 應用層注入 `expected_session`，以 America/New_York、既有交易日曆、正式快照發布時點判定最近應有的收盤資料；禁止用台北 `date.today()` 或「週一至週五」估算。
- 必須處理提前收盤、DST、跨年與缺少年份日曆；日曆不完整回 insufficient，不能回退為平日。
- 只要快照落後 expected_session 就不產生新計畫；已存計畫顯示歷史與「本次無法更新」，不把資料中斷當成買賣訊號。
- 外部動態來源失效不刪交易計畫；撤回其 evidence 關聯，顯示「外部理由已撤回」。數據規則可獨立評估，但需記錄這個變更。

### 5.4 共用介面與不可變計畫

新增 `stock_papi/services/trade_plans.py`，只做交易計畫、評估與使用者計畫變更，不放 HTTP client 或 LLM：

```python
def build_trade_plan(snapshot: dict, *, expected_session, generated_at,
                     calendar, evidence_ids: tuple[str, ...] = ()) -> dict:
    """產生規則結果，無副作用；不接受 caller 提供的勝率或行動標籤。"""

def evaluate_trade_plan(plan: dict, snapshot: dict, *, expected_session,
                        evaluated_at, calendar) -> dict:
    """回傳狀態、action、原因與可去重的 event；不覆寫 plan。"""

def apply_assistant_command(state: dict, command: dict, *, now,
                            verified_plan: dict | None = None) -> None:
    """驗證並更新 assistant 子狀態；只在 store.update 內呼叫。"""
```

`plan_id` 由 policy_version、market、symbol、source_snapshot_sha256、凍結條件與排序後 evidence_ids 的 canonical JSON hash 產生；相同輸入不因重按按鈕重複建立。`generated_at`／server observed time 獨立保留，不用變動時間破壞內容去重。

計畫必要欄位：`schema_version=1`、plan_id、policy_version、market、symbol、instrument_type、source_snapshot_sha256、source_ref、data_as_of、generated_at、available_at、eligible_session、expires_session、action、conditions、supporting_evidence、opposing_evidence、limitations、external_evidence_ids。RSI 方法、量比公式與參數版本一併保存。內部 source_ref 只在受控 server 紀錄中保留；前端與匯出只提供安全來源標籤、hash 及可公開的 reader URL，不洩露 bucket 路徑。

資料 adapter 優先保存既有已驗證 reader 的真實 artifact hash／版本；不可只對任意輸入字典重算 hash 就稱已驗證。若 reader 未提供來源 metadata，擴充該 adapter 傳出來源，不另行繞過 reader 抓行情。讀取 catalog 的來源核對時間也由伺服器驗證，不採信 client 傳入 evidence_ids 對應的內容。

觀察狀態為 `watching|triggered|invalidated|expired|cancelled|completed`；更新狀態存 event，不改原始計畫。資料不足是本次評估狀態，不能偷偷把 watching 改成 expired 或 closed。

首次儲存時，action=entry_review 的計畫初始為 triggered，記 `observed_at_save` 與保存時間，不推播補報；其餘可儲存計畫初始為 watching，insufficient 不能儲存為可執行計畫。觸發後的表現起點取 `max(訊號可用時間, saved_at)` 後第一個完整交易時段。已觸發計畫僅因新資料仍符合條件而保持 triggered，不每日追加「再次觸發」。

## 6. 使用者偏好、儲存與回饋

### 6.1 最小 state 擴充

沿用 `line_state.py`、既有兩種 Store 與 `store.update()`，新增一個 assistant 子物件；不另建 ORM 或資料庫。

```json
{
  "assistant": {
    "schema_version": 1,
    "view_preference": "combined",
    "followed_subject_ids": [],
    "followed_creator_ids": [],
    "saved_plans": [],
    "events": [],
    "feedback": [],
    "line_notifications_enabled": false
  }
}
```

- 偏好 enum 為 `data|people|combined`；只改排序與預設頁籤，不改原始事實、策略分數或風險文案。
- 使用者可追蹤最多 20 個對象（人物／帳號合計）；既有 watchlist 上限 12 不變。
- 最多保存 20 份計畫，每份 canonical JSON <= 8 KB；事件最多 200 筆、每筆 <= 1 KB；回饋最多 20 筆、文字 <= 500 字元；assistant UTF-8 JSON 合計 <= 450 KB。
- 到達上限時停止新增，回 `409 assistant_capacity_reached`，提供下載既有紀錄；不得靜默刪最舊紀錄或讓 normalizer 截斷資料。試用後若確實需要長期紀錄，再遷移獨立持久儲存。
- saved_plan 包含不可變 plan、saved_at，以及使用者自填 `position_context=unheld|held`；position_context 改變另記事件，不推定實際成交、成本或數量。
- normalize_state 讀到非法 assistant 時須保留原始可診斷狀態並阻止覆寫該使用者，不能悄悄轉成空 assistant 再存回。舊無 assistant 的使用者可以正常建立預設。
- 所有新增欄位需經 FirestoreStore 與 SupabaseStore 的 load→update→save round-trip；與舊 watchlist／alerts 更新互不抹除。
- 舊 `signals` normalizer 要求 prob，但 observation 提醒可能沒有 prob；新計畫流程不依賴這份 signals 作去重。若修改共用驗證，必須保留舊測試及缺 prob 觀察資料的明確契約。

### 6.2 API 與登入界線

在既有 `stock_papi/web/routes/auth.py` 新增少量 handlers，重用 current_session、csrf_matches、_private，避免複製登入驗證。

| 路由 | 用途與限制 |
|---|---|
| `GET /account/trading` | 我的交易頁；未登入導向 LINE 登入，非試用者顯示尚未開放 |
| `GET /api/account/trading` | 私人 assistant 狀態與當次評估；`Cache-Control: private, no-store` |
| `POST /api/account/trading` | command: `set_preferences|follow_subject|unfollow_subject|follow_creator|unfollow_creator|save_plan|cancel_plan|set_position_context|set_notifications|feedback` |
| `GET /api/account/trading/export` | 本人 JSON 下載，含 plan／event／feedback；不含 access token、內部路徑或別人資料 |
| `GET /api/account/trade-plan/<market>/<symbol>` | 按伺服器資料產生當次計畫；需要登入與試用資格；不在 GET 中永久儲存或發通知 |

POST body 最大 16 KB，未知 action／欄位、錯誤型別、非有限數字回 400；未登入 401、CSRF／非試用 403、來源服務失敗 503。`save_plan` 只接受 `market,symbol,expected_plan_id,evidence_ids,position_context,request_id`；伺服器重算計畫，與 expected_plan_id 不同回 409 stale_plan 並讓使用者重新確認，不能相信客戶端提供的價位。

變更 state 使用 request_id（UUID）去重，store 衝突重試仍只產生一次事件。request_id 由成功事件保存，不能只存在 process memory。純偏好重設相同值可無事件。

### 6.3 試用存取

新增一項設定 `ABSORB_TRADING_BETA_USERS`，逗號分隔有效 LINE user IDs，預設空名單即關閉。只在伺服器解析與比對，不輸出給前端、不寫進 repo、不用 query flag 取得權限。

`config/capabilities.py` 新增 `conditional_advice_allowed(principal: str, allowed_users: frozenset[str]) -> bool`。僅 `line:<有效 ID>` 且名單包含才 true；研究／預測四項既有旗標仍 false。名稱與文案清楚表示這是不同的日線規則能力，不把機率模型偷偷切換 production。

退出試用或清空名單時：停止新建議與推播，允許本人讀取／匯出已存紀錄及關閉通知。回滾前必須保留可辨識 assistant 的 state 程式版本，見第 14 節。

## 7. ASKsorb 與建議規則統一

- `run_absorb_conversation()` 在研究分流前辨識受邀使用者的交易計畫查詢，取得同一個 build/evaluate 結果，再形成回答。
- 將「預測機率／績效」與「可否進場／原計畫是否失效」分開；前者仍受原 capability 限制，後者可回傳規則建議。
- `_observation_conversation()` 的 early return、`_asksorb_grounded_answer()` 的禁止用語清單，以及 `absorb/conversation/prompts.py` 的既有宣告需要一起對齊。
- 對交易計畫使用結構化模板作完整 fallback；LLM 只整理原因，不產生 action、價格、勝率、期限或新來源。LLM 輸出與結構欄位不一致即丟棄其文字，回模板。
- `_research_query_kind()` 加入大咖／人物／持倉／交易揭露意圖；「Pelosi 買 Intel，我也能買嗎」分成來源核對與 INTC 計畫兩個答案區，來源查無紀錄仍能獨立分析有資料的 INTC。
- 模糊人物名稱只提出一個必要澄清；不得查無人物時退回全帳號共識冒充答案。
- 顯示當事人觀點、揭露事實、ABSORB 規則建議三種來源標籤；同一股票的外部樂觀與數據不符時並列矛盾，不投票自動升級買進。
- 未登入或非試用者仍可查公開動態；交易計畫提示申請試用，不洩露別人的計畫或跟隨清單。
- 對話中的追蹤／存計畫／開通知保留既有確認動作，不能把「這個人最近買什麼」當成訂閱同意。

## 8. 提醒與結果紀錄

### 8.1 站內與 LINE

新增 `stock_papi/services/trade_plan_checks.py`，負責 orchestrate 既有 Store、純函式評估及選用 push callback；不用新排程服務。

```python
def run_trade_plan_checks(store, load_snapshot, *, now, calendar,
                         expected_session, allowed_users,
                         push_fn=None, dry_run=True) -> dict:
    """每個 plan／snapshot 最多處理一次，回掃描／變更／失敗計數。"""
```

- 沿用 `/tasks/check-alerts` 的既有授權入口增加一次 trade-plan 檢查；舊提醒照原流程，新結果不靠 `last_triggered_date=today` 判斷。
- 檢查只在有新的、驗證通過的市場快照或外部來源撤回時產生事件；反覆執行相同輸入零新增。
- `event_id = hash(plan_id, snapshot_hash, event_type, new_status)`；同一存入交易以 store.update 的重試機制去重。
- 有意義事件限：條件達成、計畫失效、到期、外部理由撤回、由正常轉資料中斷／恢復。持續等待與持續缺資料不每日洗版。
- 首次儲存已符合條件的計畫，在頁面呈現即可，不立即補發一則「剛觸發」。只提醒儲存後的新變動。
- 站內事件先可靠保存；LINE 只對仍在試用名單、本人已啟用通知且未取消的計畫寄送。發送前重新核對退出／取消狀態。
- 不允許單次不明網路錯誤造成無限重送：每筆 delivery 記 `pending|sending|sent|failed|unknown`。發送前用 CAS 取得 claim；成功寫 sent；明確未接受可重試；逾時或接受後回寫失敗標 unknown，停止自動重送並保留站內訊息。
- 第一版不承諾 LINE exactly-once。若既有 SDK／供應商可驗證支援 idempotency key，可用 event_id 對應穩定 retry key；未驗證前不得在規格或 UI 聲稱有保證。
- 不更動現有排程時段。執行前盤點 `/tasks/check-alerts` 是否真的有自然排程、涵蓋美股快照完成後；若需新增或調時段，在試用發布清單另列確切差異及授權，不直接補建。

### 8.2 後續觀察

第一版做「訊號後市場表現」，不是交易帳戶損益：

- 以系統產生且使用者儲存後的首次有效觸發 `available_at` 為時間基準，取其後第一個完整交易時段的原始開盤價作參考價。
- 顯示該參考日後第 5／20 個交易日收盤相對變化，日期及參考價可展開；歷史序列須一致的公司行動調整基準，否則該期 unavailable。
- 尚未到觀察日顯示「觀察中」；沒有開盤價、停牌、缺棒顯示缺項，不用收盤價假裝開盤成交。
- 不將這個數字稱為名人報酬、跟單報酬、策略淨報酬或實際獲利；不發布勝率榜。若後續要做策略回測，另加入滑價、成本、可成交性與完整進出場規則。
- waiting／expired／cancelled／invalidated 的計畫也保留，不能只留下成功觸發者；任何統計明列總計畫、可評估、未成熟、缺資料數量。
- 既有 `calculate_outcome()` 使用 published_at／收盤價的算法不直接沿用為可交易成效，避免前視與商品差異。

## 9. 頁面與最小 UI 改版

| 頁面 | 改動 | 驗收重點 |
|---|---|---|
| `/perspectives` | 大咖動態、來源類型頁籤、中文篩選、追蹤按鈕 | 官方／自述／觀點標籤；公開日和交易日同時可見 |
| `/perspectives/<creator_id>` | 保留帳號頁與舊連結；加該發布者的相關動態 | 不把發布者誤顯示為交易所有人 |
| `/perspectives/subjects/<subject_id>` | 新增人物／機構頁，身份、來源範圍、時間線 | 身分與帳號不同；unknown ID 404；來源故障不變成不存在 |
| `/perspectives/stocks/<market>/<symbol>` | 股票相關觀點＋揭露，各自分組 | TW／US／ADR 不混算，期權不冒充股票交易 |
| `/stock/<code>` | 受邀使用者先見條件式計畫，再往下看原圖表與資料 | 不改舊報告數值；資料不足有原因與可用來源 |
| `/account/trading` | 偏好、追蹤人物、已存計畫、變動、回饋／匯出 | 舊 watchlist 可連入；兩帳號資料隔離 |
| `/us` 與導航 | 受邀者顯示「我的交易」入口與近期動態連結 | 不在公共快取首頁直接塞私人內容；私人區由 no-store API 載入 |
| `/ask` 與 quick ask | 同一計畫結果、可追問理由／失效條件 | 跟個股卡的 action、日期、價位一致 |

沿用目前品牌與元件，不另外做整站視覺重設。桌面以清楚列表比較人物與操作；390×844 手機改為單欄動態卡，四個關鍵欄位「人物、行為、交易／基準日、揭露日」不可隱藏。長來源 URL 自動斷行；按鈕至少 44px，鍵盤可操作，狀態不能只靠顏色。

## 10. 資料來源與營運界線

以下是影響產品語意與資料取得的具體來源，不是對 ABSORB 現況的法律許可認定。

- **美國眾議院 PTR：** 官方說明以知悉交易後 30 日或交易後 45 日較早者為一般期限，部分需申報交易門檻為超過 1,000 美元。產品因此必須保留交易與揭露兩個日期，不能稱為即時追蹤。[House Ethics Financial Disclosure](https://ethics.house.gov/financial-disclosure/)
- **SEC 13F：** 主要為季底的申報證券持倉，通常於季末後 45 日內提交；不包含完整空頭部位。依兩期推得的是申報持倉變化，不是逐筆交易。不同表單版本金額單位需按文件核對。[SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f)
- **國會揭露使用限制：** 5 USC 13107(c) 對報告的商業用途等有明文限制及新聞傳播例外；公開可讀不等於可任意商品化。匯入前記錄實際試用用途與使用依據；無法確認時只保留官方來源入口，不能透過第三方轉載繞過。[美國法典原文](https://uscode.house.gov/view.xhtml?req=%28title%3A5+section%3A13107+edition%3Aprelim%29)
- **台灣營運：** 投信投顧法第 4、6 條涉及有報酬的證券分析／推介及業務資格；免費同學試用不是自動豁免結論。正式收費、公開招攬或個人化配置前，按實際服務確認適用範圍。[金管會法規](https://law.fsc.gov.tw/LawContent.aspx?id=FL030633)
- 不簽署新條款、不購買資料、不接受未確認的商用授權。對未知來源不取巧補入；可以繼續完成頁面、validator、既有觀點、SEC 持倉與交易計畫的其他部分。

## 11. 檔案責任與介面總覽

所有路徑相對 repository root；未標「新增」者為已核對的現有路徑。

| 檔案 | 責任 |
|---|---|
| `stock_papi/services/public_opinions.py` | 新增 activity／subject 驗證與 query，不重寫 opinion 共識 |
| `stock_papi/services/research_catalog.py` | v2 相容讀取新增欄位及 source 状態 |
| `stock_papi/batch/public_activity_cli.py`（新增） | 本機候選 JSON 驗證與不覆寫輸出 |
| `data/research/public-opinions.json` | 經核對的來源與資料，小量增補，保留舊 ID |
| `docs/research/public-activity-sources.md`（新增） | 來源、使用範圍、核對日期、操作種子資料清單 |
| `stock_papi/services/trade_plans.py`（新增） | build／evaluate／assistant command 純函式 |
| `stock_papi/services/trade_plan_checks.py`（新增） | 存取 state、評估事件與可選通知，無策略數學 |
| `stock_papi/config/capabilities.py` | beta allowlist 的條件建議能力，保留原預測旗標 |
| `line_state.py` | assistant 正規化、大小與並行保存 |
| `stock_papi/web/routes/auth.py` | 新的私人交易／回饋／匯出端點，重用安全邊界 |
| `stock_papi/web/routes/research.py` | 動態查詢／subject 頁，保留舊 route |
| `stock_papi/web/routes/market.py` | 股票頁接共用 plan builder；匿名仍是原研究視圖 |
| `stock_papi/web/route_registration.py`、`stock_papi/application.py` | 注入 raw snapshot／calendar／clock／capability；ASK 路由與排程接線 |
| `absorb/conversation/prompts.py`、`policies.py` | 有依據的條件建議與 unsupported 預測分流；保留注入防護 |
| `stock_papi/integrations/line/notifications.py`、`webhook.py`、`flex.py` | 舊提醒不回歸，新計畫訊息、選擇性發送 |
| `templates/perspectives.html`、`creator.html`、`stock_perspectives.html` | 大咖動態的三種現有視圖 |
| `templates/subject.html`、`account_trading.html`（新增） | 兩個確實新增的頁面 |
| `templates/stock_detail.html`、`account_watchlist.html`、`base.html` | 共用計畫卡、入口、登入後導覽 |
| `static/app.js`、`static/app.css` | 少量表單與互動；依實作基線確認是否有生成來源 |
| `tests/test_public_opinions.py`、`test_research_catalog.py`、`test_research_routes.py` | 新來源／活動契約與路由回歸 |
| `tests/test_trade_plans.py`、`test_trade_plan_checks.py`（新增） | 規則、時間、紀錄、提醒核心行為 |
| `tests/test_line_state.py`、`test_line_login.py` | 儲存往返、權限、CSRF、並行更新 |
| `tests/test_absorb_research_integration.py`、`test_absorb_conversation.py`、`test_absorb_conversation_web.py` | 三端同義與未知來源／注入處理 |
| `tests/test_prediction_capability.py`、`test_route_inventory.py`、`test_web_product.py` | capability、路由與顯示契約 |
| `DESIGN.md`、`docs/line-to-web-map.md` | 條件建議的新產品定位與最小導航對照 |

## 12. 執行任務與順序

依序執行 `0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9`。每批先有能失敗的契約檢查，再寫最小實作；沿用 unittest，不增加測試框架。以下程式碼是實作規格／測試範例，不能當成已實作結果。

### 任務 0：保護既有工作並固定實作基線

**檔案：** 本計畫、現有 dirty diff；必要證據放新建 `artifacts/trading-assistant-v1/`，不覆寫舊 artifacts。

- [ ] 執行 `git status --short`、`git diff --stat`、`git diff --name-only`、`git rev-parse HEAD`，保存結果。
- [ ] 檢查是否有正在同檔工作的任務；只有必要隔離時才建立 `codex/trading-assistant-v1` worktree；不得假設未提交的 LINE 樣式已在新 worktree 中。
- [ ] 對照目前 HEAD、已核准基線與涉及的 dirty diff，記錄哪些既有變更必須包含；不憑記憶 cherry-pick 或遺漏。
- [ ] 跑現有相關基線測試，記錄原本就有的環境失敗；不要在這批修無關排程。
- [ ] 確認 raw snapshot reader、目前 style 來源、auth 與 Store backend；無法讀正式站不阻止本機開發，但不得宣稱正式功能可用。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_public_opinions tests.test_research_catalog tests.test_research_routes tests.test_line_state tests.test_line_login tests.test_prediction_capability
```

**完成條件：** 可重現的基線、dirty 清單與測試結果；沒有遺失使用者既有改動。

### 任務 1：操作紀錄契約與時間／去重

**修改：** public_opinions.py、research_catalog.py、其現有測試。  
**Consumes：** 舊 v2 catalog。**Produces：** 第 4 節 `validate_activity()`、`query_activities()` 及帶 activities 的相容 catalog。

- [ ] 在 `tests/test_public_opinions.py` 新增一個小測試類別，涵蓋同一文件兩列、同一列重複、owner=spouse、13F 無交易日、期權不可當股權買入、available_at、未來修訂、未知代碼與惡意 URL。
- [ ] 先跑下列測試確認新增介面／行為未存在而失敗。
- [ ] 實作第 4 節驗證與查詢；保留 raw row 與 errors，但未審正文不送入 public feed／LLM。
- [ ] 加 load_opinions 的舊 catalog 相容測試，確認無 activities 時仍可載入原六筆 confirmed。
- [ ] 全部相關檢查通過後，只提交本批列明檔案。

```python
# 添加在現有 test 檔；fixture 為測試內人工資料，不進正式 catalog。
def test_activity_is_not_known_before_review(self):
    row = self.activity(public_at="2026-09-01T20:00:00Z",
                        first_seen_at="2026-09-02T01:00:00Z",
                        reviewed_at="2026-09-02T03:00:00Z")
    catalog = self.activity_catalog([row])
    result = query_activities(catalog, subject_id=None, market="US",
                              symbol="INTC", cutoff_at=datetime.fromisoformat(
                                  "2026-09-02T02:00:00+00:00"), window_days=28)
    self.assertEqual(result, [])
```

此測試類別的 `activity()` 必須建立全部第 4.1 節必要欄位：subject=`test-household`、owner=spouse、source_kind=house_ptr、文件 ID=`test-001`、locator=`page:1,row:1`、instrument_type=common_stock、transaction_date=2026-08-28、review_status=confirmed、rights_status=approved、source_status=available、來源 hash 為測試 bytes 的 SHA-256。`activity_catalog(rows)` 以 verified 測試 subject 和這些 rows 呼叫 build_catalog；測試來源使用白名單官方網域，不能開放任意 host 讓 fixture 通過。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_public_opinions tests.test_research_catalog tests.test_opinion_consensus
```

**驗收：** cutoff 前結果為零；修訂在自己的可用時點才生效；操作不改變原觀點分母。

### 任務 2：核對種子來源、匯入與大咖動態頁

**新增：** public_activity_cli.py、public-activity-sources.md、subject.html。  
**修改：** reviewed catalog、research.py、三個現有觀點模板、base.html、CSS、research routes 測試。  
**Consumes：** 任務 1 catalog。**Produces：** 四種內容可區分的大咖動態頁與來源核對紀錄。

- [ ] 查核既有五帳號，不重新命名／換 ID；新增 Pelosi 家庭與 Berkshire 的 subject 身分來源，未知的法律身分不硬補。
- [ ] 取得可用範圍已確認的原始操作／持倉來源；記 source URL、日期、定位、owner、instrument、rights。Pelosi–INTC 未證實就明列「未證實」，不產生虛構案例。
- [ ] 以 tempfile 建立 CLI 測試：輸入錯誤、output 已存在、input==output、同來源兩筆；確認失敗不動原檔。
- [ ] 實作 bounded CLI，人工核對後生成候選；經 diff 核對再更新 catalog。
- [ ] 在 research routes 先加入「未核對／cutoff 之後列不顯示」「同文件兩列都顯示」「只有揭露日則交易日未提供」「未知 subject 404」測試，再接上 query。
- [ ] 實作動態頁籤與中文標籤，依第 3 節做 pagination、filter round-trip、來源連結與未知代碼 CTA 禁用。
- [ ] 保留 opinion 原始 API 語意與舊網址；更新 route inventory。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_public_opinions tests.test_research_catalog tests.test_research_routes tests.test_opinion_consensus tests.test_route_inventory
```

**驗收：** 至少一組真實操作／持倉紀錄及來源可 read-back；若政治人物來源 pending，明確標該部分未開放，不把整個功能說成完整即時國會交易追蹤。

### 任務 3：日線規則與不可變交易計畫

**新增：** trade_plans.py、test_trade_plans.py。  
**修改：** capabilities.py、test_prediction_capability.py。  
**Consumes：** 已驗證 raw snapshot、calendar、expected_session、aware generated_at。**Produces：** 第 5 節的 build／evaluate 結果與 `conditional_advice_allowed()`。

- [ ] 建立 61 個已完成美股 session 的最小 fixture；OHLC／Volume 合法、MA／RSI 方法固定，fixture 明確是人工測試資料。
- [ ] 寫規則邊界測試：trigger 不含當日 High；量比 1.2；RSI 70；ceiling 等號；NaN／bool／負量／缺日；失效價不低於 trigger；未知商品；公司行動不可比。
- [ ] 用 table-driven subTest 測試 held／unheld 的文字映射，以及 wait→triggered→invalidated／completed、未觸發→expired、cancelled 的終止狀態。
- [ ] 實作純函式，既有 recommendation_engine 不變，不填假 probability／sample_count。
- [ ] 檢查同一內容 plan_id 穩定、未來 snapshot 不可用、同一 snapshot 重評不產生新 event；不同 snapshot 即使同日修正也保存其版本差異。
- [ ] capability 測試確認 allowlist 空值關閉、非本人無權、原有四項 prediction flags 完全不變。

```python
def test_beta_advice_does_not_enable_predictions(self):
    from stock_papi.config.capabilities import conditional_advice_allowed
    principal = "line:U" + "a" * 32
    self.assertTrue(conditional_advice_allowed(principal, frozenset({principal[5:]})))
    self.assertFalse(conditional_advice_allowed("public:test", frozenset()))
    with patch.dict(os.environ, {"ABSORB_PREDICTION_MODE": "research"}, clear=True):
        state = PredictionCapabilityState.from_environment()
    self.assertFalse(state.probability_allowed)
    self.assertFalse(state.strong_action_allowed)
```

```powershell
.venv\Scripts\python.exe -m unittest tests.test_trade_plans tests.test_prediction_capability tests.test_recommendation_engine tests.test_batch_calendar tests.test_us_calendar
```

**驗收：** 每個 action 有可重現前提；未成熟機率不妨礙規則分析，但不對外升格成機率建議。

### 任務 4：儲存偏好、追蹤人物、交易計畫與回饋

**修改：** line_state.py、trade_plans.py、auth.py、route_registration.py、test_line_state.py、test_line_login.py、route inventory。  
**Consumes：** 任務 3 verified_plan。**Produces：** 第 6 節 API 及可往返保存的 assistant 子狀態。

- [ ] 在現有 State 測試加合法 assistant 往返、非法 assistant 不覆寫、容量上限、偏好改變不重算舊計畫、watchlist mutation 保留 assistant。
- [ ] 使用現有 Store 測試 fake transport 覆蓋 Firestore 與 Supabase：第一次更新衝突後重試，request_id 仍僅保存一份計畫／事件。
- [ ] 實作 assistant 正規化、apply_assistant_command、容量檢查及非破壞性錯誤。
- [ ] 在 auth 測試加兩個不同 session、CSRF、非邀請名單、偽造 user_id／price、expected_plan_id 過期、JSON body 超限。
- [ ] 在 auth.py 內沿用驗證 helper 加新 handlers，交易計畫 API 由 route dependency 注入 builder，不自行抓未驗證即時行情。
- [ ] 實作純文字回饋與 JSON export；500 字元以上回錯誤，不靜默裁切；export 不含原始憑證。

```python
def test_watchlist_update_keeps_assistant_preferences(self):
    state = empty_state()
    apply_assistant_command(state, {"action": "set_preferences",
        "view_preference": "people", "request_id": "00000000-0000-4000-8000-000000000001"},
        now=datetime.fromisoformat("2026-09-24T00:00:00+00:00"))
    before = copy.deepcopy(state["assistant"])
    add_watch(state, "INTC", "Intel", now=1.0)
    self.assertEqual(normalize_state(state)["assistant"], before)
```

上述例子釘住偏好往返；同一測試類別另以任務 3 的完整 verified_plan 呼叫 save_plan，驗證已存計畫保留，不用半套 dict 假裝有效 plan。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_line_state tests.test_line_login tests.test_trade_plans tests.test_route_inventory
```

**驗收：** 重新登入仍可看到自己的偏好、人物、原始計畫與回饋；其他帳號／匿名完全不可讀。

### 任務 5：Web 與 ASKsorb 共用條件建議

**修改：** application.py、route_registration.py、market.py、auth.py、conversation prompts／policies、對話與研究整合測試。  
**Consumes：** 任務 1 活動 query、任務 3 plan、任務 4 session／存計畫端點。**Produces：** 三種入口同一事實、同一計畫版本。

- [ ] 先測試「研究模式＋受邀：INTC 可以買嗎」回規則建議；「研究模式＋非受邀」不回新建議；「上漲機率幾成」不被放行。
- [ ] 測試「Pelosi 買 Intel」未找到核對紀錄時不承認前提；若有 spouse option 則完整說清來源／商品，不能簡化為她買普通股。
- [ ] 在研究 early return 前加受控分流，外部活動先 query，計畫由共用 builder 建立；不另寫一份模型判斷。
- [ ] prompt 與 post-validation 接同一 plan；故意讓 LLM 回不同價位／更強 action／惡意來源指令，驗證回落結構模板。
- [ ] 檢查既有 web／LINE action confirmation 與私人查詢沒有因新分流失效。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_absorb_research_integration tests.test_absorb_conversation tests.test_absorb_conversation_web tests.test_absorb_security tests.test_observation_public_surfaces
```

**驗收：** 相同 plan_id 在 Web、ASK 與通知的 action／conditions／date 一致；舊無建議測試只對新 beta 邊界調整，匿名與未受邀回歸保留。

### 任務 6：我的交易、個股計畫與追蹤互動

**新增：** account_trading.html。  
**修改：** stock_detail.html、account_watchlist.html、base.html、既有大咖模板、app.js、app.css、test_web_product.py。  
**Consumes：** 任務 4、5 API。**Produces：** 同學能從來源走到計畫、儲存、回饋的完整流程。

- [ ] 在頁面測試加入可見結論、來源日期、失效條件、action 中文、非試用者狀態、長來源文字與外部連結安全屬性。
- [ ] 加「我的交易」導覽與三種閱讀偏好；預設綜合，不新增強迫問卷。
- [ ] 個股頁渲染計畫卡並可儲存；重複提交 disabled 與 server idempotency 並用，409 重新顯示最新計畫。
- [ ] 大咖頁的追蹤／取消與本人清單連動；追蹤不等於自動開 LINE 通知。
- [ ] 建立簡短回饋表單：分類、是否有幫助、自由文字；自動附 page／plan_id／activity_id／policy_version，敏感聊天內容不自動附上。
- [ ] 不在公共 cache response 裡放登入者名稱、偏好或計畫；私人區 fetch no-store API。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_web_product tests.test_research_routes tests.test_line_login tests.test_route_inventory
node --check static/app.js
git diff --check
```

**驗收：** 真實 390px 手機與桌面可完整完成流程；不能以字串測試取代瀏覽器驗收。

### 任務 7：計畫變更事件、站內提醒與後續觀察

**新增：** trade_plan_checks.py、test_trade_plan_checks.py。  
**修改：** trade_plans.py、line_state.py、account_trading.html。  
**Consumes：** saved_plans、不可變 raw snapshot。**Produces：** 可去重事件與 5／20 日市場後續觀察。

- [ ] 先測試重跑同 snapshot、兩個 worker 同時更新、source revision、過期／停牌／公司行動、event 空間滿的可見失敗。
- [ ] 實作 dry_run，預覽事件但不寫 Store、不通知；正常模式在 store.update 中核對該 plan 仍存在且未取消再附 event。
- [ ] 逐個新的 session 評估；排程漏跑後補算須使用各日當時可用的快照，不能拿最新價倒灌；缺任一天則記 coverage gap，不聲稱完整觸發歷史。
- [ ] 依第 8.2 節算 reference-session open 到 5／20-session close；reference 在真正觸發之後，不使用名人交易日。
- [ ] 頁面顯示原始計畫、狀態變更與觀察中的欄位，與當前新建計畫分開。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_trade_plans tests.test_trade_plan_checks tests.test_line_state tests.test_batch_calendar tests.test_us_calendar
```

**驗收：** 同資料重跑新增 0 事件；缺資料不計虛假成效；成功／失敗／到期計畫全部可讀。

### 任務 8：接上既有提醒入口與選擇性 LINE 訊息

**修改：** line/webhook.py、notifications.py、flex.py、application.py、route_registration.py、test_trade_plan_checks.py、test_absorb_line_presentation.py。  
**Consumes：** 任務 7 events。**Produces：** 原授權排程入口的新計畫評估與 opt-in 通知。

- [ ] 先測試通知關閉、退出試用、取消 plan、兩 worker claim、供應商明確拒收、timeout 不明、send 成功後 store 失敗；核對不錯報 sent、不無限重送。
- [ ] 新增最小 Flex 文案：變更原因、資料日、計畫狀態、單一「查看計畫」CTA；不重做 Rich Menu 圖片。
- [ ] 串接 `/tasks/check-alerts`，dry-run／fake push 驗證舊價位提醒與新計畫互不影響。
- [ ] 只對已明確同意測試推播的帳號做一次真實 read-back；沒有同意則保留 fake push 結果，LINE 實際送達標未驗證。
- [ ] 實際排程啟用／調時段及人員名單列入發布紀錄；不因單次手動成功稱為自然排程通過。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_trade_plan_checks tests.test_line_state tests.test_notification_gate tests.test_absorb_line_presentation
```

**驗收：** 站內先有可回查 event，只有 opt-in 收到新變更；unknown delivery 不冒充送達或盲重發。

### 任務 9：整合、瀏覽器驗收與試用包

**修改：** DESIGN.md、line-to-web-map.md；新增 `artifacts/trading-assistant-v1/ACCEPTANCE.md` 與 `TRIAL-GUIDE.md`（執行期產物）。

- [ ] 執行第 13 節測試與瀏覽器案例；保留狀態、最終 URL、截圖、console／network、兩帳號證據。
- [ ] 逐條對照第 1 節使用流程，任何必備步驟未完成不能標 V1_READY。
- [ ] 來源資料與開關另出發布清單：版本 SHA、catalog_version、hash、邀請名單設定是否完成（不公開完整 ID）、通知 opt-in 狀態。
- [ ] 用本機或受控候選版本完成 reviewable 結果，再進第 14 節對外步驟。所有 production／排程／外部訊息變更按實際授權執行。
- [ ] 產出 1 頁試用說明及反馈問題，不要求同學實際下單才可試用。

## 13. 驗證矩陣與完成門檻

### 13.1 自動檢查

相關小批檢查每批執行一次；整合後再跑全套。不要因 docs 計畫已寫完就宣稱下列測試已通過。

```powershell
.venv\Scripts\python.exe -m unittest tests.test_public_opinions tests.test_research_catalog tests.test_opinion_consensus tests.test_research_routes tests.test_trade_plans tests.test_trade_plan_checks tests.test_line_state tests.test_line_login tests.test_prediction_capability tests.test_recommendation_engine tests.test_absorb_research_integration tests.test_absorb_conversation tests.test_absorb_conversation_web tests.test_absorb_security tests.test_web_product tests.test_route_inventory
.venv\Scripts\python.exe -m unittest discover -s tests
node --check static/app.js
git diff --check
```

若 Windows Task Scheduler 權限造成已知環境失敗，保存測試名稱與原始錯誤，將「產品測試結果」與「環境阻擋」分開；不可刪測試、改成永遠 skip 或將整套稱為全綠。若實作基線有 CSS generator，再跑其實際 build/check；不存在就不聲稱跑過。

### 13.2 必須使用瀏覽器的驗收

桌面 1440×900 與手機 390×844，至少各完成下列案例；頁面來源用真資料，故障與特殊案例在測試模式注入，不能公開假資料。

| 案例 | 期望與證據 |
|---|---|
| 未登入看大咖 | 能看已核對公開內容；追蹤導向登入；不洩露私人資料 |
| A／B 兩位使用者 | A 追蹤人物、存計畫，B 看不到；B 偽造 ID 仍無效 |
| 四種資料類型 | 官方交易、自述、機構季底、觀點都有正確中文標籤 |
| Pelosi／INTC 問句 | 未核對不承認前提；配偶／期權不可偷換成她本人買普通股 |
| 多列與修訂 | 同文件不同列都在；重複轉貼不加操作數；修訂保留可追溯歷史 |
| 截止日／窗口／換頁 | 所有 URL round-trip，清單與統計時間一致，未來／未審不顯示 |
| 不同偏好 | 改 data／people／combined 只改入口排列，計畫內容與既有狀態不變 |
| 儲存／刷新／另一裝置 | 計畫仍在；雙擊不重複；來源已更新時 409 有可理解提示 |
| ASK 與個股卡 | plan_id、action、價位、日期相同；LLM unavailable 仍能用模板 |
| 過期／缺棒／停牌 | 新建議停止，歷史仍可讀；不顯示 0 或假即時數字 |
| 提醒去重 | 同快照兩次執行只有一次站內事件；LINE 未 opt-in 零發送 |
| 手機操作 | 無整頁橫向溢出；來源、日期、失效條件可見；鍵盤／焦點正常 |
| 回饋與匯出 | 提交後可讀回，JSON 是本人的完整紀錄，不含憑證 |
| 舊路徑回歸 | `/`、`/market`、`/us`、`/reports`、`/reports/us`、舊自選與 LINE 查詢可用 |

每個證據至少記 final URL、HTTP 狀態、畫面內容、功能結果、console／network 異常；不能只保存 screenshot 就說 CTA 與寫入成功。

### 13.3 可交給同學的最低條件

- 5–10 位是招募目標，不是測試樣本保證；先有兩個隔離測試帳號證明權限。
- 至少一组真實可核對操作／持倉資料；三個已驗證 X 帳號仍可正常閱讀；兩個未核對帳號不冒充已上線 feed。
- 一檔資料完整的支援美股能走完：來源／個股→建議→存計畫→新資料評估→站內提醒→回饋；INTC 若無合格行情，明說其限制而不是挑測試股票冒充 INTC 已完成。
- 2 週觀察只評估使用體驗、語意與穩定性，不宣稱策略已獲驗證。
- `LOCAL_VERIFIED`：本機產品與瀏覽器通過；`BETA_READY`：受控對外版本、登入、資料更新與通知界線均驗證；正式切流後才可使用 `PRODUCTION_VERIFIED`。

## 14. 試用發布、回滾與停止條件

### 14.1 分批發布

1. **本機完成：** 所有必備功能、fixture 與瀏覽器流程通過，邀請名單預設空；只交付可審查 diff／測試證據。
2. **候選版本：** 依選定環境的既有發布流程建立候選；讀回 source SHA、catalog 版本、資料快照時間、auth callback、cookie／CSRF。不能只知道 HEAD 就認定候選用同一份來源。
3. **小範圍試用：** 經對外發布授權後配置邀請名單；兩個測試帳號走完整流程，再交同學網址。真實 LINE 推播須是已 opt-in 帳號，首次通知另核對送達。
4. **資料與排程：** 確認 reviewed catalog 在候選端可讀；觀察美股快照自然更新與一次正常排程。手動觸發成功只記 manual recovery／manual test。
5. **一般正式流量：** 只有另有正式切流授權才執行；讀回 Cloud Run `status.traffic`、來源標記、GCS artifact／pointer 與正式網址。既有 ObservationOnly verifier 若不理解 beta 邊界，補相應驗證，不能繞過或誤報。

### 14.2 回滾

- 第一選擇清空 `ABSORB_TRADING_BETA_USERS`，停止新計畫／推播；保留私人歷史讀取及匯出。
- UI 回退可隱藏新入口；舊觀點與報告維持。資料 catalog 回退至已驗證版本，不刪原始來源與修訂紀錄。
- **不能直接回滾到不認識 assistant 欄位的舊執行版本後繼續寫 state。** 舊 normalize_state 可能抹除新資料。先備份、暫停相關 state 寫入或使用保留欄位的相容回滾版本，再處理程式回退。
- 已推送訊息不能撤回成「沒發生」；保留事件與 delivery 狀態，修正時追加更正。

### 14.3 停止相關操作的具體條件

- 未授權存取、CSRF 漏洞、跨帳號資料或秘密外洩：停止對外試用直到修復。
- 真資料被補值、偽造來源、交易人與發布者混淆、期權當股票、前視結果：停止相關建議／動態發布。
- 未知 source rights／自動要求購買資料：停該来源接入，其他任務繼續；頁面清楚標示未開放。
- 無法保存／去重、Store 衝突導致資料遺失、通知重送不受控：停止相關寫入／推播，保留讀取與證據。
- 實作基線與本機現況不同：先重新映射路徑與差異，不能在錯誤 checkout 強套整檔覆蓋。
- 未取得正式發布、排程或外部通知授權：完成可審查程式、測試、候選操作清單再處理對外步驟，不以此中斷前面的本機工作。

## 15. 同學試用與回饋如何決定下一版

### 15.1 試用任務

發給同學的說明限定五件事，不要求實際買賣：

1. 選一個偏好的資訊入口，追蹤兩位對象或兩檔股票。
2. 找一筆動態，說明「誰的什麼操作、何時發生、何時才公開」。
3. 讀一份交易計畫，說明何時可評估進場、何時失效。
4. 儲存計畫，下次登入看變化；自行決定是否開 LINE 通知。
5. 提交一則最有幫助／最困惑的回饋。

### 15.2 收集方式與衡量

- 第一版不装第三方行為追蹤工具；以本人已同意保存的 follow／save／event／feedback 與自願訪談衡量。
- 問題固定為：你從數據還是人物開始？是否分得出實際交易／觀點？看完能否說出下一步？缺少哪一種策略？最想刪掉哪個內容？
- 目標：至少 80% 完成核心任務的受測者能正確說明揭露延遲與計畫失效條件；同時列完成者與受邀者分母，不能拿兩位成功者代表全班。
- 檢查儲存後跨 session 再回訪的人數；不蒐集秘密的全站 session replay。
- 零容忍：錯歸属交易、私人資料洩露、未 opt-in 推播、改寫歷史計畫；這些不以滿意度抵銷。
- 兩週後產出短表：實際使用人數、成功完成流程數、理解錯誤、來源新鮮度問題、回饋分類與下一版前三優先項。未滿觀察天數的成效欄位繼續顯示觀察中。

### 15.3 第二版才考慮的內容

只有回饋與資料支持才擴充：台股交易計畫、第二套長期／拉回策略、使用者自訂條件、更多人物與自動來源、長期紀錄獨立儲存、完整交易成本回測、個人化風險與配置、持牌合作、即時行情與券商整合。第一版不預先建抽象策略工廠或空的 provider 平台。

## 16. 本計畫的覆蓋檢查

| 使用者要求／已同意方向 | 對應 |
|---|---|
| 第一版可給同學試用 | 1、6、13、14、15 |
| 不同人喜歡不同策略／名人 | 1.3、3、6.1、15.3；偏好與真正策略能力明確分開 |
| 加強現有大咖版面 | 2、3、4、任務 1–2、6 |
| 有依據的具體建議 | 5、7、任務 3、5 |
| 交易計畫與觀察清單 | 6、9、任務 4、6 |
| 條件改變提醒 | 8、任務 7–8 |
| 建議可追蹤、能檢討 | 5.4、8.2、15 |
| 沿用現有功能、避免過度建設 | 2、11、15.3 |
| 完整檔案、順序、測試、瀏覽器、停止條件 | 11–14 |

本文沒有把缺少來源、授權或正式環境查核寫成已完成；沒有要求先回答非必要問題才能產出計畫。下一步是依本計畫開始實作的明確授權；此次工作到 Markdown 計畫與其檢查為止。
