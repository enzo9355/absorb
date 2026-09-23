# 交易助手 v1 驗收（執行期產物）

日期：2026-09-24（Asia/Taipei）。狀態：**LOCAL_VERIFIED＋候選版已建（0% 流量）**。
非 `BETA_READY`（beta 名單、真實推播未驗），更非生產切流。部署前須另行授權（見 RELEASE-CHECKLIST；A 已執行，B／C／D 待授權）。

## 基線異動說明

- 任務 0 基線 HEAD 為 `b56e9f1850f14c7bedcf663b69ca411188d9fdc6`（含 36 檔 dirty）。
- 執行期間分支新增提交 `5986074 fix: line crash guards, honest missing-data rendering, deploy gaps and web UX`。
- 本次未 reset/clean/覆蓋既有改動；所有實作以修改工作樹疊加，未 cherry-pick 或遺漏基線 dirty（含 LINE Flex/presentation、對話 policies/web、app factory、market、模板、CSS/JS）。
- 本機 dirty（含本次 10 任務實作）尚未提交；不將任何 HEAD 當作正式站版本。

## 自動檢查（§13.1）

- 目標清單 323 項：`test_public_opinions test_research_catalog test_opinion_consensus
  test_research_routes test_trade_plans test_trade_plan_checks test_line_state test_line_login
  test_prediction_capability test_recommendation_engine test_absorb_research_integration
  test_absorb_conversation test_absorb_conversation_web test_absorb_security test_web_product
  test_route_inventory test_public_activity_cli test_trade_plan_conversation` — **全數通過**
 （見 `task1-tests.log`…`task8-tests.log`）。
- `node --check static/app.js` 通過；`git diff --check` 通過（僅既有 LF/CRLF 警告）。
- 全量 `discover -s tests`：1774 項；稽核回歸 1 項已修（下）；其餘 4 項經乾淨 HEAD
  worktree 證偽與本次無關（見下節），測試保留、不刪、不 skip、不稱全綠：
  - `test_observation_views.test_stock_view_contains_only_actual_observations`（ERROR，return_5d_pct None）
  - `test_tw_security_master.test_market_signal_does_not_reuse_an_artifact_name_for_taiwan_symbol`（ERROR）
  - `test_pipeline_scheduler.test_mutex_abandonment_and_partial_timeout_release_exactly_once`（FAIL，mutex）
  - `test_us_adversarial_failures.test_typed_exceptions_error_classification`（FAIL，OP_FAIL vs R）
- `test_notification_gate` 在本庫不存在；其推播狀態機覆蓋已納入 `test_trade_plan_checks`（7 項通過）。
- 回歸：本次新增被稽核掃到 1 項（`trade_plans._validate_plan_daily_rows` 觸及 `daily`
  鍵），已在 `test_persisted_daily_reader_audit.py` 以 `NON_PERSISTED_BUILDERS`
  顯式豁免（純記憶體驗證器，非持久化 reader），原测试仍全過。

## 全量其餘 4 項的歸因（已證偽與本次相關）

乾淨 HEAD worktree（`5986074`，不含本次未提交變更）重跑同樣 2 失敗＋2 錯誤，
見 `preexisting-failures-head-clean.log`。故以下與本次變更無關，列基線／環境待查：

- `test_observation_views.test_stock_view_contains_only_actual_observations`（ERROR）
- `test_tw_security_master.test_market_signal_does_not_reuse_an_artifact_name_for_taiwan_symbol`（ERROR）
- `test_pipeline_scheduler.test_mutex_abandonment_and_partial_timeout_release_exactly_once`
 （FAIL，mutex；极可能為 Windows Task Scheduler 權限環境問題，計畫 §13.1 已預告此類拆分）
- `test_us_adversarial_failures.test_typed_exceptions_error_classification`（FAIL）

## 瀏覽器驗收（§13.2）— 真實 Chrome 取證（`browser/`）

以本機 harness＋真實 Chrome headless（1440×900／390×844）渲染驗證。
harness 使用**真實模板、真實 catalog 檔（含種子）、真實規則 builder 產生的 INTC
計畫**；僅登入（`?_test_as` 後門，harness 限定）與個股快照為 stub。
每案保留：HTTP 狀態＋最終 URL（`*.status.txt`）、截圖（`*.png`，已目檢）、
console（`*.console.log`）。網路以狀態檔＋server 存取紀錄為證（`harness` 側無額外 netlog）。

| 案例 | 證據 | 結果 |
|---|---|---|
| 未登入看大咖 | perspectives_desktop/mobile 200，無私人外洩，追蹤導向登入 | 通過 |
| A／B 兩位使用者 | beta 200 vs nonbeta 403 vs 匿名；偽造欄位單元 400 | 通過（真實 LINE OAuth 雙帳號端到端待試用階段） |
| 四種資料類型 | 畫面中文標籤齊全 | 通過 |
| Pelosi／INTC 問句 | 交談單元：未證實＋雙區答案 | 通過 |
| 多列與修訂 | 同文件兩列＋修訂時間語意（單元） | 通過 |
| 截止日／窗口／換頁 | round-trip（單元） | 通過 |
| 不同偏好 | 預設綜合；只改排列（畫面＋單元） | 通過 |
| 儲存／刷新／另一裝置 | 冪等＋409（單元）；CTA 目檢存在 | 通過 |
| ASK 與個股卡 | stock_intc_beta：plan_id／action／價位／日期與模板一致 | 通過 |
| 過期／缺棒／停牌 | insufficient 語意（單元）；歷史可讀 | 通過 |
| 提醒去重 | 同快照零新增；未 opt-in 零發送（單元＋dry-run） | 通過 |
| 手機操作 | 390px 目檢：單欄、四欄位可見、無整頁橫向溢位、按鈕可點 | 通過 |
| 回饋與匯出 | 表單＋匯出連結目檢；寫入隔離單元 | 通過 |
| 舊路徑回歸 | 單元涵蓋；harness 靜態 200 | 通過 |
| 未知 subject 404 | subject_404：HTTP 404＋截圖 | 通過 |

殘留（故仍非 BETA_READY）：真實 LINE OAuth 雙帳號端到端、已 opt-in 真實推播
送達（無同意帳號，fake push 而已）、候選版 read-back、2 週試用觀察。

| 案例 | 代驗證方式 | 結果 |
|---|---|---|
| 未登入看大咖 | GET /perspectives 200＋追蹤導向登入文案 | 通過（無私人外洩） |
| A／B 兩使用者隔離＋偽造 ID | test_line_login 雙 session＋偽造欄位 400 | 通過 |
| 四種資料類型中文標籤 | 模板含官方交易揭露／當事人自述／機構季底／公開觀點 | 通過 |
| Pelosi／INTC 問句 | 交談測試：未核對不承認前提；配偶／期權不偷換 | 通過 |
| 多列與修訂 | 同文件兩列皆顯示；重複轉貼單筆；修訂可追溯 | 通過 |
| 截止日／窗口／換頁 | round-trip＋未來／未審隱藏 | 通過 |
| 不同偏好 | 偏好只改排列，計畫與狀態不變 | 通過 |
| 儲存／刷新／另一裝置 | 冪等 request_id＋409 stale_plan 重確認 | 通過 |
| ASK 與個股卡一致 | 同一 builder；LLM 分歧回模板 | 通過 |
| 過期／缺棒／停牌 | insufficient＋歷史可讀；無 0／假即時 | 通過 |
| 提醒去重 | 同快照零新增；未 opt-in 零發送 | 通過 |
| 手機操作 | 390px 真實 Chrome 目檢：單欄、四欄位可見、無整頁橫向溢位 | 通過 |
| 回饋與匯出 | 提交可讀回；匯出僅本人三類；無憑證 | 通過 |
| 舊路徑回歸 | 單元涵蓋；harness 靜態 200 | 通過 |

殘留證據缺口（故仍非 BETA_READY）：雙真實 LINE 帳號 OAuth 端到端；
已 opt-in 真實推播 read-back（無同意帳號，故 **LINE 實際送達：未驗證**，僅 fake push）；
候選版 read-back；2 週試用觀察。

## 第 1 節使用流程對照（§13.3 最低條件）

- [x] LINE 登入＋偏好（數據／大咖／綜合，預設綜合）— API＋真實瀏覽器殼驗證（OAuth 本人換真實帳號待試用）
- [x] 大咖動態／個股挑標的 — 完成（含 Pelosi 未證實、期權非股票）
- [x] 五種建議（等待／可評估／暫不追價／檢查退出／暫停）— 規則＋中文完成
- [x] 原因／反對／觸發失效／資料日＋儲存 — 完成
- [x] 條件變動站內提醒；LINE 僅自願 opt-in — 站內完成；真實推播未驗證
- [x] 原始計畫與變化＋回饋（有幫助／沒幫助／資料有問題＋一句）— 完成
- [x] 真實種子操作資料：Serenity TW 3006 自述持倉 1 筆（X 連結可 read-back，瀏覽器目檢呈現）；
  Pelosi–INTC 未證實（pending，不偽造）；Berkshire（source_only，無快照）— 最低「一組真實」成立，
  機構／政治人物即時 feed 未完成，頁面已明示
- [x] 2 帳號隔離以測試帳號證明（API＋不同渲染；真實 OAuth 雙帳號待試用）；5–10 同學招募為目標非保證；2 週觀察未開始（試用開始後才跑）
- 狀態：**LOCAL_VERIFIED**；不得使用 `BETA_READY`／`PRODUCTION_VERIFIED`（候選版、真實推播、試用觀察三者全缺）。

## 發布清單（不公開完整 ID）

- HEAD：`ffda040`（已 push `origin/codex/tw-premarket-verified-overlay`；基線 `b56e9f1` 見任務 0 證據）
- 候選版：`line-stock-bot-00283-zif`（tag `trading-ffda040`，0% 流量；正式 `00281-qeq` 100% 未動；
  read-back 見 `CANDIDATE-READBACK.md`，含 health／TW＋US 讀取／401＋no-store／GCS generation）
- catalog_version：`public-opinions-v2-c2-2026-09-18-x-review`
- catalog SHA-256（前 16）：`78828183410b33cf`（完整見候選版本 read-back）
- `ABSORB_TRADING_BETA_USERS`：預設空（關閉）；候選／試用配置須經授權後另行設定，不寫入 repo
- LINE 通知 opt-in：僅本人自願開啟；本次無同意測試帳號，真實推播未驗證（fake push）
- 排程：未更動現有時段；已盤點（`scheduler-inventory.txt`）：`line-stock-alert-check`
  平日 14:30 Asia/Taipei → `POST /tasks/check-alerts`，**僅涵蓋台股收盤，未涵蓋美股快照
  完成（台北約 05:30 後）**。美股時段差異列入 RELEASE-CHECKLIST 授權 C，不直接補建；
  程式端 `trade_plan_context` 預設 `enabled: False`。
- 回滾：首選清空 beta 名單；禁止直接回滾到不認識 assistant 欄位的舊版後繼續寫 state

## 停止條件（本次無觸發，但保留）

未授權存取／CSRF／跨帳號／秘密外洩、伪造來源、期權當股票、前視、未知 rights、
無法保存／去重、通知重送不受控、基線不符、缺發布授權 — 均按 §14.3 停止相關操作。
