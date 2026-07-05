# Local Quant Full Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓每日排程持續處理台股 universe，直到完成或 09:20 停止，而不是固定 200 筆後提早結束。

**Architecture:** 保留現有 Python 時間守門與 checkpoint，只調整受控 PowerShell wrapper 的明確上限。CLI 預設與批次介面不變。

**Tech Stack:** PowerShell、Python unittest。

---

### Task 1: 調整排程工作上限

**Files:**
- Modify: `tests/test_local_quant_task.py`
- Modify: `scripts/run_local_quant_task.ps1`
- Modify: `README.md`

- [ ] 先將 wrapper 靜態測試預期改為 `5000`，並明確拒絕 `--limit 200`。
- [ ] 執行 `python -m unittest tests.test_local_quant_task -v`，確認測試因 wrapper 仍為 200 而失敗。
- [ ] 將 wrapper 改為 `--limit 5000`，README 改為「持續至完成或 09:20」。
- [ ] 執行完整測試、PowerShell parse 與 `git diff --check`。
- [ ] 提交、推送，並唯讀確認排程下次執行時間仍為 05:30。
