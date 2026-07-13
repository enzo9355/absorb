# 本機正式日報鏡像與 SAMPLE 下載設計

## 目標

每次正式台股日報通過資料驗證、PDF 驗證與本地發布流程後，除既有 content-addressed 不可變物件外，再建立一份具有人類可讀檔名的本機鏡像。

網站另提供完全獨立、明確標示為 SAMPLE / TEST DATA 的範例 PDF 下載入口。SAMPLE 不得進入正式報告 index、latest、GCS 發布流程或本機正式封存目錄。

## 正式本機鏡像

- `reporting.cli` 未指定 `--output-dir` 時，輸出目錄由 `--root` 推導為 `<root>\\reports\\<market>`。
- 預設 root 為 `D:\\StockPapiData`，台股預設目錄為 `D:\\StockPapiData\\reports\\TW`；reporting 核心邏輯不得直接寫死該磁碟路徑。
- 正式友善檔名為 `stock-papi-tw-industry-daily-YYYY-MM-DD.pdf`，並建立相同 basename 的 metadata sidecar JSON。
- `publish\\reports\\v1\\objects`、metadata、index 與 latest 仍是正式來源，既有 content-addressed 不可變副本保持不變。
- 友善副本只在來源、PDF、content-addressed PDF／metadata、index 與 latest 全部成功後建立；使用 temporary file、fsync 與 `os.replace()` 原子更新。
- 同日 PDF hash 相同時跳過；hash 不同時更新友善副本，舊版仍保留於 content-addressed objects。
- `--dry-run`、資料或 PDF 驗證失敗及 SAMPLE 資料均不得建立正式鏡像或發布項目。

## SAMPLE PDF 與網站

- SAMPLE 使用固定 synthetic fixture，PDF 必須包含 `SAMPLE / TEST DATA`、`不得正式發布` 與 `不得作為正式投資或模型結果`。
- SAMPLE 不讀取 GCS、正式 index、latest 或 `D:\\StockPapiData` 正式資料，也不寫入正式 metadata 或鏡像目錄。
- 以單一經驗證的固定 PDF 放入 `static/samples/` 隨 Cloud Run 部署；禁止 request 時現場生成。
- `/reports` 將 SAMPLE 卡片與正式報告列表分區顯示；SAMPLE 卡片顯示測試資料與投資限制說明，不能顯示為最新或歷史正式報告。
- `GET /reports/sample/download` 只能讀取 server-side 固定 PDF path，回傳 `application/pdf`、`attachment` 與含 `SAMPLE` 的檔名。

## 驗證與不變事項

- CLI／publisher 測試驗證預設鏡像目錄、PDF hash、sidecar 一致性、同內容跳過、不同內容更新與失敗不覆蓋既有鏡像。
- Flask test client 驗證 SAMPLE 下載 HTTP 200、MIME、attachment、檔名、PDF 標籤、無 GCS 呼叫與不在正式 index。
- 保留 Cloud Run cold-start 測試；`import app` 不得載入 matplotlib、reportlab 或 pypdf。
- 不修改正式 GCS 報表讀取與驗證流程，不降低 manifest、SHA-256、size、uncompressed_size 或 PDF 驗證標準。
