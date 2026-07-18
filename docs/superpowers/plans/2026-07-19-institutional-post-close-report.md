# ABSORB Institutional Post-Close Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 25–35 page institutional-grade post-close research report while keeping the pre-market product as a 1–3 page concise risk update, with HTML, PDF, LINE, and Gemini all derived from one canonical report object.

**Architecture:** Introduce a versioned `ProfessionalPostCloseReport` domain model assembled from existing observation snapshots, industry analytics, stock events, ETF observations, model diagnostics, and optional Gemini commentary. Render the same canonical object into a full web report and a private-GCS-backed PDF; keep pre-market schemas and routes separate. Gate every artifact with point-in-time identity, schema validation, finite-number validation, SHA/size checks, and observation/prediction disclosure policy.

**Tech Stack:** Python 3, Flask, Jinja2, ReportLab, pypdf, Google Cloud Storage, existing ABSORB observation services, Gemini conversation provider, unittest, PowerShell deployment scripts.

## Global Constraints

- Pre-market report remains a concise 1–3 page overnight risk update.
- Post-close report normally spans 25–35 pages and may extend to about 40 pages on major-event days.
- HTML, PDF, LINE summary, and Gemini context derive from the same canonical report schema.
- Observation facts, deterministic risk rules, quantitative model outputs, and Gemini interpretation must be visibly separated.
- Current failed model gates must be disclosed; no unvalidated probability, stable-alpha claim, or performance endorsement is allowed.
- No `backtests/v1/latest-TW.json` may be created unless the model passes every promotion gate.
- GCS remains private; PDF delivery must validate allowlisted object identity, SHA-256, size, and content type.
- No user-specific data, watchlists, LINE IDs, sessions, secrets, or private conversation content may enter public report artifacts.
- Existing immutable v1/v2 reports must not be rewritten.
- Preserve existing Flask, Jinja, ReportLab, route, OAuth, LINE webhook, CSRF, and cache-security behavior.

---

## File Structure

### New files

- `reporting/professional_schema.py` — canonical typed report schema and validation.
- `reporting/professional_builder.py` — deterministic assembly of the canonical report.
- `reporting/professional_sections.py` — section builders for market, industry, stock, ETF, regression, model, validation, and methodology.
- `reporting/professional_pdf.py` — institutional PDF renderer using ReportLab.
- `reporting/professional_html.py` — conversion from canonical report to safe Jinja view model.
- `reporting/professional_repository.py` — local/GCS metadata, PDF, and pointer handling.
- `templates/reports/post_close_professional.html` — full web report.
- `templates/reports/_professional_*.html` — focused section partials.
- `tests/test_professional_report_schema.py`
- `tests/test_professional_report_builder.py`
- `tests/test_professional_report_pdf.py`
- `tests/test_professional_report_routes.py`
- `tests/test_professional_report_repository.py`
- `tests/fixtures/professional_report/` — sanitized production-shaped fixtures.

### Modified files

- `reporting/pdf_generator.py` — keep legacy compatibility; delegate new post-close generation to the professional renderer.
- `reporting/schemas.py` — shared identity/value types only; avoid adding the entire new report into this legacy module.
- `stock_papi/services/report_view.py` — route post-close metadata into professional view model; leave pre-market behavior intact.
- `stock_papi/web/routes/reports.py` — full HTML and PDF routes.
- `templates/reports.html` — remove false empty state and add HTML/PDF actions.
- `templates/report_observation.html` — remain pre-market/legacy summary only; do not use as the professional post-close page.
- `stock_papi/batch/daily_products_cli.py` and relevant daily-product services — build professional post-close candidate.
- `stock_papi/services/report_web.py` or current GCS report loader — load and verify professional metadata/PDF.
- `absorb/conversation/tools.py` — expose canonical report sections to Gemini.
- `absorb/conversation/prompts.py` — disclosure and source-separation rules.
- LINE report rendering module — generate summary from canonical report only.
- `scripts/upload_local_quant.ps1` and `scripts/deploy_observation_production.ps1` — require and verify PDF when publishing post-close reports.
- `docs/dual-daily-report-runbook.md` and report/deployment runbooks.

---

### Task 1: Define the canonical institutional report schema

**Files:**
- Create: `reporting/professional_schema.py`
- Test: `tests/test_professional_report_schema.py`

**Interfaces:**
- Produces: `ProfessionalPostCloseReport`, `ReportIdentity`, `ExecutiveSummary`, `MarketResearchSection`, `IndustryResearchSection`, `SecurityResearchSection`, `RegressionResearchSection`, `ModelValidationSection`, `DataGovernanceSection`, `AiReferenceAdvice`.
- Produces: `ProfessionalPostCloseReport.validate() -> None` and `to_dict() -> dict[str, object]`.

- [ ] **Step 1: Write failing schema tests**

Cover required identity, source/applicable dates, finite-number rejection, list/dict normalization refusal, observation/prediction separation, and `None` preservation. Use an explicit minimal fixture and assert that `float("nan")`, `float("inf")`, mismatched market dates, or `probability_allowed=False` with a probability field raise `ValueError`.

- [ ] **Step 2: Run the focused tests**

Run: `python -m unittest tests.test_professional_report_schema -v`

Expected: FAIL because `reporting.professional_schema` does not exist.

- [ ] **Step 3: Implement immutable dataclasses and validation**

Implement frozen dataclasses with explicit fields. Use a recursive finite-number validator that treats booleans separately from integers. Require:

```python
@dataclass(frozen=True)
class ReportIdentity:
    schema_version: int
    report_type: Literal["post_close_professional"]
    product_mode: Literal["observation_only", "validated_ranking", "validated_probability"]
    market: Literal["TW"]
    source_market_date: date
    applicable_trading_date: date
    generated_at: datetime
    source_manifest: str
    source_manifest_sha256: str
    generator_version: str
    code_commit_sha: str
```

Require all section collections to be tuples, not permissive `Any` lists. Keep unavailable sections explicit with `status="unavailable"` and `reason_code` rather than fabricated zeroes.

- [ ] **Step 4: Run the focused tests and compile**

Run:

```bash
python -m unittest tests.test_professional_report_schema -v
python -m py_compile reporting/professional_schema.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add reporting/professional_schema.py tests/test_professional_report_schema.py
git commit -m "feat: define institutional report schema"
```

---

### Task 2: Build deterministic report sections from existing observation data

**Files:**
- Create: `reporting/professional_sections.py`
- Create: `reporting/professional_builder.py`
- Test: `tests/test_professional_report_builder.py`
- Fixture: `tests/fixtures/professional_report/observation_snapshot.json`

**Interfaces:**
- Consumes: validated dashboard/observation snapshot, report index metadata, model diagnostic artifact, and trading calendar.
- Produces: `build_professional_post_close_report(inputs: ProfessionalReportInputs) -> ProfessionalPostCloseReport`.

- [ ] **Step 1: Add a sanitized production-shaped fixture**

Include market observation, breadth, industries, stock events, ETF observations, data quality, current failed model gates, and unavailable PIT industry/market-cap analyses. Do not include secrets, private paths, or user data.

- [ ] **Step 2: Write failing builder tests**

Assert that the builder creates all nine chapter groups, sorts industry and security rows deterministically, preserves real zeroes, marks missing analysis unavailable, separates ETFs from stocks, and includes current failed model gates without positive performance language.

- [ ] **Step 3: Run the focused tests**

Run: `python -m unittest tests.test_professional_report_builder -v`

Expected: FAIL because the builder is missing.

- [ ] **Step 4: Implement section builders**

Create focused pure functions:

```python
build_executive_summary(...)
build_market_research(...)
build_flow_and_concentration(...)
build_industry_research(...)
build_security_research(...)
build_regression_research(...)
build_model_validation(...)
build_next_session_framework(...)
build_data_governance(...)
```

Each function must return typed schema objects and must not call network services. It must use already validated inputs, deterministic ordering, explicit limits, and reason codes for unavailable data.

- [ ] **Step 5: Implement the orchestrating builder**

`build_professional_post_close_report()` validates source date identity before assembling sections. It must reject pre-market metadata, prediction fields when the capability state forbids them, and future-dated inputs.

- [ ] **Step 6: Run tests**

Run:

```bash
python -m unittest tests.test_professional_report_builder -v
python -m py_compile reporting/professional_sections.py reporting/professional_builder.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add reporting/professional_sections.py reporting/professional_builder.py tests/test_professional_report_builder.py tests/fixtures/professional_report/observation_snapshot.json
git commit -m "feat: assemble institutional report sections"
```

---

### Task 3: Add regression and quantitative explanation sections without overstating causality

**Files:**
- Modify: `reporting/professional_sections.py`
- Test: `tests/test_professional_report_builder.py`
- Create: `reporting/regression_research.py`
- Test: `tests/test_regression_research.py`

**Interfaces:**
- Produces: `build_explanatory_regression_table(dataset, specification) -> RegressionResult`.
- Produces: `RegressionResult` containing coefficient, robust standard error, t-statistic, p-value, 95% interval, observations, R², adjusted R², fixed effects, sample window, and status.

- [ ] **Step 1: Write failing tests for unavailable and available regression output**

Test that missing PIT inputs produce an unavailable section, not fabricated coefficients. For a small deterministic synthetic fixture, assert exact coefficient ordering and that the report copy says “statistical association, not causality or guaranteed trading value.”

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_regression_research -v`

Expected: FAIL.

- [ ] **Step 3: Implement a minimal explanatory regression adapter**

Reuse existing numerical dependencies already in the repository. Do not add a new statistics package unless no current dependency can produce OLS and robust covariance. Keep the first production specification narrow: relative return explained by market, momentum, volatility, volume, and institutional-flow features, with date and industry fixed effects only when PIT data is available.

- [ ] **Step 4: Add explicit status and disclosure handling**

Supported statuses: `available`, `insufficient_sample`, `missing_pit_inputs`, `singular_design`, `invalid_data`. Never suppress a failed regression into an empty table.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_regression_research tests.test_professional_report_builder -v
git add reporting/regression_research.py reporting/professional_sections.py tests/test_regression_research.py tests/test_professional_report_builder.py
git commit -m "feat: add explanatory regression research"
```

---

### Task 4: Build the institutional PDF renderer

**Files:**
- Create: `reporting/professional_pdf.py`
- Modify: `reporting/pdf_generator.py`
- Test: `tests/test_professional_report_pdf.py`

**Interfaces:**
- Consumes: `ProfessionalPostCloseReport`.
- Produces: `ProfessionalPdfResult(path, sha256, size_bytes, page_count, canonical_report_sha256, warnings)`.

- [ ] **Step 1: Write failing PDF tests**

Generate from the sanitized fixture and assert:

- page count is at least 20 for the full fixture;
- title is `ABSORB 台股市場、產業與量化研究日報`;
- extracted text contains every required chapter heading;
- no `Stock Papi`, test stock, sample watermark, private path, or user ID appears;
- report identity, data date, applicable date, gate failures, methodology, and disclaimer are extractable;
- output SHA and canonical-report SHA are recorded.

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_professional_report_pdf -v`

Expected: FAIL because the renderer does not exist.

- [ ] **Step 3: Implement page templates and reusable components**

Create reusable ReportLab helpers for cover, chapter title, KPI grid, data table, status badge, chart image, unavailable panel, footnote, and page decoration. Keep styles driven by `ReportConfig.theme`; do not hard-code a second brand system.

- [ ] **Step 4: Implement all chapter renders**

Render chapters in the approved order. Use page breaks intentionally so the first 2–3 pages are summary-oriented and the remaining pages contain professional evidence. Use `LongTable` with repeated headers and bounded row counts. Include “not available” panels for missing PIT analyses.

- [ ] **Step 5: Add validation and atomic replacement**

Validate fonts, size, page count, extracted Traditional Chinese text, required headings, finite metadata, and absence of forbidden strings before `os.replace()`.

- [ ] **Step 6: Preserve legacy compatibility**

Leave `DailyIndustryReportGenerator` callable for immutable legacy reports. Add a separate `ProfessionalPostClosePdfGenerator`; do not silently change old report bytes.

- [ ] **Step 7: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_pdf -v
python -m py_compile reporting/professional_pdf.py reporting/pdf_generator.py
git add reporting/professional_pdf.py reporting/pdf_generator.py tests/test_professional_report_pdf.py
git commit -m "feat: render institutional post-close pdf"
```

---

### Task 5: Build the full HTML report from the same canonical schema

**Files:**
- Create: `reporting/professional_html.py`
- Create: `templates/reports/post_close_professional.html`
- Create: `templates/reports/_professional_summary.html`
- Create: `templates/reports/_professional_market.html`
- Create: `templates/reports/_professional_industries.html`
- Create: `templates/reports/_professional_securities.html`
- Create: `templates/reports/_professional_models.html`
- Create: `templates/reports/_professional_methodology.html`
- Test: `tests/test_professional_report_routes.py`

**Interfaces:**
- Produces: `to_professional_report_view(report) -> ProfessionalReportView`.

- [ ] **Step 1: Write failing HTML route tests**

Assert one H1, chapter navigation, summary first, full chapters present, PDF action shown only when verified, correct source/applicable dates, failed gates visible, unavailable analyses explicitly labeled, and no raw HTML rendering.

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_professional_report_routes -v`

Expected: FAIL.

- [ ] **Step 3: Implement safe view conversion**

Convert typed schema objects into presentation values before Jinja. Format percentages, numbers, dates, status labels, and missing values in Python; templates must not perform numeric transformations.

- [ ] **Step 4: Implement the full HTML template and partials**

Keep first-screen summary concise, add sticky chapter navigation on desktop, accessible collapsible sections on mobile, printable styles, tabular numerals, and explicit disclosure blocks.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_routes -v
git add reporting/professional_html.py templates/reports/post_close_professional.html templates/reports/_professional_*.html tests/test_professional_report_routes.py
git commit -m "feat: add full institutional report html"
```

---

### Task 6: Add immutable professional report metadata and repository support

**Files:**
- Create: `reporting/professional_repository.py`
- Modify: current report/GCS repository module used by `stock_papi/services/report_web.py`
- Test: `tests/test_professional_report_repository.py`

**Interfaces:**
- Produces: `ProfessionalReportMetadata` with HTML/content SHA, PDF object, PDF SHA, size, page count, schema version, generator version, dates, and capability status.
- Produces: `publish_professional_candidate(...)`, `load_professional_metadata(...)`, `load_verified_pdf(...)`.

- [ ] **Step 1: Write failing repository tests**

Test allowlisted paths, immutable conflicts, identical retry, SHA mismatch, size mismatch, schema mismatch, private object policy, latest-pointer-last behavior, and preservation of older latest on historical reruns.

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_professional_report_repository -v`

Expected: FAIL.

- [ ] **Step 3: Implement local candidate metadata**

Create dated immutable metadata and PDF objects. Compute canonical report SHA from canonical JSON, not rendered HTML. Store PDF metadata beside report metadata and include `html_available` and `pdf_available`.

- [ ] **Step 4: Implement GCS publish/read-back**

Upload immutable objects first, read back bytes, verify SHA/size, then update index and latest pointer atomically. Never expose bucket paths in public errors.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_repository -v
git add reporting/professional_repository.py stock_papi/services/report_web.py tests/test_professional_report_repository.py
git commit -m "feat: publish professional report artifacts"
```

---

### Task 7: Wire the post-close daily pipeline to build HTML and PDF

**Files:**
- Modify: `stock_papi/batch/daily_products_cli.py`
- Modify: post-close candidate builder/service modules
- Modify: `scripts/upload_local_quant.ps1`
- Test: existing daily-product tests plus `tests/test_professional_report_pipeline.py`

**Interfaces:**
- Consumes: validated post-close run receipt and dashboard snapshot.
- Produces: canonical JSON, professional metadata, full PDF, candidate receipt.

- [ ] **Step 1: Write failing pipeline tests**

Assert that post-close candidates require both canonical report and verified PDF, while pre-market candidates remain concise and do not invoke the full PDF renderer. Test target-date mismatch, missing PDF, failed PDF validation, idempotent rerun, and no pointer updates before all artifacts pass.

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_professional_report_pipeline -v`

Expected: FAIL.

- [ ] **Step 3: Implement candidate assembly**

After observation gates pass, call the professional builder and PDF renderer. Record every artifact SHA in `candidate.json`. Do not call Gemini during deterministic candidate assembly unless a bounded, schema-validated commentary artifact is already available; missing Gemini commentary must degrade to an explicit unavailable AI section rather than block the report.

- [ ] **Step 4: Update upload requirements**

`-RequireReportV2` for post-close must require the professional metadata and PDF. Add a separate pre-market validation path so pre-market remains lightweight.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_pipeline -v
powershell -NoProfile -Command "[scriptblock]::Create((Get-Content scripts/upload_local_quant.ps1 -Raw)) | Out-Null"
git add stock_papi/batch/daily_products_cli.py stock_papi scripts/upload_local_quant.ps1 tests/test_professional_report_pipeline.py
git commit -m "feat: produce institutional post-close reports"
```

---

### Task 8: Add canonical full-report and PDF web routes

**Files:**
- Modify: `stock_papi/web/routes/reports.py`
- Modify: `stock_papi/services/report_view.py`
- Modify: `templates/reports.html`
- Test: `tests/test_professional_report_routes.py`

**Interfaces:**
- Produces routes:
  - `/reports/<source_market_date>/post-close`
  - `/reports/<source_market_date>/post-close/download`

- [ ] **Step 1: Extend failing route tests**

Test 200 HTML, 200 PDF download, `Content-Type: application/pdf`, attachment disposition, `nosniff`, invalid date 404, missing report 404, integrity failure 503 with correlation ID, no arbitrary object path input, and false-empty-state removal.

- [ ] **Step 2: Implement metadata-based route loading**

Load by logical report identity, verify metadata and PDF, build the professional view, and render the full template. Do not pass raw GCS metadata to Jinja.

- [ ] **Step 3: Implement secure PDF streaming**

Stream only verified bytes or use the existing approved short-lived signed-URL policy. Never make the bucket public. Enforce max size and exact expected SHA.

- [ ] **Step 4: Fix report listing semantics**

Show “閱讀網頁完整版” and “下載專業 PDF” on post-close cards. Keep pre-market cards linked to concise pre-market pages. Show the global empty state only when both v2 and legacy collections are empty.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_routes -v
git add stock_papi/web/routes/reports.py stock_papi/services/report_view.py templates/reports.html tests/test_professional_report_routes.py
git commit -m "feat: serve institutional reports and pdfs"
```

---

### Task 9: Derive LINE summary and Gemini report context from the canonical report

**Files:**
- Modify: LINE report renderer module
- Modify: `absorb/conversation/tools.py`
- Modify: `absorb/conversation/prompts.py`
- Test: LINE and conversation tests

**Interfaces:**
- Produces: `get_latest_professional_post_close_report(market) -> bounded tool result`.
- Produces: LINE summary containing canonical report identity and link.

- [ ] **Step 1: Write failing parity tests**

Assert that HTML, PDF, LINE, and Gemini tool results share source date, market state, top industries, risk conditions, gate status, and canonical report SHA. Ensure LINE contains no unsupported probability or strong action.

- [ ] **Step 2: Implement bounded report tool output**

Expose executive summary, selected market/industry/security evidence, next-session conditions, model gate status, data quality, and canonical link. Do not send the entire 25–35 page JSON to Gemini.

- [ ] **Step 3: Update Gemini instructions**

Require explicit labels for system facts, rule-based risk, quantitative output, and Gemini interpretation. Require “AI 模型參考建議” and current validation limitations.

- [ ] **Step 4: Update LINE summary**

Use canonical summary fields and include links to full HTML and PDF. Keep the message compact and idempotent.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests.test_line_flow tests.test_absorb_conversation -v
git add absorb/conversation/tools.py absorb/conversation/prompts.py stock_papi/integrations/line tests
git commit -m "feat: align line and gemini with professional reports"
```

---

### Task 10: Add chart production for institutional sections

**Files:**
- Modify: `reporting/charts.py`
- Test: `tests/test_professional_report_charts.py`

**Interfaces:**
- Produces deterministic chart bytes or temporary files for market trend, breadth, volatility, industry rotation, relative-return ranking, calibration, cumulative backtest, drawdown, feature importance, and SHAP summaries.

- [ ] **Step 1: Write failing chart tests**

Test deterministic dimensions, no external network/font dependency, no NaN/Infinity, accessible labels, missing-data panels, and bounded image sizes.

- [ ] **Step 2: Implement charts using existing plotting conventions**

Reuse current chart utilities and brand tokens. Do not add decorative charts without analytical value. Charts must carry titles, as-of dates, units, legends, and source notes.

- [ ] **Step 3: Integrate chart references into the canonical builder/PDF**

Chart generation must not alter report conclusions. A failed optional chart yields a warning and unavailable panel; a failed required identity/data-quality chart blocks publication.

- [ ] **Step 4: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_charts tests.test_professional_report_pdf -v
git add reporting/charts.py reporting/professional_pdf.py tests/test_professional_report_charts.py
git commit -m "feat: add institutional research charts"
```

---

### Task 11: Add publication gates, receipts, and rollback coverage

**Files:**
- Modify: `scripts/deploy_observation_production.ps1`
- Modify: upload/promotion scripts
- Test: PowerShell and Python deployment tests
- Docs: deployment runbook

**Interfaces:**
- Produces a deployment receipt containing canonical SHA, PDF SHA/size/pages, previous pointers, new pointers, revision, traffic, smoke results, and rollback inputs.

- [ ] **Step 1: Write failing deployment tests**

Cover missing PDF, PDF SHA mismatch, HTML/PDF canonical mismatch, no-traffic route failure, previous-pointer capture, and rollback WhatIf.

- [ ] **Step 2: Add publication gates**

Post-close publication requires canonical JSON, HTML view validation, PDF validation, metadata validation, GCS read-back, report-index consistency, and no-prediction-policy scan.

- [ ] **Step 3: Extend no-traffic smoke tests**

Verify listing, full HTML, PDF download, old routes, OAuth, webhook method/signature behavior, static assets, and absence of 500/error logs.

- [ ] **Step 4: Run tests and commit**

```bash
python -m unittest tests.test_professional_report_repository tests.test_professional_report_routes -v
powershell -NoProfile -File scripts/deploy_observation_production.ps1 -WhatIf
git add scripts docs tests
git commit -m "feat: gate institutional report deployment"
```

---

### Task 12: Backfill one verified trading date and validate production-shaped output

**Files:**
- No source file required unless a defect is found.
- Artifacts remain outside Git under `D:\AbsorbData`.

**Interfaces:**
- Produces a candidate-only professional report for an explicitly selected date, followed by an authorized immutable publish after all gates pass.

- [ ] **Step 1: Generate a candidate for a date with complete PIT data**

Use an explicit `TargetDate`. Do not use current/future data to fill missing historical fields.

- [ ] **Step 2: Validate the candidate**

Confirm 25–35 page target for a normal fixture, correct dates, canonical SHA parity, full chapter coverage, failed model-gate disclosure, no private data, and no unvalidated probability.

- [ ] **Step 3: Render desktop/mobile HTML and download PDF**

Inspect the first 3 pages for novice readability and later pages for institutional depth. Verify tables do not clip and charts remain legible.

- [ ] **Step 4: Publish only after all observation gates pass**

Save previous local/GCS pointers and Cloud Run revision. Upload immutable objects, verify read-back, then update index/latest. Do not update backtest latest.

- [ ] **Step 5: Production smoke and rollback readiness**

Verify live HTML/PDF routes and rollback WhatIf. If any required route fails, restore the previous revision/pointers.

---

### Task 13: Documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `docs/dual-daily-report-runbook.md`
- Create/modify: `docs/reports/institutional-post-close-report.md`
- Modify: deployment, security, troubleshooting, and architecture docs

- [ ] **Step 1: Document report products and boundaries**

Explain pre-market concise update versus institutional post-close report, canonical schema, HTML/PDF parity, Gemini role, current model-gate status, artifact identity, publication, and rollback.

- [ ] **Step 2: Run the complete verification suite**

Run the repository’s full unittest command plus:

```bash
python -m compileall reporting stock_papi absorb
python -m py_compile app.py local_quant.py
node --check static/app.js
git diff --check
```

Also run route inventory, template rendering, PDF extraction/page-count validation, secret scan, legacy-brand scan, no-prediction-policy scan, broken-link scan, desktop/mobile screenshots, no-traffic smoke, and production smoke.

- [ ] **Step 3: Verify exact acceptance criteria**

Confirm:

- pre-market remains concise and independent;
- post-close full HTML and PDF use the same canonical SHA;
- normal report is 25–35 pages;
- all approved chapters appear;
- failed model gates are prominent;
- no unvalidated probability or alpha claim appears;
- GCS remains private;
- PDF download is verified and secure;
- old immutable reports remain readable;
- LINE/Gemini conclusions match the canonical report;
- rollback inputs are complete.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md docs
git commit -m "docs: document institutional post-close reporting"
```

- [ ] **Step 5: Produce the final implementation report**

Include commits, changed files, canonical schema version, generator version, sample report date, page count, SHA values, GCS generations, Cloud Run revision, traffic, tests, smoke results, rollback status, known unavailable PIT analyses, and final `git status`.
