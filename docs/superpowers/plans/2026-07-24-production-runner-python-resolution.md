# Production Runner Python Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Taiwan production pipelines' dependency on a transient Codex runtime, make their Python selection deterministic, and keep reporting status output valid on non-UTF-8 Windows streams.

**Architecture:** Add one shared Windows PowerShell resolver that validates an optional absolute `ABSORB_PYTHON_EXE`, then prefers `<RepoRoot>\.venv\Scripts\python.exe`, then falls back to the system Python application. Both Taiwan pipelines use the same resolver and verify that the selected runtime can import `stock_papi`. The reporting CLI emits native-language JSON when the target stream supports it and falls back to ASCII-escaped JSON when the stream encoding cannot represent Traditional Chinese.

**Tech Stack:** Windows PowerShell 5.1, Python 3.10, Python `unittest`, GitHub Actions.

## Global Constraints

- Base commit: `55dadc4e65220424edfec7a45b35ad3180036e5c`.
- Do not modify data contracts, GCS publication logic, notifications, scheduled-task registration, regression readiness flags, backtests, Cloud Run, or model behavior.
- Runtime priority is exactly: valid `ABSORB_PYTHON_EXE` → runner-local `.venv\Scripts\python.exe` → system `python.exe`.
- A present but invalid `ABSORB_PYTHON_EXE` fails closed; it never falls through.
- The resolver must not reference `%USERPROFILE%\.cache\codex-runtimes`.
- Windows PowerShell 5.1 and Python 3.10 compatibility are mandatory.
- Status JSON must remain parseable even when stdout or stderr uses a narrow Windows code page.
- No live FinMind, Production credentials, Pipeline execution, GCS mutation, deployment, Scheduled Task mutation, backfill, or LINE delivery during implementation and verification.

---

### Task 1: Lock and implement stable Python resolution

**Files:**
- Create: `scripts/python_runtime.ps1`
- Create: `tests/test_python_runtime_wrapper.py`
- Modify: `scripts/run_tw_post_close_pipeline.ps1`
- Modify: `scripts/run_tw_pre_market_pipeline.ps1`
- Modify: `tests/test_pipeline_scheduler.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Resolve-AbsorbPythonExecutable([string]$RepoRoot) -> [string]`.
- Produces: `Assert-AbsorbPythonRuntime([string]$PythonExe, [string]$RepoRoot) -> void`.

- [ ] Write Windows PowerShell behavior tests for explicit override, runner-local `.venv`, system fallback, invalid override, no runtime, repository-root imports, and safe failure output.
- [ ] Confirm the tests fail before the helper and wiring exist.
- [ ] Implement the shared resolver and fail-closed runtime smoke check.
- [ ] Wire both Taiwan pipeline scripts to the shared helper and remove the Codex cache path.
- [ ] Include `RepoRoot` and `.deps` in `PYTHONPATH` so module execution is independent of the caller's working directory.
- [ ] Add `.venv/` to `.gitignore`.
- [ ] Run focused tests and Windows PowerShell 5.1 parser validation.

### Task 2: Make reporting status output Windows-safe

**Files:**
- Modify: `reporting/cli.py`
- Modify: `tests/test_daily_report_cli.py`

**Interfaces:**
- Produces: `_print_status_json(document: dict, *, stream: TextIO | None = None) -> None`.

- [ ] Write a failing test using a `cp1252` text stream and Traditional Chinese status content.
- [ ] Confirm the existing direct `print(json.dumps(..., ensure_ascii=False))` path raises or causes the CLI to return failure on Windows.
- [ ] Implement native-language JSON output when the stream supports it.
- [ ] Fall back to `ensure_ascii=True` only when the stream encoding cannot represent the JSON text.
- [ ] Route success and error status output through the helper without changing the persisted UTF-8 status file.
- [ ] Run the reporting CLI tests and the complete suite.

### Task 3: Verify and publish a clean review branch

**Files:**
- No additional Production source changes.

- [ ] Verify twice on Windows Python 3.10 that the runtime tests pass.
- [ ] Run scheduler tests, reporting CLI tests, the focused reliability suite, and the complete test suite.
- [ ] Run Python compilation, JavaScript syntax, Windows PowerShell 5.1 parser checks, `git diff --check`, readiness-flag checks, and the forbidden-artifact check.
- [ ] Keep diagnostic workflows and test fonts out of the final branch.
- [ ] Open a Draft PR from the clean branch, document exact verification evidence, and require a final head gate before Merge Commit integration.
