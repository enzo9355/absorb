# Production Runner Python Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Taiwan production pipelines' dependency on a transient Codex runtime and resolve Python deterministically from an explicit override, the runner-local virtual environment, or the system installation.

**Architecture:** Add one shared PowerShell resolver that validates an optional absolute `ABSORB_PYTHON_EXE`, then prefers `<RepoRoot>\.venv\Scripts\python.exe`, then falls back to `Get-Command python`. The Taiwan post-close and pre-market scripts dot-source the helper and use the returned executable; focused Windows PowerShell tests exercise the real helper behavior while scheduler tests lock the wiring and prohibit the Codex cache path.

**Tech Stack:** Windows PowerShell 5.1, Python `unittest`, GitHub pull requests.

## Global Constraints

- Base commit: `55dadc4e65220424edfec7a45b35ad3180036e5c`.
- Do not modify data contracts, GCS publication logic, notifications, scheduled-task registration, regression readiness flags, backtests, Cloud Run, or model behavior.
- Runtime priority is exactly: valid `ABSORB_PYTHON_EXE` → runner-local `.venv\Scripts\python.exe` → system `python.exe`.
- A present but invalid `ABSORB_PYTHON_EXE` fails closed; it never falls through.
- The resolver must not reference `%USERPROFILE%\.cache\codex-runtimes`.
- Windows PowerShell 5.1 compatibility is mandatory.
- No live FinMind, Production credentials, Pipeline execution, GCS mutation, deployment, Scheduled Task mutation, backfill, or LINE delivery.

---

### Task 1: Lock the runtime contract with failing tests

**Files:**
- Create: `tests/test_python_runtime_wrapper.py`
- Modify: `tests/test_pipeline_scheduler.py`

**Interfaces:**
- Consumes: repository `scripts` directory and Windows PowerShell 5.1.
- Produces: behavioral contract for `Resolve-AbsorbPythonExecutable -RepoRoot <path>`.

- [ ] Add Windows-only tests that create temporary fake executables and verify explicit override, local `.venv`, system fallback, invalid override failure, and no-runtime failure.
- [ ] Add static scheduler assertions that both Taiwan scripts dot-source `python_runtime.ps1`, call `Resolve-AbsorbPythonExecutable`, and contain no `codex-runtimes` reference.
- [ ] Run the focused tests and confirm they fail because the helper and wiring do not yet exist.
- [ ] Commit as `test(tasks): define production Python runtime resolution`.

### Task 2: Implement the minimal shared resolver

**Files:**
- Create: `scripts/python_runtime.ps1`
- Modify: `scripts/run_tw_post_close_pipeline.ps1`
- Modify: `scripts/run_tw_pre_market_pipeline.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Resolve-AbsorbPythonExecutable([string]$RepoRoot) -> [string]`.
- Selection priority: explicit absolute override, runner-local virtual environment, system Python.

- [ ] Implement fail-closed validation for `ABSORB_PYTHON_EXE` and canonical file resolution.
- [ ] Prefer `<RepoRoot>\.venv\Scripts\python.exe` when no override is present.
- [ ] Fall back to `Get-Command python` and reject missing or non-file results.
- [ ] Dot-source the helper from both Taiwan pipeline scripts and replace the transient Codex runtime selection.
- [ ] Add `.venv/` to `.gitignore`.
- [ ] Run focused tests, full unit tests, Python compilation, JavaScript syntax, PowerShell parser checks, and `git diff --check`.
- [ ] Commit as `fix(tasks): prefer stable production Python runtime`.

### Task 3: Publish a reviewable Draft PR

**Files:**
- No additional source changes.

- [ ] Push `assistant/production-runner-recovery` without force.
- [ ] Open a Draft PR titled `fix: stabilize production runner Python resolution`.
- [ ] Document the stale-data incident, exact runtime scope, local verification status, absence of GitHub Actions, and Production safety boundaries.
- [ ] Keep the PR Draft for independent review; do not merge or perform Production operations.
