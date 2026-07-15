# ABSORB 品牌與自然語言研究助理設計

## 決策

- 使用者品牌一次切換為 ABSORB；歷史 immutable 物件、schema identifier、外部 secret 名稱與 compatibility import 不機械改寫。
- `absorb` 成為新入口與對話層的 canonical package；既有 `stock_papi` 內部實作在本階段保留，以降低跨 70+ 模組搬移造成的循環 import、pickle 與 cold-start 風險。
- 固定 LINE 指令維持原 handler 與順序。只有既有規則全部不匹配時才進入共用 conversational orchestrator。
- LINE 與 Web 共用 schema、context、tool registry、policy、prompt 與 orchestrator；renderer 只處理篇幅與呈現。
- LLM 不直接接觸 repository。tool adapter 只能呼叫既有 `search_stock_code`、`analyze`、report reader 與 LINE state application functions。

## 信任邊界

1. transport 產生可信 principal：LINE user id 來自 webhook event；Web principal 來自 HttpOnly 隨機 cookie，不接受 request body 的 user id。
2. context store 以 principal key 隔離、TTL 到期刪除，只保存 entity 與 pending action，不保存完整對話。
3. command bridge 先完成輸入大小、安全與固定命令判斷。
4. orchestrator 只允許 registry 中的 canonical tool；參數先經 market、symbol、數量與字串長度驗證。
5. tool output 轉為有限 JSON，保留 `None`、日期、stale 與 limitations，不傳 raw document、manifest、HTML、PDF 或路徑。
6. LLM 只負責理解與解釋，不能改寫 recommendation action。工具失敗或核心資料缺失時不給進場／追價結論。

## 固定指令契約

既有 pending alert、`Papi ...` compatibility prefix、試算、大盤／今日盤勢、預測／熱門產業、我的關注、強勢訊號、提醒管理、完整分析、投資試算、功能選單、分類分頁、產業列表、選產業、免責聲明、新手教學、股票代碼／名稱查詢維持 deterministic。舊 prefix 不再顯示舊人格，但仍可進入 ABSORB 對話服務。

## 對話資料流

`question -> entity resolution -> allowlisted tools -> normalized evidence -> bounded LLM synthesis -> action-preserving validation -> renderer -> context update`

追價問題至少嘗試取得現有分析中的 recommendation、五日機率、近期／技術／量能／波動／產業／市場／籌碼、支持與反對證據、失效條件、資料日、資料品質、model version 與 backtest date。沒有現成欄位即保留 `None` 並列入 limitations；不新增追價分數或未回測門檻。

## 寫入操作

自然語言寫入先建立綁定 principal、canonical args、nonce、expiry、status 與 idempotency key 的 proposal。未登入 Web 只回覆登入需求；watchlist 新增、移除、清空，以及明確的價格／機率／趨勢提醒建立與關閉全部提醒，均需確認後才呼叫既有 application function。模糊的單筆提醒更新／刪除保持 fail closed，使用原本「提醒管理」流程。

## 遷移邊界

- Environment：新增集中式 ABSORB config；只有實際存在的品牌前綴變數提供舊名 fallback，衝突 fail closed。
- Data root：copy-verify-switch，不 move、不 delete source，拒絕 reparse point。
- Scheduler：建立 disabled 的 `ABSORB-*` shadow tasks；驗證後才 enable 新／disable 舊，永不自動刪舊。
- External：GitHub repo rename、Cloud Run service、GCS、Firestore、LINE provider 與 production secrets 均需人工核准，不在此變更中執行。

## Rollback

應用 rollback 只需回退 code commit；compatibility package、舊資料根、舊 tasks、舊 env fallback 與 reader 相容仍保留。若新資料或 task shadow 驗證失敗，保持舊設定啟用，不覆蓋 latest，也不刪除 candidate、checkpoint 或 immutable object。
