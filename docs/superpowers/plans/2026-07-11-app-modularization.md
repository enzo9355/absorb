# Stock-Papi `app.py` Modularization Implementation Plan

> 本次依可回滾 phase 執行；未使用任何 `superpowers` 技能。

**Goal:** 將 `app.py` 漸進式拆成可獨立測試的模組，並維持所有既有公開行為與 cold-start 特性。

**Architecture:** 先抽出無副作用邊界並保留 `app.py` compatibility exports；待 caller 與 tests 已改為顯式依賴後，再建立 `AppRuntime`、route registration 與 `create_app()`。route endpoint 保留原名稱，重型分析維持 lazy。

**Tech Stack:** Python 3.12 runtime（程式碼維持 Python 3.10 相容）、Flask、LINE SDK、unittest、stdlib、Node syntax check。

> 下列 checkbox 保留原始執行計畫與當時先後順序；最終落地狀態以文件末尾的 Completion record、Git commits 與驗證輸出為準。

## Global Constraints

- 不改 route URL、endpoint name、methods、HTTP status、JSON／template context、LINE 文案／Flex、cache semantics、GCS path／schema、模型數值或 publication 行為。
- root `app.py` 暫以 module identity facade 保留既有 `patch.object(stock_app, ...)` 語意；新 production module 禁止 import root `app.py`。
- `import app` 不得載入 pandas、numpy、sklearn、lightgbm、matplotlib、reportlab、pypdf、google.generativeai。
- 不建立 Blueprint namespace、不導入 DI framework、不改 `local_quant.py` 核心。
- 每個 phase 都要跑 focused test、目前 345-test suite、`py_compile`、`node --check static/app.js`、cold import、`git diff --check`。

---

### Task 1: Freeze public route and compatibility contracts

**Files:**
- Create: `tests/test_route_inventory.py`
- Create: `tests/test_app_compatibility.py`
- Modify: `docs/superpowers/specs/2026-07-11-app-modularization-design.md`

**Interfaces:**
- Produces: `route_inventory(app) -> set[tuple[str, str, frozenset[str]]]`.
- Produces: explicit list of root exports still patched by tests.

- [x] Write a route-inventory test that records every non-static rule with rule, endpoint and method set.
- [ ] Run `python -m unittest tests.test_route_inventory -v`; expect failure because the helper / expected snapshot is absent.
- [ ] Add the smallest test-only fixture using `app.app.url_map`; do not move route code.
- [x] Add compatibility tests for `analyze`, `fetch_market_insights`, `dashboard_sector_cards`, `industry_map`, `line_store`, GCS readers and major Flex builders.
- [ ] Run focused tests, then full baseline; commit `test: freeze app route and compatibility contracts`.

### Task 2: Extract pure shared helpers

**Files:**
- Create: `stock_papi/__init__.py`
- Create: `stock_papi/shared/__init__.py`
- Create: `stock_papi/shared/formatting.py`
- Create: `stock_papi/shared/validation.py`
- Create: `stock_papi/shared/exceptions.py`
- Modify: `app.py`
- Test: `tests/test_shared_helpers.py`

**Interfaces:**
- Produces: `safe_float(value, default=0.0) -> float`, `clamp(value, low, high) -> float` and pure ticker／string validation.
- Consumes: no Flask, LINE client, cache or network dependency.

- [ ] Write failing equality tests against current `_safe_float`, `_clamp` and ticker validation edge cases.
- [ ] Run `python -m unittest tests.test_shared_helpers -v`; expect import failure before the module exists.
- [x] Move only exact pure bodies to `stock_papi.shared`; root wrappers retain existing underscored names and output.
- [ ] Re-run shared, prediction and web focused tests; commit `refactor: extract shared formatting and validation`.

### Task 3: Extract LINE Flex presentation

**Files:**
- Create: `stock_papi/integrations/__init__.py`
- Create: `stock_papi/integrations/line/__init__.py`
- Create: `stock_papi/integrations/line/flex.py`
- Modify: `app.py`
- Test: `tests/test_line_flex_compatibility.py`

**Interfaces:**
- Produces existing builder names and identical `dict` payloads; builders accept all data from callers.
- Consumes no Flask `app`, repository, store or HTTP client.

- [ ] Capture a golden dict for summary, navigation, calculator, welcome, tutorial, stock, alert, watchlist and sector builders.
- [ ] Run the new test and confirm it fails before the exports exist.
- [x] Move exact builder bodies; keep root compatibility aliases until all callers migrate.
- [ ] Run `test_line_flow`, `test_web_product`, golden equality and full suite; commit `refactor: extract LINE flex builders`.

### Task 4: Isolate report, GCS and snapshot readers

**Files:**
- Create: `stock_papi/repositories/__init__.py`
- Create: `stock_papi/repositories/gcs.py`
- Create: `stock_papi/repositories/report_store.py`
- Create: `stock_papi/repositories/quant_snapshots.py`
- Create: `stock_papi/repositories/market_insights.py`
- Create: `stock_papi/services/reports.py`
- Modify: `app.py`
- Test: `tests/test_gcs_fail_closed.py`, `tests/test_report_repository.py`

**Interfaces:**
- Produces verified bytes only after prefix, size, SHA-256, gzip, schema, market, symbol, date and freshness checks.
- Consumes explicit token provider; no query parameter is treated as an object path.

- [ ] Write rejection tests for arbitrary prefix, oversized response, bad hash, invalid gzip, missing `uncompressed_size` and bad report index.
- [ ] Verify red tests fail because the repository API does not exist.
- [ ] Move `_gcs_get_allowed_object` first without relaxing its guards; layer report／quant validation above it.
- [ ] Preserve root reader exports and run report／prediction tests; commit `refactor: isolate verified report and snapshot readers`.

### Task 5: Extract dashboard, market and stock services/routes

**Files:**
- Create: `stock_papi/services/dashboard.py`
- Create: `stock_papi/services/market.py`
- Create: `stock_papi/services/stock_analysis.py`
- Create: `stock_papi/web/__init__.py`
- Create: `stock_papi/web/routes/dashboard.py`
- Create: `stock_papi/web/routes/market.py`
- Create: `stock_papi/web/routes/stocks.py`
- Modify: `app.py`
- Test: `tests/test_dashboard_service.py`, `tests/test_stock_routes.py`

**Interfaces:**
- Route factories receive explicit callable dependencies and preserve endpoint names through `add_url_rule`.
- `analyze` remains a root compatibility export until test callers are migrated.

- [ ] Write failing route-factory tests for exact endpoint, status and template context behavior.
- [ ] Move dashboard／market payload assembly before stock orchestration; keep DataFrame work out of route code.
- [ ] Move stock orchestration without changing fallback order, cache key or `None` behavior.
- [ ] Run route inventory, web product, prediction and full suite; commit per independently testable service extraction.

### Task 6: Extract news, sentiment and LINE orchestration

**Files:**
- Create: `stock_papi/integrations/news/__init__.py`
- Create: `stock_papi/integrations/news/provider.py`
- Create: `stock_papi/services/sentiment.py`
- Create: `stock_papi/integrations/line/commands.py`
- Create: `stock_papi/integrations/line/handlers.py`
- Create: `stock_papi/integrations/line/notifications.py`
- Create: `stock_papi/integrations/line/webhook.py`
- Modify: `app.py`
- Test: `tests/test_sentiment_golden.py`, `tests/test_line_commands.py`

**Interfaces:**
- Sentiment consumes and returns plain mappings; provider owns HTTP/schema normalisation; handlers do not import Flask app.
- Command and Flex text／postback data are unchanged.

- [ ] Write golden full-dict sentiment tests and command parsing tests before moving code.
- [ ] Verify tests fail from missing module, not different expected calculation.
- [ ] Move provider and pure sentiment unchanged; then adapt handler registration to explicit runtime dependencies.
- [ ] Run line flow, prediction, sentiment and full suite; commit `refactor: isolate sentiment and LINE handlers`.

### Task 7: Extract quant core last

**Files:**
- Create: `stock_papi/quant/__init__.py`
- Create: `stock_papi/quant/constants.py`
- Create: `stock_papi/quant/data.py`
- Create: `stock_papi/quant/features.py`
- Create: `stock_papi/quant/model.py`
- Create: `stock_papi/quant/backtest.py`
- Create: `stock_papi/quant/projection.py`
- Modify: `app.py`, `local_quant.py`
- Test: `tests/test_quant_regression.py`

**Interfaces:**
- Produces exact `accuracy`, `brier`, `strat_cum`, `bh_cum`, `win_rate`, `trades`, `mdd`, `sharpe`, `top_features`, `AI_P` and projection outputs.
- Maintains lazy imports, seed, feature order, DataFrame index and rounding.

- [ ] Write deterministic fixture regression before moving a single model function.
- [ ] Run it against current implementation and freeze expected values.
- [ ] Move constants, data, features, model, backtest and projection in isolated commits; no formula edits.
- [ ] Run quant regression, local quant tests, full suite and cold import after each move.

### Task 8: Introduce runtime, factory and route registration

**Files:**
- Create: `stock_papi/runtime.py`
- Create: `stock_papi/web/app_factory.py`
- Create: `stock_papi/web/route_registration.py`
- Create: `stock_papi/web/error_handlers.py`
- Modify: `app.py`, `Dockerfile`, `README.md`
- Test: `tests/test_app_factory.py`, `tests/test_route_inventory.py`

**Interfaces:**
- `create_app(config: Mapping[str, Any] | None = None) -> Flask`.
- `app.py` ends with `app = create_app()` plus documented explicit compatibility exports.

- [x] Write two-app isolation, route inventory and root-import compatibility tests.
- [x] Verify config and Flask route state are independent; retain documented process-level caches intentionally.
- [x] Add an independent factory and central route registration.
- [ ] Run final required checks plus `/health`, valid webhook and `/stock/2330` local smoke tests.

### Task 9: Documentation, review and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-11-app-modularization-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-app-modularization.md`

- [x] Update module map, entry point, route registration, test commands, compatibility layer and heavy-import rules.
- [x] Keep `local_quant.py` unchanged and document its future pipeline boundaries separately from this refactor.
- [ ] Run final full verification and `git diff --check`. External review is intentionally omitted because the user explicitly disabled sub-agents and external reviewers for this task.
- [ ] Commit final documentation only after all code phases are independently committed.

## Completion record

- Completed commits cover shared helpers, LINE Flex, report/GCS repositories, news/sentiment, dashboard/market/stock routes and services, stock analysis, quant core, LINE webhook/handlers, independent Flask factory, legacy HTML renderer, logging helpers and central route registration.
- Final composition cleanup also moved remaining LINE presentation/state helpers, Papi research orchestration, news orchestration, market providers, runtime loaders, market-insights payloads and broadcast insight generation out of `application.py`.
- Compatibility is deliberate: root `app.py` aliases `stock_papi.application` so existing `patch.object(stock_app, ...)` tests continue to affect the dynamic dependency callbacks used by routes and handlers.
- Per-app Flask state is isolated. Existing process-level caches remain canonical singletons because changing cache ownership or TTL in the same refactor would alter behavior.
