# Implementation Plan: Task C Regression Explainer & Research Presentation Layer

**Date:** 2026-07-22  
**Status:** DRAFT (Pending User Review & Design Spec Approval)  
**Target Branch:** `antigravity/task-c-regression-explainer-design`  
**Design Spec:** [docs/superpowers/specs/2026-07-22-regression-explainer-design.md](file:///C:/Users/enzo/Documents/absorb-institutional-report/docs/superpowers/specs/2026-07-22-regression-explainer-design.md)  
**Base SHA:** `39d66adb23d2795143ccac7bf3661db97192e054`  
**Repository:** `enzo9355/absorb`  

---

## Safety & Boundaries

- **No Implementation Code Execution**: This document outlines the planned execution tasks for Task C. Actual code implementation will commence ONLY after user review and approval.
- **Forbidden Actions**:
  - NO LightGBM training or SHAP execution.
  - NO probability, win rate, or trading signal generation.
  - NO prediction capability gate modifications (gates remain BLOCKED / UNAVAILABLE).
  - NO Cloud Run deployment, Production GCS updates, backfills, or LINE notifications.
  - NO Task D execution.

---

## Detailed Task Plan

### Task A: Regression Artifact Schema Definitions
- **Goal**: Define `RegressionResearchArtifact`, `RegressionSpec`, `RegressionResultItem`, `RegressionFitStatistics`, `RegressionDiagnostics`, and `RegressionPresentation` dataclasses with strict JSON schema versioning (`schema_version = 1`, `kind = "absorb-regression-research-artifact"`).
- **Files**:
  - `[NEW] reporting/regression_schema.py`
- **RED Test**: `tests/test_regression_schema.py::test_empty_document_raises_validation_error`
- **Implementation**: Dataclasses with `from_document()` and `to_document()` enforcing finite JSON values, required field checks, and forbidden word filtering (`Probability`, `勝率`, `上漲機率`, `下跌機率`, `正式預測`, `買進訊號`, `賣出訊號`).
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_regression_schema.py`
- **Commit Message**: `feat(reporting): define regression research artifact schema`
- **Acceptance Criteria**: `RegressionResearchArtifact.from_document(doc)` passes for valid documents and raises `ValueError` for non-finite values or forbidden terms.
- **Rollback Boundary**: Delete `reporting/regression_schema.py`.

---

### Task B: Schema Validation Unit Tests
- **Goal**: Build comprehensive test coverage for `RegressionResearchArtifact` schema validation rules, boundary edge cases, and safety term restrictions.
- **Files**:
  - `[NEW] tests/test_regression_schema.py`
- **RED Test**: `tests/test_regression_schema.py` (verify fail-closed behavior before full validation implementation).
- **Implementation**: Unit tests covering valid artifact round-trips, invalid dates, non-finite values (`NaN`, `Infinity`, `bool` as `int`), sample size violations ($n < 30$), confidence interval order violations ($\text{ci\_low} > \text{ci\_high}$), and forbidden predictive words.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_regression_schema.py`
- **Commit Message**: `test(reporting): add unit tests for regression research artifact schema`
- **Acceptance Criteria**: 100% of schema validation tests pass cleanly.
- **Rollback Boundary**: Delete `tests/test_regression_schema.py`.

---

### Task C: Regression Result Adapter
- **Goal**: Build an adapter to ingest raw observation/factor data and compute deterministic OLS linear factor coefficients, standard errors, t-statistics, p-values, and 95% confidence intervals using numpy/scipy/statsmodels or pure math.
- **Files**:
  - `[NEW] reporting/regression_adapter.py`
- **RED Test**: `tests/test_regression_adapter.py::test_adapter_computes_valid_ols_coefficients`
- **Implementation**: Implement `compute_ols_factor_regression(dependent_series, factor_matrix, dates)` with strict point-in-time window indexing ($t \le \text{source\_market\_date}$).
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_regression_adapter.py`
- **Commit Message**: `feat(reporting): implement OLS factor regression adapter`
- **Acceptance Criteria**: Adapter computes exact OLS estimates, standard errors, and confidence intervals matching statsmodels reference values.
- **Rollback Boundary**: Delete `reporting/regression_adapter.py`.

---

### Task D: Statistical Validation Engine
- **Goal**: Implement automated statistical validity checks including sample size boundary ($n \ge 30$), VIF multicollinearity test, Durbin-Watson autocorrelation check, White heteroskedasticity test, and Jarque-Bera residual normality check.
- **Files**:
  - `[NEW] reporting/regression_validation.py`
- **RED Test**: `tests/test_regression_validation.py::test_insufficient_sample_fails_validation`
- **Implementation**: `validate_regression_statistics(results, diagnostics)` returning `is_valid: bool` and structured `warnings: list[str]`. If $n < 30$ or critical assumption fails, returns `is_valid = False`.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_regression_validation.py`
- **Commit Message**: `feat(reporting): implement statistical validation engine for regression explainer`
- **Acceptance Criteria**: Validation engine correctly identifies valid vs invalid regression fits and generates diagnostic warnings.
- **Rollback Boundary**: Delete `reporting/regression_validation.py`.

---

### Task E: Regression Artifact Builder
- **Goal**: Build `build_regression_research_artifact(...)` orchestrator to generate `RegressionResearchArtifact` documents from verified observation manifests.
- **Files**:
  - `[NEW] reporting/regression_builder.py`
- **RED Test**: `tests/test_regression_builder.py::test_builds_valid_regression_research_artifact`
- **Implementation**: Orchestrates adapter computation, validation engine, mandatory disclaimers, and identity generation (`content_sha256`, `code_commit_sha`). If validation fails, returns `None`.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_regression_builder.py`
- **Commit Message**: `feat(reporting): implement regression research artifact builder`
- **Acceptance Criteria**: Successfully builds content-addressed `RegressionResearchArtifact` or returns `None` on invalid data.
- **Rollback Boundary**: Delete `reporting/regression_builder.py`.

---

### Task F: Immutable Publisher Pipeline Updates
- **Goal**: Update `reporting/publisher.py` to publish `objects/regression/<content_sha256>.json` with atomic write, post-write read-back size and SHA verification, and pointer injection.
- **Files**:
  - `[MODIFY] reporting/publisher.py`
  - `[MODIFY] tests/test_canonical_publisher_integrity.py`
- **RED Test**: `tests/test_canonical_publisher_integrity.py::test_publishes_regression_artifact_with_readback_verification`
- **Implementation**: Extend `publish_report_v2` to support optional `regression_artifact`. Perform atomic write to `objects/regression/<sha256>.json`, perform read-back hash match, and inject `regression_research` pointer into `metadata`.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_canonical_publisher_integrity.py`
- **Commit Message**: `feat(reporting): integrate regression artifact publishing with read-back verification`
- **Acceptance Criteria**: Publisher writes regression object, verifies SHA256 read-back, and injects valid metadata pointer.
- **Rollback Boundary**: `git checkout origin/main -- reporting/publisher.py`.

---

### Task G: Metadata Pointer Schema Extension
- **Goal**: Extend `ReportMetadataV2` in `reporting/schemas.py` to support `regression_research` pointer dict validation.
- **Files**:
  - `[MODIFY] reporting/schemas.py`
  - `[MODIFY] tests/test_professional_pointer_schema.py`
- **RED Test**: `tests/test_professional_pointer_schema.py::test_validates_regression_research_pointer`
- **Implementation**: Update `ReportMetadataV2.from_document()` to validate `regression_research` pointer keys (`object`, `sha256`, `content_sha256`, `schema_version`, `generator_version`, `code_commit_sha`).
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_professional_pointer_schema.py`
- **Commit Message**: `feat(reporting): extend metadata v2 schema with regression research pointer`
- **Acceptance Criteria**: `ReportMetadataV2` parses and validates valid `regression_research` pointers and rejects malformed paths or SHA mismatches.
- **Rollback Boundary**: `git checkout origin/main -- reporting/schemas.py`.

---

### Task H: Canonical Binding Validation Updates
- **Goal**: Update `validate_professional_report_binding()` in `reporting/professional_binding.py` to cross-validate regression research pointer identity and SHA.
- **Files**:
  - `[MODIFY] reporting/professional_binding.py`
  - `[MODIFY] tests/test_professional_report_binding.py`
- **RED Test**: `tests/test_professional_report_binding.py::test_cross_validates_regression_pointer_sha`
- **Implementation**: Add pointer cross-checks verifying `pointer.content_sha256 == identity.content_sha256` and `code_commit_sha`.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_professional_report_binding.py`
- **Commit Message**: `feat(reporting): add regression pointer cross-validation to canonical binding`
- **Acceptance Criteria**: Binding validator raises `ValueError` if regression pointer content SHA or commit SHA mismatches.
- **Rollback Boundary**: `git checkout origin/main -- reporting/professional_binding.py`.

---

### Task I: HTML View Model Adapter Updates
- **Goal**: Update `build_professional_report_view()` in `reporting/professional_html.py` to format `quantitative_research` section data into Jinja-safe view model.
- **Files**:
  - `[MODIFY] reporting/professional_html.py`
  - `[MODIFY] tests/test_report_web.py`
- **RED Test**: `tests/test_report_web.py::test_view_model_contains_regression_research_data`
- **Implementation**: Populate `quantitative_research` view model with title, `AI 模型參考建議`, `模型方向參考`, factor exposures table, diagnostic badges, and mandatory disclaimer.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_report_web.py`
- **Commit Message**: `feat(reporting): format regression research section in HTML view model`
- **Acceptance Criteria**: View model contains structured factor exposures, mandatory disclaimers, and zero forbidden terms.
- **Rollback Boundary**: `git checkout origin/main -- reporting/professional_html.py`.

---

### Task J: HTML Template Rendering
- **Goal**: Update Jinja template `templates/reports/post_close_professional.html` to render the `quantitative_research` section card with factor exposure table, diagnostic badges, and mandatory disclaimers.
- **Files**:
  - `[MODIFY] templates/reports/post_close_professional.html`
- **RED Test**: Render test in `tests/test_canonical_report_route_integrity.py` verifying HTML output contains `量化與迴歸因子研究` and `模型方向參考`.
- **Implementation**: Add Jinja block for `report.quantitative_research` rendering factor coefficients, t-stats, p-values, 95% CIs, diagnostic status, and limitations box.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_canonical_report_route_integrity.py`
- **Commit Message**: `feat(web): render quantitative regression research section in post-close report template`
- **Acceptance Criteria**: Template renders clean HTML table for `status == "available"` and alert card for `status == "unavailable"`.
- **Rollback Boundary**: `git checkout origin/main -- templates/reports/post_close_professional.html`.

---

### Task K: Section Unavailable Fail-Closed Integration Test
- **Goal**: Verify that when regression artifact is missing, unreadable, or invalid, the route renders HTTP 200 OK with `quantitative_research.status = "unavailable"` without throwing HTTP 503.
- **Files**:
  - `[MODIFY] tests/test_canonical_report_route_integrity.py`
- **RED Test**: `tests/test_canonical_report_route_integrity.py::test_missing_regression_artifact_returns_200_with_unavailable_section`
- **Implementation**: Test route with missing regression artifact object; assert status code is 200, response body contains `迴歸與量化研究暫不提供`, and no 503 error is raised.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_canonical_report_route_integrity.py`
- **Commit Message**: `test(web): verify fail-closed unavailable state for missing regression artifact`
- **Acceptance Criteria**: Missing regression artifact yields 200 OK with graceful unavailable card.
- **Rollback Boundary**: Revert edits in `tests/test_canonical_report_route_integrity.py`.

---

### Task L: Pre-Market Pipeline Non-Regression Verification
- **Goal**: Verify pre-market pipeline core lineage (`content.core`) remains 100% unaffected by post-close regression explainer artifacts.
- **Files**:
  - `[MODIFY] tests/test_pre_market_pipeline.py`
- **RED Test**: `tests/test_pre_market_pipeline.py::test_pre_market_lineage_unaffected_by_regression_artifacts`
- **Implementation**: Run pre-market pipeline tests with and without regression artifacts present; assert identical raw core bytes.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_pre_market_pipeline.py`
- **Commit Message**: `test(pipeline): verify pre-market raw core lineage unaffected by regression artifacts`
- **Acceptance Criteria**: Pre-market pipeline tests pass with 0 regressions.
- **Rollback Boundary**: Revert edits in `tests/test_pre_market_pipeline.py`.

---

### Task M: Notification & Download URL Non-Regression Verification
- **Goal**: Verify post-close and pre-market notification URLs continue to use correct date parameters (`source_market_date` vs `applicable_trading_date`) and `pdf_download_url` remains `None`.
- **Files**:
  - `[MODIFY] tests/test_report_notification_dates.py`
- **RED Test**: `tests/test_report_notification_dates.py`
- **Implementation**: Verify notification date logic and PDF button `None` invariant.
- **Focused Test**: `C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests/test_report_notification_dates.py`
- **Commit Message**: `test(notification): verify notification URL dates and PDF None invariant`
- **Acceptance Criteria**: Notification tests pass with 0 regressions.
- **Rollback Boundary**: Revert edits in `tests/test_report_notification_dates.py`.

---

### Task N: Full Suite Verification & Formatting Audit
- **Goal**: Run complete test suite across repository, verify zero regressions, run `compileall`, `node --check`, and `git diff --check`.
- **Commands**:
  - `python -m unittest discover tests -v`
  - `python -m compileall reporting stock_papi tests`
  - `node --check static/app.js`
  - `git diff --check`
- **Commit Message**: `docs: complete Task C regression explainer design and plan`
- **Acceptance Criteria**: All 717+ unit tests pass, zero compile errors, zero git diff formatting warnings.
- **Rollback Boundary**: N/A.

---

## Acceptance Summary

Upon user approval of the Design Spec and Implementation Plan, execution of Tasks A through N will proceed sequentially with per-task commits, RED/GREEN test cycles, and full rollback boundaries.
