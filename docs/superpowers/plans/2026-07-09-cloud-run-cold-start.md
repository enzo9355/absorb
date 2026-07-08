# Cloud Run Cold Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion.

**Goal:** 保留全部既有服務行為，縮短 LINE webhook 冷啟動。

**Architecture:** 重型分析套件改為執行時載入；既有 LINE 狀態流程不變；建置工具不進入最終映像。

**Tech Stack:** Python 3.10、Flask、Gunicorn、Cloud Run、unittest。

## Global Constraints

- 不新增依賴，不更換模型，不改 API、路由、訊息或資料結果。
- 保留 1 GiB、scale-to-zero、1 worker 與 8 threads。
- 所有正式流量切換前必須通過測試與 webhook 驗證。

### Task 1: 鎖定延遲載入與狀態讀取行為

**Files:**
- Create: `tests/test_cold_start.py`

- [ ] 新增子行程測試，確認單純 `import app` 不載入 Pandas、NumPy、sklearn、LightGBM、Gemini。
- [ ] 執行測試並確認因現行立即載入而失敗。

### Task 2: 最小化啟動路徑

**Files:**
- Modify: `app.py`

- [ ] 使用標準庫延遲載入 Pandas、NumPy 與 Gemini。
- [ ] 將 sklearn、LightGBM 匯入移入實際使用函式。
- [ ] 執行新增測試與完整測試。

### Task 3: 縮小執行映像並驗證部署

**Files:**
- Modify: `Dockerfile`

- [ ] 確保編譯工具只存在於建置階段。
- [ ] 建置、部署新修訂版並確認 100% 流量。
- [ ] 讓服務 scale-to-zero，再測量冷啟動與 LINE 官方 webhook。
- [ ] 若驗證失敗，停止切換或回復上一修訂版。
