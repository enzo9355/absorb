# Implementation Plan: Task C Regression Explainer & Research Presentation Layer

**Date:** 2026-07-22  
**Status:** APPROVED — Ready for Implementation  
**Target Branch:** `antigravity/task-c-regression-explainer-design`  
**Design Spec:** [Design Spec](../specs/2026-07-22-regression-explainer-design.md)  
**Base SHA:** `da25d594d3b76865da22b891285ac0c85e710d86`  
**Repository:** `enzo9355/absorb`  

---

## Safety & Boundaries

- **No Implementation Code Execution**: This document outlines the planned execution tasks for Task C. Actual code implementation will commence ONLY after user review and approval.
- **Forbidden Actions**:
  - NO LightGBM training or SHAP execution.
  - NO probability, win rate, or trading signal generation.
  - NO prediction capability gate modifications (gates remain BLOCKED / UNAVAILABLE).
  - NO sample or mock data generation in production report builders (`production_regression_source_adapter_ready = false`, `production_regression_input_ready = false`, `production_regression_artifact_available = false`, `aggregate_manifest_interval_validation_ready = false`).
  - NO Cloud Run deployment, Production GCS updates, backfills, or LINE notifications.
  - NO Task D execution.

---

## Detailed Task Plan

### Task A: Regression Schema Definitions & Canonical Serializer
- **Goal**: Define `RegressionResearchArtifact`, `RegressionSpec`, `RegressionResultItem`, `RegressionFitStatistics`, `RegressionDiagnostics`, and `RegressionPresentation` dataclasses with strict JSON schema versioning (`schema_version = 1`, `kind = "absorb-regression-research-artifact"`, `MAX_REGRESSION_ARTIFACT_BYTES = 2_000_000`) and canonical serializer `serialize_regression_artifact()`.
- **Exact Files**:
  - `[NEW] reporting/regression_schema.py`
  - `[NEW] tests/test_regression_schema.py`
- **RED Test**: `tests/test_regression_schema.py::test_empty_document_raises_validation_error`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_schema'`
- **Minimal Implementation**: Dataclasses with `from_document()`, `to_document()`, `serialize_regression_artifact()`, `content_sha256` calculation (excluding `object_sha256` from `identity`), and forbidden word filtering (`Probability`, `勝率`, `上漲機率`, `下跌機率`, `正式預測`, `買進訊號`, `賣出訊號`).
- **Focused Command**: `python -m unittest tests.test_regression_schema -v`
- **Acceptance Criteria**: `RegressionResearchArtifact.from_document(doc)` passes for valid documents, enforces $0 \le R^2 \le 1$, $\text{ci\_low} \le \text{coef} \le \text{ci\_high}$, $\text{SE} \ge 0$, degrees of freedom $>0$, and raises `ValueError` for non-finite values or forbidden terms.
- **Commit Message**: `feat(reporting): define regression research artifact schema and canonical serializer`
- **Rollback Boundary**: Delete `reporting/regression_schema.py` and `tests/test_regression_schema.py`.

---

### Task B1: Self-Contained RegressionInputDataset Schema & Hash Serializers
- **Goal**: Define `RegressionInputDataset`, `RegressionInputRow`, and factor definition schemas with canonical serializers `serialize_regression_input_dataset()` and `serialize_regression_rows()`.
- **Exact Files**:
  - `[NEW] reporting/regression_input_schema.py`
  - `[NEW] tests/test_regression_input_schema.py`
- **RED Test**: `tests/test_regression_input_schema.py::test_input_dataset_validates_rows_and_hashes`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_input_schema'`
- **Minimal Implementation**: Implements `RegressionInputDataset.from_document()` validating `row_count == len(rows)`, ascending `feature_session` order, exact factor column keys, `factor_value_stage == "raw"`, finite float values, `aggregate_manifest_object` path format, `aggregate_manifest_sha256` (64 lowercase hex), `schema_version == 1`, and `canonical_rows_sha256` verification.
- **Focused Command**: `python -m unittest tests.test_regression_input_schema -v`
- **Acceptance Criteria**: Validates 252-row matrix schema, computes `canonical_rows_sha256` and `content_sha256`, validates aggregate manifest metadata format, and rejects duplicate sessions or non-finite values.
- **Commit Message**: `feat(reporting): define self-contained regression input dataset schema and row serializers`
- **Rollback Boundary**: Delete `reporting/regression_input_schema.py` and `tests/test_regression_input_schema.py`.

---

### Task B2: Offline Input Dataset Loader & Validation
- **Goal**: Build `load_regression_input_dataset(object_path, expected_sha256, max_bytes=MAX_REGRESSION_INPUT_DATASET_BYTES)` loader for fetching and verifying raw dataset bytes against size limit `MAX_REGRESSION_INPUT_DATASET_BYTES = 5_000_000` (5MB).
- **Exact Files**:
  - `[NEW] reporting/regression_input_loader.py`
  - `[NEW] tests/test_regression_input_loader.py`
- **RED Test**: `tests/test_regression_input_loader.py::test_load_regression_input_dataset_validates_bytes_and_sha`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_input_loader'`
- **Minimal Implementation**: Implements raw bytes fetch, size check `<= 5MB`, `object_sha256` hash verification, UTF-8 decode, JSON parse, schema validation, and `canonical_rows_sha256` cross-check.
- **Focused Command**: `python -m unittest tests.test_regression_input_loader -v`
- **Acceptance Criteria**: Loader verifies dataset bytes, path regex `^objects/regression-input/[0-9a-f]{64}\.json$`, and returns parsed `RegressionInputDataset`.
- **Commit Message**: `feat(reporting): implement offline regression input dataset raw bytes loader`
- **Rollback Boundary**: Delete `reporting/regression_input_loader.py` and `tests/test_regression_input_loader.py`.

---

### Task B3: Input Dataset Builder & Production Orchestrator Readiness
- **Goal**: Build pure builder `build_regression_input_dataset(source_objects, ...)` and production orchestrator readiness checks (`production_regression_source_adapter_ready = false`, `production_regression_input_ready = false`, `production_regression_artifact_available = false`, `aggregate_manifest_interval_validation_ready = false`). Pure builder constructs valid datasets from verified source objects for unit tests/fixtures, while production orchestrator gates off building/publishing in production reports.
- **Exact Files**:
  - `[NEW] reporting/regression_input_builder.py`
  - `[NEW] tests/test_regression_input_builder.py`
- **RED Test**: `tests/test_regression_input_builder.py::test_production_orchestrator_does_not_build_or_publish_when_readiness_false`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_input_builder'`
- **Minimal Implementation**: Implements pure builder for valid source datasets, and production orchestrator guard returning `None` and preventing production artifact publishing when readiness flags are `false`.
- **Focused Command**: `python -m unittest tests.test_regression_input_builder -v`
- **Acceptance Criteria**: Pure builder constructs valid input dataset when provided valid source objects; production orchestrator returns `None` without invoking builder or publishing fixtures when readiness flags are `false`.
- **Commit Message**: `feat(reporting): implement regression input dataset builder and production orchestrator readiness gates`
- **Rollback Boundary**: Delete `reporting/regression_input_builder.py` and `tests/test_regression_input_builder.py`.

---

### Task B4: Input Dataset Immutable Publisher
- **Goal**: Build `reporting/regression_input_publisher.py` to publish `RegressionInputDataset` objects to `objects/regression-input/<object_sha256>.json` with atomic replace and 11-step read-back verification.
- **Exact Files**:
  - `[NEW] reporting/regression_input_publisher.py`
  - `[NEW] tests/test_regression_input_publisher.py`
  - `[MODIFY] reporting/publisher.py`
- **RED Test**: `tests/test_regression_input_publisher.py::test_publishes_input_dataset_atomically_with_readback`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_input_publisher'`
- **Minimal Implementation**: Implements atomic write to `objects/regression-input/<object_sha256>.json`, size check `<= 5MB`, `object_sha256` calculation, read-back verification, and failure injection rollback. If `production_regression_input_ready == false`, production batch pipeline MUST NOT invoke this publisher.
- **Focused Command**: `python -m unittest tests.test_regression_input_publisher -v`
- **Acceptance Criteria**: Publisher writes input dataset object, verifies SHA256/Rows SHA read-back, and cleans up uncommitted objects on error.
- **Commit Message**: `feat(reporting): implement regression input dataset immutable publisher`
- **Rollback Boundary**: Delete `reporting/regression_input_publisher.py`, `tests/test_regression_input_publisher.py` and revert `reporting/publisher.py`.

---

### Task C: Dependency Manifest, Install Script & Cold-Start Guard Test
- **Goal**: Update `requirements-report.txt` with `statsmodels>=0.14.4,<0.15.0`, create `scripts/install_report_runtime.ps1`, create `stock_papi/research/regression_deps.py`, and build cold-start guard test verifying heavy econometric libraries (`statsmodels`) are NEVER imported at top level of `stock_papi.application`, HTTP routes, or Cloud Run cold-start paths.
- **Exact Files**:
  - `[MODIFY] requirements-report.txt`
  - `[NEW] scripts/install_report_runtime.ps1`
  - `[NEW] stock_papi/research/regression_deps.py`
  - `[NEW] tests/test_cold_start_imports.py`
- **Test Type**: Architecture Guard / Characterization Test
- **Expected Result**: Pass before and after implementation.
- **Minimal Implementation**: Update `requirements-report.txt` with `statsmodels>=0.14.4,<0.15.0`. Create `scripts/install_report_runtime.ps1` for Windows Scheduler runtime installation. Implement lazy import wrapper inside `stock_papi/research/regression_deps.py` loading `statsmodels` exclusively inside function scope.
- **Focused Command**: `python -m unittest tests.test_cold_start_imports -v`
- **Acceptance Criteria**: `stock_papi.application` and `stock_papi.web.routes.reports` can be imported without loading `statsmodels` into `sys.modules`.
- **Commit Message**: `test(architecture): enforce cold start top level import isolation for statsmodels`
- **Rollback Boundary**: `git checkout origin/main -- requirements-report.txt` and delete `scripts/install_report_runtime.ps1`, `stock_papi/research/regression_deps.py`, `tests/test_cold_start_imports.py`.

---

### Task D: OLS & Newey-West HAC Covariance Adapter
- **Goal**: Build `compute_ols_hac_regression(dependent_series, factor_matrix, lags=4)` using `statsmodels` inside offline research module to compute OLS estimates with Newey-West HAC robust covariance (`cov_type="HAC"`, `maxlags=4`, `kernel="bartlett"`, `use_correction=True`, `use_t=True`) for `five_session_forward_return`.
- **Exact Files**:
  - `[NEW] reporting/regression_adapter.py`
  - `[NEW] tests/test_regression_adapter.py`
- **RED Test**: `tests/test_regression_adapter.py::test_computes_newey_west_hac_estimates`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_adapter'`
- **Minimal Implementation**: Calculates OLS estimates with exact Newey-West HAC parameters for overlapping 5-session forward return series.
- **Focused Command**: `python -m unittest tests.test_regression_adapter -v`
- **Acceptance Criteria**: Estimates match reference HAC standard errors, t-statistics, and 95% confidence intervals within tolerance $10^{-5}$.
- **Commit Message**: `feat(reporting): implement OLS factor regression adapter with Newey-West HAC covariance`
- **Rollback Boundary**: Delete `reporting/regression_adapter.py` and `tests/test_regression_adapter.py`.

---

### Task E: Diagnostics & Validation Engine
- **Goal**: Implement statistical validation engine evaluating sample count policy ($n < 30 \rightarrow \text{unavailable}$, $30 \le n < 60 \rightarrow \text{available\_with\_limited\_sample\_warning}$, $60 \le n \le 252 \rightarrow \text{available}$), design matrix rank, Breusch-Pagan heteroskedasticity test, VIF multicollinearity (excluding intercept), Jarque-Bera normality, and Durbin-Watson autocorrelation.
- **Exact Files**:
  - `[NEW] reporting/regression_validation.py`
  - `[NEW] tests/test_regression_validation.py`
- **RED Test**: `tests/test_regression_validation.py::test_sample_count_below_30_fails_hard`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_validation'`
- **Minimal Implementation**: `validate_regression_diagnostics(fit_stats, diagnostics, sample_count)` separating Hard Failures ($n < 30$, rank deficient, non-finite values) from Warnings (VIF $\ge 5.0$, Breusch-Pagan $p < 0.05$).
- **Focused Command**: `python -m unittest tests.test_regression_validation -v`
- **Acceptance Criteria**: Hard Failures mark section `unavailable`; Diagnostic Warnings generate presentation badges without failing report.
- **Commit Message**: `feat(reporting): implement statistical validation and diagnostic engine for regression explainer`
- **Rollback Boundary**: Delete `reporting/regression_validation.py` and `tests/test_regression_validation.py`.

---

### Task F: Regression Artifact Pure Builder
- **Goal**: Build pure builder `build_regression_research_artifact(validated_input_dataset, ...)` orchestrator to generate content-addressed `RegressionResearchArtifact` documents from verified `RegressionInputDataset` objects. Pure builder constructs valid artifacts when provided valid input datasets (used in unit tests, offline fixtures, and future source adapters). Decouple pure builder execution from production orchestrator when readiness flags are `false`.
- **Exact Files**:
  - `[NEW] reporting/regression_builder.py`
  - `[NEW] tests/test_regression_builder.py`
- **RED Test**: `tests/test_regression_builder.py::test_builds_valid_regression_research_artifact`
- **Expected Failure**: `ModuleNotFoundError: No module named 'reporting.regression_builder'`
- **Minimal Implementation**: Orchestrates adapter computation, validation engine, mandatory disclaimers, and content-addressed `content_sha256` generation.
- **Focused Command**: `python -m unittest tests.test_regression_builder -v`
- **Acceptance Criteria**: Successfully builds content-addressed `RegressionResearchArtifact` when provided valid `RegressionInputDataset`, or raises `ValueError` / returns `None` on invalid data.
- **Commit Message**: `feat(reporting): implement regression research artifact pure builder`
- **Rollback Boundary**: Delete `reporting/regression_builder.py` and `tests/test_regression_builder.py`.

---

### Task G: Single-Hash Publisher Integration
- **Goal**: Update `reporting/publisher.py` to execute the exact 10-step atomic publication sequence, calling `serialize_regression_artifact()` once to compute `object_sha256` and write `objects/regression/<object_sha256>.json` with atomic replace and read-back verification.
- **Exact Files**:
  - `[MODIFY] reporting/publisher.py`
  - `[MODIFY] tests/test_canonical_publisher_integrity.py`
- **RED Test**: `tests/test_canonical_publisher_integrity.py::test_publishes_regression_artifact_with_single_hash_ownership`
- **Expected Failure**: `TypeError: publish_report_v2() got an unexpected keyword argument 'regression_artifact'`
- **Minimal Implementation**: Implements atomic write to `objects/regression/<object_sha256>.json`, read-back verification against `MAX_REGRESSION_ARTIFACT_BYTES = 2_000_000`, and exact metadata pointer injection (`metadata/<metadata_sha256>.json`). Saves in-memory byte backups `previous_index_bytes` and `previous_latest_bytes` for rollback.
- **Focused Command**: `python -m unittest tests.test_canonical_publisher_integrity -v`
- **Acceptance Criteria**: Publisher writes regression object, verifies SHA256 read-back, and injects exact metadata pointer.
- **Commit Message**: `feat(reporting): integrate single hash regression publishing into atomic ten step sequence`
- **Rollback Boundary**: `git checkout origin/main -- reporting/publisher.py`.

---

### Task H: Metadata Pointer Schema Extension
- **Goal**: Extend `ReportMetadataV2` in `reporting/schemas.py` to validate `regression_research` pointer dict (`object`, `sha256`, `content_sha256`, `schema_version`, `generator_version`, `code_commit_sha`).
- **Exact Files**:
  - `[MODIFY] reporting/schemas.py`
  - `[MODIFY] tests/test_professional_pointer_schema.py`
- **RED Test**: `tests/test_professional_pointer_schema.py::test_validates_regression_research_pointer`
- **Expected Failure**: `ValueError: report metadata v2 schema contains unknown key 'regression_research'`
- **Minimal Implementation**: Update `ReportMetadataV2.from_document()` to validate `regression_research` pointer keys enforcing `pointer.object == f"objects/regression/{pointer.sha256}.json"`.
- **Focused Command**: `python -m unittest tests.test_professional_pointer_schema -v`
- **Acceptance Criteria**: `ReportMetadataV2` parses and validates valid `regression_research` pointers and rejects malformed paths or SHA mismatches.
- **Commit Message**: `feat(reporting): extend metadata v2 schema with regression research pointer validation`
- **Rollback Boundary**: `git checkout origin/main -- reporting/schemas.py`.

---

### Task I: Optional Regression Binding Validator
- **Goal**: Implement `validate_regression_research_binding(metadata, professional_report, regression_pointer, regression_artifact)` in `reporting/professional_binding.py` for optional research binding validation.
- **Exact Files**:
  - `[MODIFY] reporting/professional_binding.py`
  - `[MODIFY] tests/test_professional_report_binding.py`
- **RED Test**: `tests/test_professional_report_binding.py::test_optional_regression_binding_validation`
- **Expected Failure**: `ImportError: cannot import name 'validate_regression_research_binding' from 'reporting.professional_binding'`
- **Minimal Implementation**: Cross-checks regression pointer SHA, semantic content SHA, source dates, manifest SHA, and commit SHA. On mismatch, raises `ValueError` caught by optional route handler (does NOT affect critical canonical binding `validate_professional_report_binding`).
- **Focused Command**: `python -m unittest tests.test_professional_report_binding -v`
- **Acceptance Criteria**: Validator verifies optional regression binding without mutating critical canonical report binding logic.
- **Commit Message**: `feat(reporting): implement optional regression research binding validator`
- **Rollback Boundary**: `git checkout origin/main -- reporting/professional_binding.py`.

---

### Task J: Application Raw-Bytes Regression Loader
- **Goal**: Add `load_regression_object(object_path, max_bytes=MAX_REGRESSION_ARTIFACT_BYTES)` in `stock_papi/application.py`.
- **Exact Files**:
  - `[MODIFY] stock_papi/application.py`
  - `[NEW] tests/test_regression_loader.py`
- **RED Test**: `tests/test_regression_loader.py::test_load_regression_object_validates_path_and_bytes`
- **Expected Failure**: `AttributeError: module 'stock_papi.application' has no attribute 'load_regression_object'`
- **Minimal Implementation**: Implements `load_regression_object` with regex `^objects/regression/[0-9a-f]{64}\.json$`, size limit `MAX_REGRESSION_ARTIFACT_BYTES = 2_000_000`, defensive parameter checks, and prefixing `reports/v2/`.
- **Focused Command**: `python -m unittest tests.test_regression_loader -v`
- **Acceptance Criteria**: Loader fetches raw bytes, validates exact regex path, rejects traversal/uppercase/oversized inputs, and returns `None` on error.
- **Commit Message**: `feat(application): implement raw bytes load_regression_object loader`
- **Rollback Boundary**: `git checkout origin/main -- stock_papi/application.py` and delete `tests/test_regression_loader.py`.

---

### Task K: Route Optional Loading & View Model Overlay
- **Goal**: Update `_observation_page` in `stock_papi/web/routes/reports.py` to attempt optional regression loading using `load_regression_object`. Pass loaded artifact or `regression_unavailable_reason` to `build_professional_report_view()` overlay without mutating canonical report object. Maintains HTTP 200 OK.
- **Exact Files**:
  - `[MODIFY] stock_papi/web/routes/reports.py`
  - `[NEW] tests/test_regression_route.py`
- **RED Test**: `tests/test_regression_route.py::test_missing_regression_artifact_returns_200_with_unavailable_section`
- **Expected Failure**: Route attempts to invoke `load_regression_object` when passed in dependency injection.
- **Minimal Implementation**: Adds `load_regression_object=None` optional dependency to `register_report_routes`. Implements 7-step route data flow for regression artifact loading and view model overlay.
- **Focused Command**: `python -m unittest tests.test_regression_route -v`
- **Acceptance Criteria**: Valid regression artifact populates `quantitative_research` view model; missing or corrupted regression artifact returns HTTP 200 OK with `status = "unavailable"`.
- **Commit Message**: `feat(web): add optional regression artifact loading with view model overlay degradation`
- **Rollback Boundary**: `git checkout origin/main -- stock_papi/web/routes/reports.py` and delete `tests/test_regression_route.py`.

---

### Task L: HTML View Model Overlay Adapter
- **Goal**: Update `build_professional_report_view(report, *, regression_artifact=None, regression_unavailable_reason=None, pdf_download_url=None)` in `reporting/professional_html.py` to format `quantitative_research` view model without mutating `report`.
- **Exact Files**:
  - `[MODIFY] reporting/professional_html.py`
  - `[MODIFY] tests/test_professional_report_html.py`
- **RED Test**: `tests/test_professional_report_html.py::test_view_model_overlay_does_not_mutate_canonical_report`
- **Expected Failure**: `TypeError: build_professional_report_view() got an unexpected keyword argument 'regression_artifact'`
- **Minimal Implementation**: Formats Jinja-safe view model containing section title, `AI 模型參考建議`, `模型方向參考`, factor exposures table, diagnostic badges, and mandatory disclosure text. Leaves `report.quantitative_research.status` unmutated.
- **Focused Command**: `python -m unittest tests.test_professional_report_html -v`
- **Acceptance Criteria**: View model contains structured factor exposures and mandatory disclaimers; canonical report object remains unmutated.
- **Commit Message**: `feat(reporting): implement view model overlay interface for quantitative regression section`
- **Rollback Boundary**: `git checkout origin/main -- reporting/professional_html.py`.

---

### Task M: HTML Template Rendering
- **Goal**: Update Jinja template `templates/reports/post_close_professional.html` to render the `quantitative_research` section card with factor exposure table, diagnostic badges, and mandatory disclaimers.
- **Exact Files**:
  - `[MODIFY] templates/reports/post_close_professional.html`
  - `[NEW] tests/test_reports_template_regression.py`
- **RED Test**: `tests/test_reports_template_regression.py::test_renders_quantitative_research_section_card`
- **Expected Failure**: Template output does not contain `量化與迴歸因子研究` or `模型方向參考`.
- **Minimal Implementation**: Adds Jinja block for `report.quantitative_research` rendering factor coefficients, t-stats, p-values, 95% CIs, diagnostic status, and limitations box.
- **Focused Command**: `python -m unittest tests.test_reports_template_regression -v`
- **Acceptance Criteria**: Template renders clean HTML table for `status == "available"` and alert card for `status == "unavailable"`.
- **Commit Message**: `feat(web): render quantitative regression research section in post-close report template`
- **Rollback Boundary**: `git checkout origin/main -- templates/reports/post_close_professional.html` and delete `tests/test_reports_template_regression.py`.

---

### Task N: Publisher Rollback & Failure Injection Test Suite
- **Goal**: Build failure injection tests verifying that if metadata, index, or latest write fails during publishing, newly created regression objects are cleanly unlinked and previous index/latest states are restored.
- **Exact Files**:
  - `[NEW] tests/test_regression_publisher_rollback.py`
- **RED Test**: `tests/test_regression_publisher_rollback.py::test_publisher_rollback_restores_previous_index_and_latest`
- **Expected Failure**: Test fails until publisher rollback restores `previous_index_bytes` and `previous_latest_bytes` on write failure.
- **Minimal Implementation**: Verifies unlinking of newly created `objects/regression/<object_sha256>.json` and byte restoration of `index-TW.json` and `latest-TW-post_close.json` on simulated write exceptions.
- **Focused Command**: `python -m unittest tests.test_regression_publisher_rollback -v`
- **Acceptance Criteria**: Publisher rollback restores index/latest states and cleans up newly created regression artifacts without mutating pre-existing identical files.
- **Commit Message**: `test(reporting): verify publisher rollback and failure injection suite for regression artifacts`
- **Rollback Boundary**: Delete `tests/test_regression_publisher_rollback.py`.

---

### Task O: Pre-market, Notification & PDF Non-regression Guard Tests
- **Goal**: Verify pre-market core lineage (`content.core`), notification date semantics, and PDF generator remain 100% unaffected by regression explainer updates.
- **Exact Files**:
  - `[MODIFY] tests/test_pre_market_pipeline.py`
  - `[MODIFY] tests/test_report_notification_dates.py`
- **Test Type**: Architecture Guard / Non-Regression Guard Test
- **Expected Result**: Pass before and after implementation.
- **Minimal Implementation**: Ensures pre-market raw core lineage remains untouched and post-close notification URLs continue using `source_market_date`.
- **Focused Command**: `python -m unittest tests.test_pre_market_pipeline tests.test_report_notification_dates -v`
- **Acceptance Criteria**: All 100% of pre-market and notification tests pass cleanly with zero regressions.
- **Commit Message**: `test(pipeline): verify pre-market lineage and notification dates unaffected by regression explainer`
- **Rollback Boundary**: `git checkout origin/main -- tests/test_pre_market_pipeline.py tests/test_report_notification_dates.py`.

---

### Task P: Cold-start, Secret & Sample-Data Guard Scans
- **Goal**: Execute security and code hygiene scans asserting zero secrets, zero legacy persona references, zero sample data leaks, and zero statsmodels top-level imports in web paths.
- **Exact Files**:
  - `[MODIFY] tests/test_absorb_security.py`
- **Test Type**: Security Guard Test
- **Expected Result**: Pass before and after implementation.
- **Minimal Implementation**: Scans codebase AST for forbidden top-level imports and hardcoded credentials.
- **Focused Command**: `python -m unittest tests.test_absorb_security -v`
- **Acceptance Criteria**: All security and import isolation checks pass.
- **Commit Message**: `test(security): audit code hygiene, secret scan, and import isolation for regression explainer`
- **Rollback Boundary**: `git checkout origin/main -- tests/test_absorb_security.py`.

---

### Task Q: Full Verification & Lint Audit
- **Goal**: Run full test suite, verify compilation, check JavaScript syntax, and audit git diff formatting.
- **Commands**:
  - `python -m unittest discover tests -v`
  - `python -m compileall reporting stock_papi tests`
  - `node --check static/app.js`
  - `git diff --check`
- **Commit Message**: `docs: align regression builder and source readiness contracts`
- **Acceptance Criteria**: All 717+ unit tests pass, zero compile errors, zero git diff formatting warnings.
- **Rollback Boundary**: N/A.

---

## Acceptance Summary

Upon user approval of the Design Spec and Implementation Plan, execution of Tasks A through Q will proceed sequentially with per-task commits, RED/GREEN test cycles, and full rollback boundaries.
