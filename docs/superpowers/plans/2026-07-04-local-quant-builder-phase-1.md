# Local Quant Builder Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立只使用 `D:\StockPapiData` 的本地量化執行根目錄、台北時間 05:30–09:30 時間限制、單一實例 lock、原子 checkpoint 與 Windows Task Scheduler 排程。

**Architecture:** 新增一個只依賴 Python 標準函式庫的 `local_quant.py`，負責路徑、時間、磁碟、lock 與 checkpoint。PowerShell 安裝腳本只處理 D 槽 NTFS／空間／ACL 與排程器，不下載資料或保存 API 密鑰。Phase 1 的排程只執行 dry-run 狀態檢查，後續資料階段再掛入工作函式。

**Tech Stack:** Python 3.10 standard library、PowerShell ScheduledTasks、NTFS ACL、unittest。

---

### Task 1: 時間窗與 D 槽路徑守門

**Files:**
- Create: `local_quant.py`
- Create: `tests/test_local_quant.py`

- [ ] **Step 1: 寫失敗測試**

測試必須驗證：C 槽被拒絕、D 槽可接受、05:30–09:20 可領工作、09:20–09:25 只能 drain、09:25–09:30 只能 checkpoint，其餘時段 closed。

```python
class LocalQuantTests(unittest.TestCase):
    def test_data_root_must_be_on_d_drive(self):
        self.assertEqual(validate_data_root(Path("D:/StockPapiData")), Path("D:/StockPapiData"))
        with self.assertRaises(ValueError):
            validate_data_root(Path("C:/StockPapiData"))

    def test_window_phases(self):
        self.assertEqual(window_phase(at(5, 30)), "run")
        self.assertEqual(window_phase(at(9, 20)), "drain")
        self.assertEqual(window_phase(at(9, 25)), "checkpoint")
        self.assertEqual(window_phase(at(9, 30)), "closed")
```

- [ ] **Step 2: 執行 RED 測試**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path '.deps').Path
& 'C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_local_quant -v
```

Expected: `ModuleNotFoundError: No module named 'local_quant'`。

- [ ] **Step 3: 實作最小守門函式**

`local_quant.py` 使用固定 UTC+8，不依賴 Windows IANA timezone database：

```python
TAIPEI = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")
RUN_START = datetime.time(5, 30)
DRAIN_START = datetime.time(9, 20)
CHECKPOINT_START = datetime.time(9, 25)
RUN_END = datetime.time(9, 30)

def validate_data_root(path):
    path = Path(path).expanduser()
    if path.drive.upper() != "D:" or path.name != "StockPapiData":
        raise ValueError("data root must be D:\\StockPapiData")
    return path

def window_phase(now=None):
    current = (now or datetime.datetime.now(TAIPEI)).astimezone(TAIPEI).time()
    if RUN_START <= current < DRAIN_START:
        return "run"
    if DRAIN_START <= current < CHECKPOINT_START:
        return "drain"
    if CHECKPOINT_START <= current < RUN_END:
        return "checkpoint"
    return "closed"
```

- [ ] **Step 4: 執行 GREEN 測試**

Expected: 2 tests pass。

- [ ] **Step 5: Commit**

```powershell
git add -- local_quant.py tests/test_local_quant.py
git commit -m "feat: add local quant safety guards"
```

### Task 2: 目錄、磁碟門檻、lock 與 checkpoint

**Files:**
- Modify: `local_quant.py`
- Modify: `tests/test_local_quant.py`
- Modify: `.gitignore`
- Modify: `.dockerignore`

- [ ] **Step 1: 寫失敗測試**

使用 `TemporaryDirectory` 模擬 D 槽內部檔案行為，測試：固定目錄清單、低空間拒絕、第二把 lock 失敗、前一天 lock 可封存、checkpoint 使用 JSON 原子取代。

```python
def test_lock_is_single_instance_and_old_lock_is_archived(self):
    first = acquire_lock(root, now=at(5, 30))
    with self.assertRaises(RuntimeError):
        acquire_lock(root, now=at(5, 31))
    first.release()

def test_checkpoint_round_trip(self):
    save_checkpoint(root, {"stage": "prices", "symbol": "2330"})
    self.assertEqual(load_checkpoint(root)["symbol"], "2330")
```

- [ ] **Step 2: 執行 RED 測試**

Expected: missing `ensure_layout`、`acquire_lock`、`save_checkpoint`。

- [ ] **Step 3: 實作標準函式庫版本**

建立 `raw`、`cache`、`checkpoints`、`artifacts`、`publish`、`logs`、`secrets`。lock 使用 `os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)`；checkpoint 先寫同目錄暫存檔、`flush()`、`os.fsync()` 後 `os.replace()`。磁碟空間使用 `shutil.disk_usage()`，預設至少保留 100GB。

`.gitignore` 與 `.dockerignore` 新增：

```text
.local-quant/
local-quant-data/
*.checkpoint.tmp
```

實際 D 槽資料位於 repo 外，這些規則防止測試或誤設路徑時被提交或建置。

- [ ] **Step 4: 執行 GREEN 與現有完整測試**

Run:

```powershell
& $python -m unittest tests.test_local_quant -v
& $python -m unittest discover -s tests -v
```

Expected: 新測試及既有 175 tests 全部通過。

- [ ] **Step 5: Commit**

```powershell
git add -- local_quant.py tests/test_local_quant.py .gitignore .dockerignore
git commit -m "feat: add local quant checkpoints"
```

### Task 3: 安全 CLI 與 D 槽初始化

**Files:**
- Modify: `local_quant.py`
- Modify: `tests/test_local_quant.py`

- [ ] **Step 1: 寫 CLI 失敗測試**

測試 `--init` 可建立 layout；`--dry-run` 在時段外只回報 closed 且不執行工作；路徑錯誤、低空間或有效 lock 回傳非零。

- [ ] **Step 2: 執行 RED 測試**

Expected: missing `main`。

- [ ] **Step 3: 實作 argparse CLI**

```python
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"D:\StockPapiData")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-free-gb", type=float, default=100.0)
    args = parser.parse_args(argv)
```

Phase 1 不加入市場工作；合法 dry-run 只寫入 `logs/runner-status.json` 與 checkpoint。時段外正常退出，不建立工作 lock。

- [ ] **Step 4: 執行測試與實際 D 槽初始化**

Run:

```powershell
& $python local_quant.py --root 'D:\StockPapiData' --init --dry-run
```

Expected: 顯示 NTFS 路徑、剩餘空間與目前 phase；D 槽建立七個目錄，C 槽不產生資料檔。

- [ ] **Step 5: Commit**

```powershell
git add -- local_quant.py tests/test_local_quant.py
git commit -m "feat: add local quant command"
```

### Task 4: Windows Task Scheduler 與 ACL

**Files:**
- Create: `scripts/install_local_quant_task.ps1`
- Create: `tests/test_local_quant_task.py`
- Modify: `README.md`

- [ ] **Step 1: 寫靜態安全測試**

測試腳本必須包含 `05:30`、四小時限制、`IgnoreNew`、`StartWhenAvailable:$false`、Below Normal priority、D 槽 NTFS／100GB 檢查，且不得包含 API key、password、service-account JSON 或 `0.26.0`。

- [ ] **Step 2: 執行 RED 測試**

Expected: installer file missing。

- [ ] **Step 3: 實作 PowerShell 安裝腳本**

腳本：

1. 驗證 D 槽 Ready、NTFS、剩餘至少 100GB。
2. 呼叫 `local_quant.py --init --dry-run`。
3. 只對新建的 `D:\StockPapiData` 設定目前使用者與 SYSTEM FullControl，移除一般繼承。
4. 建立每日 05:30、最長 PT4H、單一實例、錯過不補跑、Below Normal、AC power 的 current-user task。
5. `-WhatIf` 只顯示設定，不改 ACL 或排程。

- [ ] **Step 4: 執行靜態測試、WhatIf 與正式安裝**

Run:

```powershell
& $python -m unittest tests.test_local_quant_task -v
& .\scripts\install_local_quant_task.ps1 -WhatIf
& .\scripts\install_local_quant_task.ps1
```

Expected: task `StockPapi-LocalQuant` Ready；下一次執行為 05:30；Action 指向 repo 的 `local_quant.py`，資料 root 為 D 槽。

- [ ] **Step 5: Commit**

```powershell
git add -- scripts/install_local_quant_task.ps1 tests/test_local_quant_task.py README.md
git commit -m "feat: schedule local quant runner"
```

### Task 5: 安全與交付驗證

**Files:**
- Modify only if verification reveals a defect.

- [ ] **Step 1: 執行完整測試與語法檢查**

```powershell
& $python -m unittest discover -s tests -v
& $python -m py_compile local_quant.py
git diff --check
```

- [ ] **Step 2: 執行 ShellWard 與人工秘密掃描**

```powershell
shellward scan --ci .
rg -n "BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|api[_-]?key\s*=|secret\s*=|Bearer [A-Za-z0-9]" --glob '!0.26.0' .
```

已知 `FINMIND_PASSWORD = os.getenv("FINMIND_PASSWORD")` 可能被 ShellWard 誤判；必須檢查內容，不得只看分數。

- [ ] **Step 3: 驗證 D 與 C 寫入範圍**

確認 D 槽有 layout、ACL 只有目前使用者與 SYSTEM；repo 只新增程式與測試，沒有 raw/cache/checkpoint/artifact。確認 `0.26.0` 仍未追蹤。

- [ ] **Step 4: 驗證排程設定**

讀取 Task Scheduler XML，確認 05:30、PT4H、IgnoreNew、StartWhenAvailable=false 與正確 action。手動在時段外執行 task 時，runner 應正常回報 closed 且不啟動高負載工作。

- [ ] **Step 5: Push**

完整驗證後推送 `main`。Phase 1 不部署 Cloud Run，因為尚未修改線上讀取流程。
