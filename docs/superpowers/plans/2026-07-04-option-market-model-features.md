# Option Market Model Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將具有兩年歷史的 VIX 水準、變化率與期限結構安全加入台股及美股五日 LightGBM 模型。

**Architecture:** 沿用現有 yfinance 抓取與快取，並行取得 VIX、VIX9D、VIX3M。純資料函式先在波動率日期計算，再用 backward as-of merge 對齊股票日期，避免未來資料洩漏。

**Tech Stack:** Python 3.10、pandas、yfinance、LightGBM、unittest。

---

## File map

- Modify: `app.py` — 新特徵常數、抓取、日期對齊與模型接線。
- Modify: `tests/test_prediction_pipeline.py` — 對齊、缺漏、欄位一致與 get_data 回歸測試。
- Modify: `README.md` — 說明已啟用與暫緩的選擇權資料。

### Task 1: 純資料特徵與無洩漏對齊

**Files:**
- Modify: `tests/test_prediction_pipeline.py`
- Modify: `app.py:89-300`

- [ ] **Step 1: Write failing alignment tests**

```python
def test_option_context_uses_only_same_or_earlier_dates(self):
    price = pd.DataFrame({"Date": pd.to_datetime(["2026-01-05", "2026-01-06"]), "Close": [100, 101]})
    vix = pd.DataFrame({"Date": pd.to_datetime(["2026-01-02", "2026-01-07"]), "Close": [20, 99]})
    vix9d = pd.DataFrame({"Date": pd.to_datetime(["2026-01-02"]), "Close": [24]})
    vix3m = pd.DataFrame({"Date": pd.to_datetime(["2026-01-02"]), "Close": [18]})
    result = stock_app.add_option_context_features(price, vix, vix9d, vix3m)
    self.assertEqual(result["OPTION_IV_LEVEL"].tolist(), [0.2, 0.2])
    self.assertAlmostEqual(result["OPTION_IV_TERM_9D_3M"].iloc[0], 24 / 18 - 1)
    self.assertEqual(result["OPTION_DATA_MISSING"].tolist(), [0, 0])

def test_option_context_returns_neutral_values_when_missing(self):
    price = pd.DataFrame({"Date": pd.to_datetime(["2026-01-05"]), "Close": [100]})
    result = stock_app.add_option_context_features(price)
    self.assertEqual(result["OPTION_DATA_MISSING"].iloc[0], 1)
    self.assertTrue((result[stock_app.OPTION_FEATURES[:-1]] == 0).all().all())
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: bundled Python with `-m unittest` and both test names.

Expected: `AttributeError` because `add_option_context_features` and `OPTION_FEATURES` do not exist.

- [ ] **Step 3: Implement minimal option feature calculation**

```python
OPTION_FEATURES = [
    "OPTION_IV_LEVEL", "OPTION_IV_CHG_1", "OPTION_IV_CHG_5",
    "OPTION_IV_TERM_9D_3M", "OPTION_DATA_MISSING",
]

def add_option_context_features(price, vix=None, vix9d=None, vix3m=None):
    result = price.copy()
    for column in OPTION_FEATURES[:-1]:
        result[column] = 0.0
    result["OPTION_DATA_MISSING"] = 1.0
    if result.empty or "Date" not in result or vix is None or vix.empty:
        return result

    option = vix[["Date", "Close"]].copy()
    option["Date"] = pd.to_datetime(option["Date"], errors="coerce")
    option["VIX"] = pd.to_numeric(option["Close"], errors="coerce")
    option = option.drop(columns=["Close"]).dropna().sort_values("Date").drop_duplicates("Date")
    option["OPTION_IV_LEVEL"] = option["VIX"] / 100.0
    option["OPTION_IV_CHG_1"] = option["VIX"].pct_change(fill_method=None)
    option["OPTION_IV_CHG_5"] = option["VIX"].pct_change(5, fill_method=None)

    for frame, name in ((vix9d, "VIX9D"), (vix3m, "VIX3M")):
        if frame is not None and not frame.empty:
            right = frame[["Date", "Close"]].copy()
            right["Date"] = pd.to_datetime(right["Date"], errors="coerce")
            right[name] = pd.to_numeric(right["Close"], errors="coerce")
            option = pd.merge_asof(
                option.sort_values("Date"),
                right.drop(columns=["Close"]).dropna().sort_values("Date"),
                on="Date", direction="backward", tolerance=pd.Timedelta(days=4),
            )
    option["OPTION_IV_TERM_9D_3M"] = option.get("VIX9D", 0) / option.get("VIX3M", np.nan) - 1

    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.drop(columns=OPTION_FEATURES).sort_values("Date")
    result = pd.merge_asof(
        result, option[["Date"] + OPTION_FEATURES[:-1]].sort_values("Date"),
        on="Date", direction="backward", tolerance=pd.Timedelta(days=4),
    )
    result["OPTION_DATA_MISSING"] = result["OPTION_IV_LEVEL"].isna().astype(float)
    result[OPTION_FEATURES[:-1]] = result[OPTION_FEATURES[:-1]].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return result
```

- [ ] **Step 4: Run Task 1 tests**

Expected: both tests pass.

### Task 2: 抓取與模型接線

**Files:**
- Modify: `tests/test_prediction_pipeline.py`
- Modify: `app.py:89-99,329-454,713-875`

- [ ] **Step 1: Write failing model integration tests**

```python
def test_model_features_include_option_features(self):
    for column in stock_app.OPTION_FEATURES:
        self.assertIn(column, stock_app.MODEL_FEATURES)

@patch("app.fetch_yfinance_price_history")
def test_fetch_option_context_history_requests_three_cboe_indexes(self, fetch):
    fetch.return_value = pd.DataFrame()
    stock_app.fetch_option_context_history("2025-01-01", "2026-01-01")
    self.assertEqual({call.args[0] for call in fetch.call_args_list}, {"^VIX", "^VIX9D", "^VIX3M"})
```

- [ ] **Step 2: Run focused tests and verify RED**

Expected: missing `OPTION_FEATURES` in `MODEL_FEATURES` and missing fetch function.

- [ ] **Step 3: Implement fetch and wire all numeric paths**

```python
def fetch_option_context_history(start_date, end_date):
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(fetch_yfinance_price_history, ticker, start_date, end_date)
            for ticker in ("^VIX", "^VIX9D", "^VIX3M")
        ]
        return tuple(future.result() for future in futures)
```

Append `OPTION_FEATURES` to `MODEL_FEATURES` and every existing numeric-cleaning list. In both `get_data()` branches, fetch the tuple once and call:

```python
price = add_option_context_features(price, vix, vix9d, vix3m)
```

Patch `fetch_option_context_history` to return three empty DataFrames in existing get_data unit tests so their yfinance side-effect lists remain unchanged.

- [ ] **Step 4: Run prediction pipeline tests**

Run: bundled Python `-m unittest tests.test_prediction_pipeline -v`.

Expected: all prediction pipeline tests pass.

### Task 3: Documentation, complete verification and publication

**Files:**
- Modify: `README.md`
- Modify: `app.py`
- Modify: `tests/test_prediction_pipeline.py`

- [ ] **Step 1: Document active and deferred features**

State that VIX level, changes and 9D/3M term structure are model inputs for both markets. State that OI, GEX, Vanna, 0DTE and options flow remain excluded until point-in-time history exists.

- [ ] **Step 2: Run full verification**

Run: bundled Python `-m unittest discover -s tests -v`.

Run: `git diff --check`.

Expected: all tests pass and diff check is empty.

- [ ] **Step 3: Live data smoke test**

Fetch two years of `^VIX`, `^VIX9D`, and `^VIX3M`, calculate features, and confirm at least 450 valid rows with no future-date merge.

- [ ] **Step 4: Commit, push and deploy**

```powershell
git add -- app.py tests/test_prediction_pipeline.py README.md docs/superpowers/plans/2026-07-04-option-market-model-features.md
git commit -m "feat: add option market features to prediction model"
git push origin main
```

Deploy a clean `git archive HEAD` to Cloud Run service `line-stock-bot`, then verify latest revision, 100% traffic, health endpoint, Taiwan stock page and US stock page.

