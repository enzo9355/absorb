# 本機正式日報鏡像與 SAMPLE 下載 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將每份已成功發布的正式日報寫入人類可讀的本機鏡像，並提供與正式資料流隔離的 SAMPLE PDF 下載。

**Architecture:** `publisher` 在正式 latest 已原子更新後，以正式 metadata 與 PDF bytes 寫入 `<root>/reports/TW` 鏡像與 sidecar。CLI 只在該目錄的 staging 子目錄生成候選 PDF。SAMPLE 是隨映像佈署的固定靜態 PDF，Flask route 只讀該固定檔案。

**Tech Stack:** Python 3.10+、stdlib、Flask、ReportLab、pypdf、unittest。

## Global Constraints

- 不修改正式 GCS report index/latest 讀取與驗證流程。
- 不新增相依套件，不在 Cloud Run request 產生 PDF。
- 鏡像目錄從 `root` 與 market 推導；不得寫死 `D:\\StockPapiData`。
- SAMPLE 不得寫入正式 index、latest、metadata 或鏡像目錄。
- 正式 PDF／sidecar 均使用 temporary file、fsync 與 `os.replace()`。

---

### Task 1: 正式發布後的本機鏡像

**Files:**
- Modify: `reporting/publisher.py`
- Modify: `tests/test_daily_report_publish.py`

**Interfaces:**
- Produces: `publish_report(..., archive_dir: Path | None = None) -> Path`
- Produces: `<archive_dir>/stock-papi-tw-industry-daily-YYYY-MM-DD.pdf` 與同 basename `.json`。

- [ ] **Step 1: Write failing mirror tests**

```python
latest_path = publish_report(root, report, result)
mirror = root / "reports" / "TW" / "stock-papi-tw-industry-daily-2026-07-03.pdf"
self.assertEqual(mirror.read_bytes(), pdf.read_bytes())
self.assertEqual(json.loads(mirror.with_suffix(".json").read_text()), metadata)
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `python -m unittest tests.test_daily_report_publish -v`

Expected: FAIL because mirror and sidecar do not exist.

- [ ] **Step 3: Add minimum atomic mirror writer**

```python
archive = archive_dir or Path(root) / "reports" / report.source.manifest.market
mirror_pdf = archive / f"stock-papi-tw-industry-daily-{report.report_date}.pdf"
mirror_json = mirror_pdf.with_suffix(".json")
```

Write the verified PDF bytes and canonical metadata bytes after `latest-TW.json` succeeds. If the existing mirror PDF hash equals `result.sha256` and the sidecar describes the same hash, leave both unchanged.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest tests.test_daily_report_publish -v`

Expected: PASS.

### Task 2: CLI permanent default and staging cleanup

**Files:**
- Modify: `reporting/cli.py`
- Modify: `tests/test_daily_report_cli.py`

**Interfaces:**
- Consumes: CLI `--root`, optional `--output-dir`.
- Produces: final status `pdf_path` pointing to the human-readable mirror.

- [ ] **Step 1: Write failing CLI test**

```python
self.assertEqual(status["pdf_path"], str(root / "reports" / "TW" / filename))
self.assertFalse((root / "reports" / "TW" / ".staging" / filename).exists())
```

- [ ] **Step 2: Run focused test to verify RED**

Run: `python -m unittest tests.test_daily_report_cli -v`

Expected: FAIL because the CLI uses `cache/reports` and reports the immutable object path.

- [ ] **Step 3: Generate in a hidden archive staging directory**

```python
archive_dir = args.output_dir or root / "reports" / args.market
staged_pdf = archive_dir / ".staging" / filename
latest_path = publish_report(root, report, generation, config, archive_dir=archive_dir)
generation.output_path.unlink(missing_ok=True)
```

Do not delete a staged PDF until `publish_report` returns; only the generation artifact is removed, never the final mirror.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest tests.test_daily_report_cli tests.test_daily_report_publish -v`

Expected: PASS.

### Task 3: Fixed SAMPLE PDF and isolated web download

**Files:**
- Modify: `reporting/pdf_generator.py`
- Modify: `scripts/generate_sample_daily_report.py`
- Create: `static/samples/stock-papi-tw-industry-daily-SAMPLE.pdf`
- Modify: `app.py`
- Modify: `templates/reports.html`
- Modify: `tests/test_daily_report_pdf.py`
- Modify: `tests/test_report_web.py`

**Interfaces:**
- Produces: `GET /reports/sample/download` attachment response.
- Produces: a static PDF containing all three required SAMPLE labels.

- [ ] **Step 1: Write failing PDF and route tests**

```python
download = client.get("/reports/sample/download")
self.assertEqual(download.status_code, 200)
self.assertEqual(download.mimetype, "application/pdf")
self.assertIn("attachment", download.headers["Content-Disposition"])
self.assertIn(b"%PDF", download.data[:8])
```

Verify extracted PDF text contains `SAMPLE / TEST DATA`、`不得正式發布`、`不得作為正式投資或模型結果` and patch `_gcs_get_report_object` to fail if called.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `python -m unittest tests.test_daily_report_pdf tests.test_report_web -v`

Expected: FAIL because the fixed route and required SAMPLE labels do not exist.

- [ ] **Step 3: Implement fixed static response and separated page card**

```python
SAMPLE_REPORT_PATH = BASE_DIR / "static" / "samples" / "stock-papi-tw-industry-daily-SAMPLE.pdf"
@app.route("/reports/sample/download")
def sample_report_download():
    return _fixed_sample_pdf_response()
```

Keep this response independent of `_published_report_index` and GCS. Add explicit SAMPLE copy to the template. Add the two missing PDF labels, then generate the single static asset with `scripts/generate_sample_daily_report.py`.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest tests.test_daily_report_pdf tests.test_report_web -v`

Expected: PASS.

### Task 4: Final verification

**Files:**
- Verify: all changed files

- [ ] **Step 1: Verify sample artifact**

Run: `python scripts/generate_sample_daily_report.py --font-path C:\\Windows\\Fonts\\NotoSansTC-VF.ttf --font-bold-path C:\\Windows\\Fonts\\NotoSansTC-VF.ttf --title-font-path C:\\Windows\\Fonts\\NotoSerifTC-VF.ttf --output static/samples/stock-papi-tw-industry-daily-SAMPLE.pdf`

Expected: JSON with `sample: true` and a PDF path under `static/samples`.

- [ ] **Step 2: Run complete verification**

Run: `python -m unittest discover -s tests -v`; `python -m compileall -q reporting scripts tests`; `git diff --check`.

Expected: all tests pass and all commands exit 0.
