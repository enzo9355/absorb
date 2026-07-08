# US Universe Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SEC 回傳 403 且本地沒有快取時，使用 Nasdaq Trader 官方清單建立美股 universe。

**Architecture:** 保留 `get_us_symbols()` 與現有快取格式，在同一個 `local_quant.py` 加入兩份 pipe-delimited 清單解析器及受限下載函式。SEC 失敗後才呼叫 Nasdaq 備援，兩者都失敗時仍沿用舊快取或安全停止。

**Tech Stack:** Python 3.10、requests、unittest、Windows PowerShell。

## Global Constraints

- 不新增套件或資料庫。
- 每個來源限制 5 MB 且必須使用 HTTPS 固定網址。
- 只寫入 `D:\StockPapiData\raw\us-universe.json`，維持原子寫入。
- 不在 02:30–09:30 以外執行市場下載或回測。

---

### Task 1: Nasdaq 官方 universe 備援

**Files:**
- Modify: `local_quant.py`
- Test: `tests/test_local_quant_batch.py`

**Interfaces:**
- Consumes: `get_us_symbols(root, fetch_json=None, now=None)` 與既有安全 ticker 驗證。
- Produces: `parse_nasdaq_us_universe(listed_text, other_text) -> list[str]`，以及 SEC 失敗時的 Nasdaq fallback。

- [x] **Step 1: Write failing tests**

加入測試，傳入最小 `nasdaqlisted.txt` 與 `otherlisted.txt` 內容，斷言測試證券、危險 ticker 與 footer 被排除；再讓 `fetch_json` 拋出 403，斷言 `get_us_symbols` 使用 `fetch_nasdaq` 結果並建立相同快取格式。

- [x] **Step 2: Run tests to verify failures**

Run: `python -m unittest tests.test_local_quant_batch.LocalQuantBatchTests.test_nasdaq_us_universe_filters_test_and_unsafe_symbols tests.test_local_quant_batch.LocalQuantBatchTests.test_us_universe_falls_back_to_nasdaq_without_cache -v`

Expected: FAIL，因 `parse_nasdaq_us_universe` 或 `fetch_nasdaq` 介面尚不存在。

- [x] **Step 3: Implement minimal fallback**

新增兩個固定 Nasdaq Trader URL；使用標準函式解析 `|` 分隔欄位，只接受 `Test Issue=N` 與 `validate_market_symbol("US", symbol)` 可接受的代碼。下載函式沿用 requests、15 秒逾時與 5 MB 上限；`get_us_symbols` 僅在 SEC 失敗時呼叫它，成功後寫入既有快取。

- [x] **Step 4: Run focused and full verification**

Run focused tests, then `python -m unittest discover -s tests -v`、Python compile、PowerShell parser、`git diff --check`。

Expected: 兩個回歸測試與完整測試全部 PASS，語法檢查 exit 0。

- [ ] **Step 5: Review, register and publish**

執行 ShellWard 與 agy 唯讀審查；只提交本次檔案並推送。用既有 installer 重註冊兩個工作排程，確認仍為 02:30、05:30 門檻與 09:35 上傳。白天只測試官方清單讀取，不手動執行市場批次。
