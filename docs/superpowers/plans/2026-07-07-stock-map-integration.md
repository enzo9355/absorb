# Stock Papi 市場地圖整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以既有資料完成每日焦點、市場熱力圖、個股頁分區導覽與產業同儕，不增加 Cloud Run 的全市場即時計算。

**Architecture:** 在 `app.py` 增加兩個純函式，分別把現有產業卡轉成熱力圖資料、把現有市場分類轉成個股同儕。Jinja 模板與現有 `static/app.js` 只負責呈現與無障礙導覽；資料失敗時回傳空陣列，不影響既有頁面。

**Tech Stack:** Python 3.10、Flask、Jinja2、Vanilla JavaScript、CSS、unittest

---

### Task 1: 熱力圖資料

**Files:**
- Modify: `app.py`
- Test: `tests/test_web_product.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_market_heatmap_orders_strongest_first(self):
    cards = [
        {"category": "弱勢", "average_probability": 42, "candidates": ["1101"]},
        {"category": "強勢", "average_probability": 68, "candidates": ["2330", "2454"]},
    ]
    result = stock_app.build_market_heatmap(cards)
    self.assertEqual([item["category"] for item in result], ["強勢", "弱勢"])
    self.assertEqual(result[0]["tone"], "hot")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_web_product.WebProductTest.test_build_market_heatmap_orders_strongest_first -v`

Expected: FAIL because `build_market_heatmap` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def build_market_heatmap(cards):
    result = []
    for card in cards or []:
        probability = _safe_float(card.get("average_probability"), 50.0)
        result.append({
            "category": str(card.get("category") or "未分類"),
            "probability": round(probability, 1),
            "count": len(card.get("candidates") or []),
            "tone": "hot" if probability >= 60 else "cold" if probability < 45 else "steady",
            "code": str((card.get("candidates") or [""])[0]),
        })
    return sorted(result, key=lambda item: item["probability"], reverse=True)
```

- [ ] **Step 4: Run the focused test**

Expected: PASS.

### Task 2: 產業同儕

**Files:**
- Modify: `app.py`
- Test: `tests/test_web_product.py`

- [ ] **Step 1: Write the failing test**

```python
def test_find_industry_peers_excludes_current_stock(self):
    market_map = {"半導體": ["2330", "2454", "2303"]}
    peers = stock_app.find_industry_peers("2330", market_map, limit=2)
    self.assertEqual(peers, {"category": "半導體", "codes": ["2454", "2303"]})
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL because `find_industry_peers` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def find_industry_peers(code, market_map=None, limit=5):
    code = str(code).upper()
    for category, codes in (market_map or build_market_map()).items():
        normalized = [str(item).upper() for item in codes]
        if code in normalized:
            return {"category": category, "codes": [item for item in normalized if item != code][:limit]}
    return {"category": "", "codes": []}
```

- [ ] **Step 4: Run the focused test**

Expected: PASS.

### Task 3: Web 呈現

**Files:**
- Modify: `app.py`
- Modify: `templates/dashboard.html`
- Modify: `templates/stock_detail.html`
- Modify: `static/app.js`
- Modify: `static/app.css`
- Test: `tests/test_web_product.py`

- [ ] **Step 1: Add failing page assertions**

```python
self.assertIn("市場熱力圖", dashboard_html)
self.assertIn("今日焦點", dashboard_html)
self.assertIn("產業同儕", stock_html)
self.assertIn('aria-label="個股分析導覽"', stock_html)
```

- [ ] **Step 2: Run the Web tests and verify failure**

Run: `python -m unittest tests.test_web_product -v`

- [ ] **Step 3: Connect existing data**

`dashboard_api()` adds `heatmap = build_market_heatmap(sector_cards)`. `stock_page()` passes `peers=find_industry_peers(code)` and peer display names. Templates render semantic links and anchors; CSS uses responsive grid with `minmax(0, 1fr)` and no fixed width.

- [ ] **Step 4: Run Web tests**

Expected: PASS.

### Task 4: 安全、文件與發布

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document Secret Manager and new Web features**

Document the six Secret names, non-secret environment variables, LINE-first state boundary, and the rule that Stock Papi never calls or copies aistockmap.com in production.

- [ ] **Step 2: Run complete verification**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path '.deps').Path
python -m unittest discover -s tests -v
git diff --check
shellward scan --ci .
```

Expected: all tests pass, no diff errors, and no confirmed secret leak.

- [ ] **Step 3: Commit, push and deploy**

Commit only tracked project changes. Preserve `0.26.0`, `deliverables/`, and `scripts/build_competition_doc.py`. Push `main`, deploy Cloud Run, then verify `/health`, `/dashboard`, and `/stock/2330`.
