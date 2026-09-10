# 交接書：美股 production 收尾（Claude Code → Codex）

- **交接日期**：2026-09-10
- **交接方**：Claude Code（Opus 5，Anthropic 雲端 session，Linux 容器）
- **接手方**：Codex（Terra，主協調者，Windows production runner）
- **分支**：`claude/vigilant-cori-e6ouu9`（已推送；base 為 `origin/main` = `0a2c9c1`）
- **狀態**：4 項 repo 內缺陷已修正並驗證；部署與正式環境操作**未執行**，原因見第 4 節。

---

## 1. 這份交接書解決什麼

接續 PR #69 合併後仍未收斂的美股 production 問題。本輪只處理「可在 repository 內定位、重現、修正並驗證」的缺陷；所有需要 GCP 憑證、`D:\AbsorbData` 或 Windows 排程的動作都留給 Codex。

**Codex 先前回報的 PARTIAL 判定中，有兩項在本輪關閉，一項無法確認，其餘不在本輪範圍。**

---

## 2. 已完成的修正

| # | Commit | 檔案 | 問題 |
| --- | --- | --- | --- |
| 1 | `b5a3a30` | `stock_papi/batch/us_pre_market_cli.py` | 2026-09-09 美股盤前 503 的根因 |
| 2 | `60b0d09` | `stock_papi/batch/us_official_post_close_cli.py` | halt 證據導致整批盤後失敗（**本輪新發現**） |
| 3 | `a0e1a55` | `scripts/verify_cutover.ps1` | v4 `operational_failure_rate` 算術；BLOCKED 證據不可讀 |
| 4 | `1606753` | `static/app.js` | 手機重載殘留 `Object is disposed` |

### 2.1 `b5a3a30` — 盤前報告必須綁定自己那一節的盤後 base

`run_us_pre_market` 直接採用 `latest-US-post_close.json` 指向的任何 base，未檢查該 base 適用於哪一個 session。

`stock_papi/web/routes/reports.py:286-293` 要求盤前報告與其盤後 base 共用 `source_market_date` 與 `applicable_trading_date`。2026-09-04 的盤後（`next_session` → 2026-09-08）被綁到 2026-09-09 的盤前時，產出的報告**在任何時間點都只能回 503**，且已是 immutable 物件，事後無法修復。

修正後產製端 fail closed：

- 驗證 pointer 指向 content-addressed metadata 物件（`metadata/<sha256>.json`）。
- **重算** metadata hash 並與 pointer 比對。原程式讀的 `base_meta["metadata_sha256"]` 是 metadata 文件本身不存在的欄位，因此永遠 fallback 到 pointer 值，等於未驗證。
- 要求 base 為已驗證的 US observation post-close，且 `applicable_trading_date` 等於目標 session。

契約比照 TW 既有的 `stock_papi/batch/pre_market.py:110` `PreMarketPipeline._base()`，未新增新規則。

### 2.2 `60b0d09` — halt 證據沒有價格歷史時不得阻斷整批

**這是本輪新發現的獨立 production blocker，Codex 先前的紀錄未涵蓋。**

`_fetch_and_classify_symbol` 在 provider 回空 frame 時，只要 Nasdaq halt feed 點名該 symbol，就判為 N（verified non-price）並寫出 `as_of == target_market_date`、`daily: []`、`rows: 0` 的 artifact。

`local_quant.py` 的 manifest producer 要求每個發布 symbol 具備真實價格歷史，且非 regular_price 類別的 `as_of` 必須早於 target session。該 artifact 兩項皆不符，於是整批美股盤後以
`RuntimeError: artifact is invalid for US:<symbol>` 失敗 —— **任一 active universe 內的 halted symbol 都會讓當日全批停擺**。已在容器內以 40 檔 universe 實測重現。

修正：沒有任何 row 就沒有 last regular price date 可綁，因此改判為 M（合法不可得），halt 文件保留在 audit record 的 `official_status_evidence`，並以 `verified_halt_without_price_history` 這個 reason code 與一般 M 區隔。實測由「全批失敗」變為正常發布、coverage 97.5%。

**方向是收緊而非放寬**：該 symbol 從 observation 集合移出，coverage 下降，仍受 >95% gate 約束。有價格歷史的 halted symbol 依舊判為 N，行為不變。

同一 commit 另修 `tests/test_us_adversarial_failures.py` 的連網污染：`test_typed_exceptions_error_classification` 只 stub 了主要 fetcher，兩個會 fallback 到 Nasdaq 的分支實際打到線上端點，並以該端點對假 symbol 的回應決定分類（Codex 先前觀察到的 `TEST` 被判成 `R`）。兩個分支現已 stub，另補一個測試明確涵蓋 fallback 自身的 R / M / OP_FAIL 三種結果。

### 2.3 `a0e1a55` — verifier 的 v4 算術與可讀性

**算術**：`operational_failure_rate` 原本比對整個 observation gap。v4 的 gap 同時包含合法 unavailable 分區，因此任何帶 unavailable 的美股 manifest 都會被判 rate 不合法 —— 16 筆合法 unavailable、0 筆 operational failure 的 manifest 永遠過不了 `latest_us`。

`local_quant.py:752`、`scripts/upload_local_quant.ps1`、`scripts/manual_rollback.ps1` 三處都只以 operational failures 計算，verifier 現與之一致。v3 沒有 unavailable 分區，兩個計數相同，**TW 行為不變**。

本輪同時補上**可執行的 v4 fixture matrix**（原本只有 v2/v3，這正是此缺陷得以出貨的原因）。

**可讀性 —— 請特別注意，這直接影響 Codex 下一步**：

```powershell
} catch { Add-Check $Name $false $_.Exception.GetType().Name }
```

PowerShell 中每個 `throw '訊息'` 的型別都是 `RuntimeException`，因此此腳本約 40 個不同的 gate 條件在 BLOCKED 證據裡全部塌成同一個字串。這就是先前只能看到「另一個 RuntimeException」、必須手動執行驗證函式才能定位條件的原因。

現在 detail 會帶原始訊息（空白收斂、限長 500 字元），三處 catch（`Invoke-Checked` 與兩處 `cloud_run_revision`）統一走新的 `Get-CheckFailureDetail`。

### 2.4 `1606753` — 圖表 resize hook 未釋放

`createPriceChart` 註冊的 `ResizeObserver` 與 window `resize` listener 皆 closure 住 chart，且從未釋放。切換美股指數 tab 時 chart 被 `remove()`，hook 仍在，下一次 viewport 變動即對已 dispose 的 chart 呼叫 `resize()`，圖表庫拋出 `Object is disposed`。

修正：chart handle 帶 `destroy()`，依序 disconnect observer、移除 listener、remove chart；切換器改用 `destroy()`。resize callback 在 destroy 後 no-op，處理切換當下已排入佇列的 resize。

---

## 3. 驗證證據

執行環境：Linux 容器、Python 3.11.15、PowerShell 7.4.6（`pwsh`）、Chromium 1194。

| 項目 | 結果 |
| --- | --- |
| 完整測試 | 執行 **1583** 項（baseline 1574 + 本輪新增 9），新增的 9 項全數通過 |
| Regression | **0**。與同環境 clean baseline 逐一比對失敗清單，集合完全相同 |
| 既有失敗 | 51 項，修改前後為**同一組**，全為 Windows-only：`powershell.exe`、`D:\` 路徑語意、缺 Noto Sans TC 字型 |
| TDD | 每項修正皆先確認 RED、修正後 GREEN |
| `compileall` | PASS（`stock_papi reporting tests`） |
| `node --check static/app.js` | PASS |
| `git diff --check` | PASS |
| PowerShell parse | PASS（`verify_cutover.ps1`） |
| Template smoke | PASS，24 個 template |

**瀏覽器驗收**（`tests/visual_qa_server.py`，390×844 / 1440×1000 / 3840×2160；每個 viewport 切完三個指數 tab ×2，再三次改變 viewport）：

| app.js 版本 | mobile | desktop | 4K |
| --- | --- | --- | --- |
| 修正前（`0a2c9c1`） | 30 筆 disposed | 18 筆 | 18 筆 |
| 修正後（`1606753`） | **0** | **0** | **0** |

三個 viewport 皆無水平溢出，`aria-pressed` 與可見 panel 數皆為 1。

**驗收方法的限制，請據此判斷是否需要在 Windows 重跑**：本容器 egress policy 封鎖 unpkg 與 cdnjs，無法載入真實圖表庫，因此以 stub 模型化「resize 已移除的 chart 會 throw」這一項行為。上表修正前 30/18/18、修正後 0/0/0 的對比證明該 harness 具備鑑別力，但**未使用真實 lightweight-charts 4.2.2 驗證**。若要取得完整證據，請在可連外的 Windows 主機以真實 CDN 重跑同一流程。

---

## 4. 我沒有做、也無法做的事

| 項目 | 原因 |
| --- | --- |
| 部署與 Cloud Run 驗證 | 容器無 GCP 憑證。`line-stock-bot-00212-wap` 仍對應 `88d790b`，未含 `91ea829` 之後任何修正 |
| GCS index 修復、LKG 擷取、generation-guarded 上傳 | 需 bucket 憑證與 `D:\AbsorbData` |
| `D:\` ACL、可用空間、ABSORB 排程狀態 | Windows host |
| 2 個測試 | 需要 `powershell.exe`（Windows PowerShell），非 `pwsh`，在 Linux 上 skip |
| 真實 CDN 的瀏覽器驗收 | egress policy |
| `docs/release_blockers_and_risks.md` 的 B-01～B-05 | 需 CI 與 GCP 環境，本輪未觸碰，仍為 Open |

---

## 5. 建議的接手順序

1. **先比對，不要盲目套用。** Codex 紀錄顯示 Windows runner 上有一份**未提交**的 `us_pre_market_cli.py` 修正。本分支的 `b5a3a30` 是獨立實作，兩者很可能衝突。請先 diff 兩份，決定保留哪一份或如何合併，再動 worktree。

2. **重跑 `verify_cutover.ps1`。** 修正 3 之後，`latest_us` 若仍 BLOCKED，證據會直接指出精確條件，不再是 `RuntimeException`。這是本交接書對「第二個 exception」最直接的貢獻。

3. **評估修正 2 的部署急迫性。** 該缺陷與盤前 503 無關，但風險更高：只要 halt feed 點名一檔沒有歷史的 active symbol，當日整批美股盤後即停擺。建議與其餘修正一併部署。

4. **在 Windows 跑完整套件**，涵蓋本容器 skip 的 2 個 `powershell.exe` 測試與 51 項 Windows-only 案例，取得乾淨的正式驗證數字。

5. **部署閘門維持不變。** 依先前 Claude 主管級審查結論，正式部署仍受真實 TW/US prediction artifacts gate 阻擋；本輪未變更、也不建議繞過任何 gate。

---

## 6. 未解的開放問題

**修正 3 的算術問題已由 fixture 確認並修復，但我無法確認它是否就是 Codex 觀察到的第二個 `RuntimeException`** —— 手上沒有你們的實際 US manifest。

三種可能，依序判斷：

1. 就是 2.3 的 rate 算術（fixture 已證實會誤擋合法 v4 manifest）。
2. 是 2.2 的 halt 路徑，在更上游就讓 manifest 無法產生。
3. 兩者皆非，是該 manifest 特有的資料形狀。

**判斷方式**：套用本分支後重跑 `verify_cutover.ps1`，讀 `latest_us` 的 detail。修正 3 的可讀性部分正是為此而做 —— 訊息會直接指名條件，不需要再手動執行驗證函式。

我另外靜態比對過 verifier 與 uploader 的 v4 契約，未發現其他分歧：US symbol regex 與長度上限（`^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?$`、≤10）和 `us_universe.py:50` 完全一致；非 regular_price 項目 `as_of` 必須早於 target 這條，producer 在 `local_quant.py` 已同樣強制。這是靜態比對，**不等於在你們的實際資料上驗證過**。
