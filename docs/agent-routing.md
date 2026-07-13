# Stock-Papi 多模型 Agent 路由

## 已驗證的 Codex 能力

驗證日期：2026-07-11。Codex CLI 為 `0.141.0`。

- Codex 官方 schema 支援 project-scoped `.codex/config.toml` 與 `.codex/agents/*.toml`，以及自訂 Agent 的 `name`、`description`、`developer_instructions`、`model`、`model_reasoning_effort` 與 `sandbox_mode`。
- 官方 schema 支援 `[agents] max_threads` 與 `max_depth`，以及 `read-only`／`workspace-write` sandbox。本專案設定為 4 條執行緒、深度 1。父 Agent 的即時權限仍會重新套用到子 Agent；需要硬性唯讀時，Terra 的父回合也必須選擇唯讀權限。
- Codex 已實際將根目錄 `AGENTS.md` 注入 model-visible prompt。`.codex/` 的 runtime 載入仍取決於專案信任狀態與可啟動的 Codex runtime。

## 模型識別結果

| 名稱 | 狀態 | 設定方式 |
| --- | --- | --- |
| Terra | 已確認：`gpt-5.6-terra` | 維持使用者目前的全域主模型，不在專案設定覆寫。 |
| Luna | 已確認：`gpt-5.6-luna` | 由本機 `models_cache.json` 驗證，已寫入兩個 `luna_*` Agent 檔。 |
| Sol | 已確認：`gpt-5.6-sol` | 由本機 `models_cache.json` 驗證，已寫入 `sol_deep` Agent 檔。 |

三個自訂 Agent 已使用本機 model catalog 驗證的 `model` 值。角色、reasoning effort、sandbox 與委派政策已寫入並通過靜態 TOML 解析；Luna／Sol 的不同模型 runtime 是否實際套用仍待驗證，且未宣稱已完成。

## 角色與權限

| Agent | 有效模型 | Reasoning | Sandbox | 用途 |
| --- | --- | --- | --- | --- |
| Terra | `gpt-5.6-terra` | 使用者既有 `xhigh` | 父回合設定 | 唯一主協調、整合、最終驗證。 |
| `luna_explorer` | `gpt-5.6-luna` | `low` | `read-only` | 精確搜尋與唯讀探索。 |
| `luna_worker` | `gpt-5.6-luna` | `medium` | `workspace-write` | 已核准的狹窄低風險修改。 |
| `sol_deep` | `gpt-5.6-sol` | `high` | `read-only` | 高風險、深度與跨模組審查。 |

## 使用方式

- 直接要求 Terra「使用 `luna_explorer` 找出 app.py 的所有 routes 與對應測試」即可進行唯讀探索。
- 直接要求 Terra「使用 `sol_deep` 分析 Blueprint 與 service modules 的循環依賴和 cold-start 風險；不要修改檔案」即可進行高風險審查。
- 寫入前先要求 Terra 決定範圍。只有低風險、已核准且不重疊的修改才交由 `luna_worker`；高風險寫入維持由 Terra 完成。

不需要手動編輯現有設定。若未來 Codex 的 model catalog 顯示已驗證的 Luna／Sol model ID，再由 Terra 將該精確 ID 寫入對應 Agent 檔的 `model` 欄位，並重跑本文件的三個路由驗證。

## 已知限制

- `max_threads` 限制同時開啟的 Agent 執行緒，但不提供跨 Agent 檔案鎖；單一 write Agent 規則由 Terra 與 `AGENTS.md` 強制。
- Agent 檔中的 sandbox 是預設值。父回合的即時權限可覆蓋它，因此敏感審查回合應以唯讀父權限啟動。
- 本機 CLI `0.141.0` 的 project config runtime 驗證尚未完成：實際啟動 `gpt-5.6-terra` 回合時先收到 HTTP 400，指出此模型需要較新的 Codex。`codex doctor` 顯示可升級版本；升級會影響全機 Codex，因此本次未自行執行。`--help` 不視為 project config 載入驗證。完成升級後，必須重跑三個 CLI 路由測試，才能驗證 runtime 層的 custom-agent 選用與 sandbox。
