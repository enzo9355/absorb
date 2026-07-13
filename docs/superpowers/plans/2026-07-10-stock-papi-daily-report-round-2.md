# Stock Papi Daily Report Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安全遷移 legacy TW manifest，完成第二輪日報分析與 PDF 修正，並以正式 2026-07-08 快照產生經驗證的真實報告。

**Architecture:** 保留嚴格 loader，新增一次性 migration CLI；分析資料仍由 `build_daily_report` 集中產生，PDF 只負責呈現。所有正式資料寫入維持 content-addressed immutable object 與 latest 最後原子替換。

**Tech Stack:** Python 3.10+、stdlib、ReportLab、Matplotlib、pypdf、unittest、PowerShell。

## Global Constraints

- 不降低 SHA-256、壓縮 size、解壓上限、JSON schema、market、symbol、as_of 與 model_version 驗證。
- `ROTATION_NEUTRAL_THRESHOLD_PCT = 0.20`，資料內部使用比例值 `0.002`。
- 模型偏多門檻 `>= 60%`；模型偏弱門檻 `<= 45%`。
- 五日非重疊回測單次完整持有扣除 `0.585%`。
- 舊 manifest 不可修改；migration 任一失敗不可更新 latest。
- SAMPLE 不可發布；Cloud Run import 不可載入 matplotlib、reportlab、pypdf。

---

### Task 1: Legacy manifest migration

**Files:**
- Create: `reporting/migrate_quant_manifest.py`
- Create: `tests/test_quant_manifest_migration.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `migrate_manifest(root: Path, market: str, latest: Path, dry_run: bool) -> MigrationResult`
- Produces: CLI `python -m reporting.migrate_quant_manifest --root ... --market TW --latest quant\v1\latest-TW.json [--dry-run]`

- [ ] Write tests that build a legacy manifest without `uncompressed_size`, verify calculated UTF-8 byte size, immutable old bytes, new manifest, dry-run statistics, size-limit failure and unchanged latest on failure.
- [ ] Run `python -m unittest tests.test_quant_manifest_migration -v`; confirm failures are caused by the missing module/API.
- [ ] Implement two-pass compressed hash/size validation plus bounded streaming gzip decode, schema validation, canonical manifest bytes, immutable write and latest-last `os.replace`.
- [ ] Re-run the migration tests and `tests.test_local_quant_publish tests.test_daily_report_source` until green.

### Task 2: Daily comparison, thresholds and market/model quality

**Files:**
- Modify: `reporting/config.py`
- Modify: `reporting/schemas.py`
- Modify: `reporting/industry_analytics.py`
- Modify: `reporting/summaries.py`
- Modify: `reporting/cli.py`
- Modify: `tests/test_industry_report_analytics.py`

**Interfaces:**
- Consumes: `build_daily_report(source, industry_map, config=None, previous_source=None)`
- Produces: mutually exclusive `bullish_industries` and `weak_industries`, optional prior-day changes, expanded `MarketSnapshot`, `ModelQualitySnapshot`, industry sample quality and signal profile.

- [ ] Write failing tests for 60/45 absolute thresholds, no forced weak list, no-prior text, rank/probability/breadth/rotation changes, neutral rotation band and pooled OOS metrics.
- [ ] Run the analytics tests and confirm expected assertion failures.
- [ ] Add the minimal schema/config fields and calculations; keep unavailable previous values as `None`.
- [ ] Re-run analytics, source and CLI tests until green.

### Task 3: Backtest evidence and actual date axes

**Files:**
- Modify: `reporting/schemas.py`
- Modify: `reporting/industry_backtest.py`
- Modify: `reporting/charts.py`
- Modify: `tests/test_industry_report_backtest.py`

**Interfaces:**
- Produces: `rebalance_periods`, `entry_periods`, `winning_periods`, `losing_periods`, `cash_periods`, `sample_quality`, `all_cash`.

- [ ] Write failing tests separating rebalance and entry periods, all-cash metrics, sample-quality bands and win-rate denominator.
- [ ] Run the backtest tests and confirm expected failures.
- [ ] Implement counts from the existing `positions` and period-return arrays; keep all-cash strategy metrics `None`.
- [ ] Change chart x values from integer indexes to `rebalance_dates`, add date formatting and metadata text.
- [ ] Re-run backtest and chart/PDF tests until green.

### Task 4: Watchlist and risk wording

**Files:**
- Modify: `reporting/industry_analytics.py`
- Modify: `reporting/pdf_generator.py`
- Modify: `tests/test_industry_report_analytics.py`
- Modify: `tests/test_daily_report_pdf.py`

**Interfaces:**
- Produces: MA20 status values `站上 MA20` / `跌破 MA20` / `接近 MA20`, previous probability, probability change, high-score entry/exit and explicit risk wording.

- [ ] Write failing tests for names, MA20 states, default risk copy, foreign-flow unit label and formal-report rejection of `測試股票`.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement only source-backed fields and reject formal placeholder names before PDF generation/publish.
- [ ] Re-run analytics, PDF and publish tests until green.

### Task 5: Flowing PDF and disclosure

**Files:**
- Modify: `reporting/charts.py`
- Modify: `reporting/pdf_generator.py`
- Modify: `reporting/publisher.py`
- Modify: `reporting/config.py`
- Modify: `tests/test_daily_report_pdf.py`
- Modify: `tests/test_daily_report_publish.py`
- Modify: `tests/test_cold_start.py`

**Interfaces:**
- Consumes: expanded `DailyIndustryReport`.
- Produces: extractable sections `市場與資料品質`, `產業五日上漲機率排名`, `產業輪動`, `整體模型品質`, `產業策略回測`, `量化觀察名單`, `方法論、限制與免責聲明`.

- [ ] Write failing PDF text tests for ranking note, rotation definitions, neutral band, cost basis, sample warnings, methodology identifiers and no fixed empty pages.
- [ ] Run PDF/cold-start tests and confirm expected failures without importing report libraries in `app`.
- [ ] Replace fixed page breaks with flowing sections, add KPI cards/progress bars and two small market charts, simplify main ranking table and append the full table.
- [ ] Add quadrant backgrounds, neutral bands, bubble legend and label offsets; expose all chart meanings as extractable paragraphs.
- [ ] Add report/generator schema versions and Git SHA to metadata without local paths.
- [ ] Re-run PDF, publish, web and cold-start tests until green.

### Task 6: Real-data migration and report verification

**Files:**
- Output directory: `D:\StockPapiData\publish\quant\v1\manifests\`（實際檔名由 `TW-{UTC run id}-{manifest SHA-256 前 12 碼}.json` 產生）
- Output: `D:\StockPapiData\publish\quant\v1\latest-TW.json`
- Output: `output/pdf/stock-papi-tw-industry-daily-REAL-2026-07-08.pdf`
- Output: `tmp/pdfs/real-2026-07-08-*.png`

- [ ] Run migration with `--dry-run`; require 2,074 successes, zero failures and record maximum compressed/uncompressed sizes.
- [ ] Run migration without dry-run; verify old manifest bytes are unchanged and new latest resolves to the new manifest hash.
- [ ] Run the regular loader and report generator against the migrated source with available Noto TC fonts.
- [ ] Use pypdf to verify page count and required text, then render every page with Poppler.
- [ ] Inspect every PNG for clipping, overlap, blank pages, broken glyphs and unreadable tables; iterate if any defect remains.
- [ ] Run `python -m unittest discover -s tests -v`, `python -m py_compile ...`, relevant PowerShell/Node syntax checks and `git diff --check`.
- [ ] Run `agy` on the isolated diff input; if authentication blocks it, report that fact without claiming a second review passed.
