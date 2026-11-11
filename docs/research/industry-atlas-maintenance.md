# 產業關係名錄維護

入口為 `/industries/relationships`；舊的 `/industries/ai-server/relationships` 保留。搜尋支援已收錄公司的中文名、英文名、別名與股票代號，可跨產業找到公司，再進入該產業查看關係。搜尋沒有結果不代表公司沒有產業關係。

## 第一版範圍

8 個產業、21 家不重複公司、17 筆關係紀錄（16 筆 active、1 筆 historical）。公開關係圖另外檢查核對日期、來源狀態與有效期間，因此筆數會隨複核期限改變。AI 伺服器沿用原有名錄與核對日期；新增的 7 個產業各先提供 2 家公司與 1 筆官方來源支持的關係，不宣稱完整覆蓋。

## 新增公司或關係

1. 編輯 `data/research/<catalog_id>.json` 對應產業。新產業需先加入服務中的 `CATALOGS` 固定清單，網址參數不能任意指定檔案。
2. 公司放入適當的 `stages[].nodes`；填寫 `symbol`、`name`、明確的 `market`（TW／US／KR）及可選 `aliases`。身份由市場與代號共同決定；同一家公司出現在多個產業，搜尋會合併呈現。
3. 沒有關係證據時只新增公司位置，不畫線。各產業可以是尚未有來源或關係的公司名錄。
4. 原始證據加入 `sources`，記錄官方網址、標題、發布者、發布日、可定位段落、實際閱讀核對日與來源狀態。新官方網站須加入 `ALLOWED_SOURCE_HOSTS` 精確白名單，不能放寬為任意網址。
5. 在 `relationships` 加入獨立 ID、兩端公司、類型、產品／服務範圍、說明、來源引用與狀態。兩端公司資料必須與節點完全一致。`supply` 方向為供應者至客戶；合作、競爭與同環節不使用供應箭頭。同屬一個產業不能當作供應證據。
6. 未核實標為 `pending_review`；不會出現在公開頁面或搜尋 API 的關係中。僅能確認歷史事件時使用 `historical`，並保留證據。`active` 表示可依目前核對的來源呈現，不代表計畫已落實或合作永久持續。

來源引用使用對應 source 的 `id`、`title`、`url`。不要把 demo 的示意連線當成真實關係匯入。

## 低頻複核

採人工季度複核，加上重大公告時更新，不新增每日排程。現行關係要求最近核對日在當日以前且未超過 90 天、來源可用、發布與來源核對日非未來，以及關係已生效且未到期。逾期或來源失效會移至「歷史與待複核紀錄」，不進入關係圖、個股現行關係或 ASKsorb 現行關係摘要。

只有實際重新閱讀原文才能更新 `checked_at`／`reviewed_at`。重新閱讀舊公告不等於證明合作延續，必須在說明保留原始業務和日期範圍；缺乏延續證據時維持歷史狀態。例如 Microsoft／FedEx 的 2022 年公告僅列為歷史紀錄。

每個產業分別驗證。單檔缺漏、錯誤 JSON 或欄位型別不正確時，該產業顯示暫不可用，其他產業仍可搜尋。資料必須修正後才恢復顯示。

## 驗證

使用專案 `.venv` 執行：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_industry_relationships tests.test_industry_atlas tests.test_research_routes tests.test_route_inventory tests.test_absorb_research_integration tests.test_web_product tests.test_observation_views tests.test_absorb_brand -q
node --check static/industry-atlas.js
```

再以瀏覽器確認搜尋、公司聚焦、原始來源、手機排版與市場篩選。市場篩選會保留與選定市場有直接關係的海外對象，讓圖上連線與證據清單一致。停用 JavaScript 時仍可使用 GET 表單與證據清單。

本次僅完成本機實作與驗證，不代表已部署。驗證紀錄在 `artifacts/industry-atlas-20261104/`；正式發布仍須依專案既有部署及公開讀回流程執行。
