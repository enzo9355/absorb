# Local Quant Builder Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每日 05:30–09:30 期間，將現有台股 730 天資料、特徵、五日預測與回測逐股寫入 `D:\StockPapiData`，支援 checkpoint、原子 gzip JSON 與每晚最多 200 檔的安全初始回補。

**Architecture:** `local_quant.py` 延用現有 `app.get_data()`、`calc_all()` 與 `run_ai_engine()`，但只在本地 runner 通過時間、D 槽、空間與 lock 後才延遲載入 app。逐股完成即原子寫入 D 槽並更新 checkpoint，不把全市場同時載入記憶體。PowerShell wrapper 將 Python cache、TEMP、yfinance cache 與未來模型 cache 全部指向 D 槽。

**Tech Stack:** Python stdlib gzip/json、既有 pandas/LightGBM/yfinance/FinMind、PowerShell Task Scheduler、unittest。

---

### Task 1: 逐股原子 artifact

**Files:**
- Modify: `local_quant.py`
- Create: `tests/test_local_quant_batch.py`

- [ ] 先寫失敗測試，驗證 symbol allowlist、gzip JSON schema、日期與非有限值拒絕、暫存檔原子取代。
- [ ] 執行 `python -m unittest tests.test_local_quant_batch -v`，確認缺少 `write_stock_artifact`。
- [ ] 實作 `write_stock_artifact(root, market, symbol, payload)`，只允許 `TW` 與標準代碼，輸出 `artifacts/stocks/TW/<symbol>.json.gz`。

```python
def write_stock_artifact(root, market, symbol, payload):
    if market != "TW" or not re.fullmatch(r"[0-9]{4,6}", symbol):
        raise ValueError("invalid Taiwan symbol")
    target = Path(root) / "artifacts" / "stocks" / market / f"{symbol}.json.gz"
    document = {"schema_version": 1, "market": market, "symbol": symbol, **payload}
    _write_gzip_json_atomic(target, document)
    return target
```
- [ ] gzip 寫入同目錄 `.tmp`，完成 `flush/fsync` 後 `os.replace`；JSON 使用固定 `schema_version=1`，不使用 pickle。
- [ ] 重跑測試並提交 `feat: add local stock artifacts`。

### Task 2: 有界批次與 checkpoint

**Files:**
- Modify: `local_quant.py`
- Modify: `tests/test_local_quant_batch.py`

- [ ] 先寫失敗測試，使用兩個假股票驗證逐股處理、失敗隔離、checkpoint next_index、到 09:20 停止領取新股票及 resume。
- [ ] 實作 `run_market_batch(root, market, symbols, analyze_symbol, limit, now_fn, delay)`；一次只持有一檔資料。

```python
def run_market_batch(root, market, symbols, analyze_symbol, limit=200,
                     now_fn=lambda: datetime.datetime.now(TAIPEI), delay=0.5):
    checkpoint = load_checkpoint(root)
    start = checkpoint.get("next_index", 0)
    for index in range(start, min(len(symbols), start + limit)):
        if window_phase(now_fn()) != "run":
            break
        symbol = symbols[index]
        try:
            write_stock_artifact(root, market, symbol, analyze_symbol(symbol))
        finally:
            save_checkpoint(root, {"market": market, "next_index": index + 1})
```
- [ ] 每檔成功後寫 artifact；失敗只記錄 symbol 與錯誤類型，不記外部回應或憑證。
- [ ] 每檔完成即原子保存 checkpoint；`limit=200` 是每晚最大新工作量，不是 universe 上限。
- [ ] 測試通過後提交 `feat: add resumable local market batch`。

### Task 3: 延用現有模型的台股分析器

**Files:**
- Modify: `local_quant.py`
- Modify: `tests/test_local_quant_batch.py`

- [ ] 先寫失敗測試，mock 現有 pipeline，驗證輸出包含 rows、latest、backtest、model_version 與 enriched daily records。
- [ ] 實作延遲載入：先設定 dummy LINE import-only 值與 D 槽 cache，再 `import app`；不得載入 Gemini 或 Firestore 資料。

```python
def load_stock_pipeline(root):
    os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "local-only")
    os.environ.setdefault("LINE_CHANNEL_SECRET", "local-only")
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GCP_PROJECT_ID", None)
    import app as stock_app
    import yfinance as yf
    yf.set_tz_cache_location(str(Path(root) / "cache" / "yfinance"))
    return stock_app
```
- [ ] 對每檔執行 `get_data(code, 730)`、`calc_all(df)`、`run_ai_engine(df)`；資料不足明確失敗並由批次隔離。
- [ ] DataFrame 使用 `to_json(..., orient="records", date_format="iso")` 轉成安全 JSON 值；不序列化模型物件。
- [ ] 測試通過後提交 `feat: build local Taiwan stock snapshots`。

### Task 4: CLI 與 D 槽 wrapper

**Files:**
- Modify: `local_quant.py`
- Create: `scripts/run_local_quant_task.ps1`
- Modify: `scripts/install_local_quant_task.ps1`
- Modify: `tests/test_local_quant.py`
- Modify: `tests/test_local_quant_task.py`

- [ ] 先寫失敗測試，驗證 `--run --market TW --limit 200 --delay 0.5` 只在 phase=run 執行，其他時段不啟動 app。
- [ ] wrapper 設定 `TEMP`、`TMP`、`XDG_CACHE_HOME`、`HF_HOME`、`PYTHONPYCACHEPREFIX`、yfinance cache 到 D 槽，並設定 repo `.deps` 為 `PYTHONPATH`。

```powershell
$env:TEMP = 'D:\StockPapiData\cache\tmp'
$env:TMP = $env:TEMP
$env:XDG_CACHE_HOME = 'D:\StockPapiData\cache'
$env:HF_HOME = 'D:\StockPapiData\cache\huggingface'
$env:PYTHONPYCACHEPREFIX = 'D:\StockPapiData\cache\pycache'
$env:PYTHONPATH = Join-Path $RepoRoot '.deps'
& $PythonExe $Runner --root 'D:\StockPapiData' --run --market TW --limit 200 --delay 0.5
```
- [ ] 安裝器將排程 action 改為受限 PowerShell wrapper，不把任何 API key 放入 arguments 或 Task XML。
- [ ] 重新安裝排程並驗證 action、05:30、PT4H、IgnoreNew、Priority 7、StartWhenAvailable=false。
- [ ] 測試通過後提交 `feat: schedule Taiwan local backfill`。

### Task 5: 安全驗證與啟用

**Files:**
- Modify: `README.md`

- [ ] 執行所有 unit tests、Python compile、PowerShell parse、`git diff --check`。

```powershell
& $python -m unittest discover -s tests -v
& $python -m py_compile local_quant.py
git diff --check
```
- [ ] ShellWard 與人工檢查新檔；環境變數名稱誤判需人工核對，不得包含真實值。
- [ ] 時段外手動觸發排程，確認回傳 closed、無 lock、無新 artifact。
- [ ] 保留排程於 05:30 自動執行；不使用繞過時間窗的旗標做真實下載。
- [ ] 推送 main；此階段不部署 Cloud Run，因線上尚未讀取本地 artifact。
