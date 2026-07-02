# US Stock Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support direct US stock ticker analysis in LINE and Web without adding dependencies or full-market US scanning.

**Architecture:** Recognize standard alphabetic tickers, route them to the existing yfinance history loader, add S&P 500/SPY market context, and preserve neutral Taiwan-only chip features. Reuse the existing analysis, Flex, watchlist, alert, and Web detail flows.

**Tech Stack:** Python 3.10, Flask, yfinance, unittest

---

### Task 1: Ticker recognition and US data path

**Files:**
- Modify: `tests/test_prediction_pipeline.py`
- Modify: `app.py`

- [ ] Add failing tests for alphabetic ticker recognition and yfinance-only US data loading.
- [ ] Run focused tests and confirm the current Taiwan-only behavior fails.
- [ ] Add `is_us_ticker()` and branch `get_data()` to use the ticker, `^GSPC`, and `SPY` without FinMind calls.
- [ ] Run focused tests and confirm they pass.

### Task 2: LINE and Web integration

**Files:**
- Modify: `tests/test_line_flow.py`
- Modify: `tests/test_web_product.py`
- Modify: `app.py`

- [ ] Add failing tests for AAPL LINE lookup, postback resolution, and `/stock/AAPL`.
- [ ] Run focused tests and confirm current validation rejects AAPL.
- [ ] Reuse `search_stock_code()` for LINE, calculators, postbacks, and the Web route.
- [ ] Run focused tests and confirm they pass.

### Task 3: Documentation and release

**Files:**
- Modify: `README.md`

- [ ] Document supported US ticker queries and current limitations.
- [ ] Run all tests, live AAPL analysis, and `git diff --check`.
- [ ] Commit, push, deploy from a clean Git archive, and verify `/stock/AAPL` on Cloud Run.
