# Stock-Papi `app.py` 漸進式模組化設計

## 現況與基線

- `app.py`：4,153 行；同時承擔 Flask、LINE、量化、GCS、新聞、情緒、Flex、報告與 Web route。
- Flask route：19 條非 static URL rule；既有 endpoint 名稱、method 與 `Gunicorn app:app` 均是公開契約。
- 既有測試直接 `import app as stock_app`，並 patch module global、cache、HTTP client 與 handler；相容門面不能一次移除。
- 搬移前基線：345/345 `unittest` 通過；後續新增測試使目前 suite 為 358 項。
- 基線的同步 ADC／Firestore token 預熱已在 app factory 階段移除；本機 `import app` 由約 12.5 秒降至約 0.5 秒。

## 目標

1. 根目錄 `app.py` 最終只保留 `create_app()` 組裝與明確 compatibility exports。
2. Web、LINE、service、repository、quant 與 shared 的依賴單向，核心模組不反向 import `app.py`。
3. 保持 URL、endpoint、HTTP status、template context、Flex payload、LINE command、GCS fail-closed 與模型數值行為。
4. 不讓 package `__init__.py` 或 route import 觸發分析／PDF／模型重載。
5. 每個 phase 可獨立回滾；每個 production move 都有先行 regression test。

## 非目標

- 不改 LightGBM、特徵、五日目標、成本、門檻、回測或 publication protocol。
- 不取消即時計算 fallback；它是否違反 Cloud Run 重運算邊界是獨立產品決策。
- 不全面拆分 `local_quant.py`、不改 UI、沒有 DI framework、沒有 Blueprint namespace migration。
- 不修改 GCS manifest／schema、immutable object 或 latest 指標流程。

## 方案比較與決定

| 方案 | 優點 | 風險 | 決定 |
| --- | --- | --- | --- |
| 直接先建 app factory／Blueprint | 表面檔案最少 | endpoint 與 module-global test mock 一次破壞 | 不採用 |
| 先純搬移、保留 singleton，再導入 runtime／factory | 每一步小、可回滾、可維持 exports | 過渡期有 compatibility layer | 採用 |
| 新增泛用 DI／service locator | 抽象完整 | 引入不需要的 lifecycle 與隱性依賴 | 不採用 |

## 依賴方向與模組邊界

```text
web routes / LINE webhook
        ↓
services
        ↓
repositories / integrations / quant
        ↓
shared
```

- `web` 只處理 request、validation、status、template／response。
- `services` 編排既有資料與 pure 函式，但不 import Flask app。
- `repositories` 是 GCS／已發布 snapshot／report trust boundary；不能回傳未驗證 payload。
- `integrations.line` 只處理 SDK adapter、command、handler、Flex presentation。
- `quant` 是 lazy pure-analysis stack；不能 import Flask、LINE 或 templates。
- `shared` 僅含無副作用格式化、validation、exception、日期與小型 typing。

## Runtime、cache 與 cold-start

初始 phase 不改變以下 canonical owner，只將讀寫者逐步改成透過明確參數取得：

| 狀態 | 目前 owner | 最終 owner |
| --- | --- | --- |
| LINE client／handler／store | `app.py` module globals | `AppRuntime` |
| system analysis cache | `_SYSTEM_CACHE` | `ApplicationCaches.system_analysis` |
| Yahoo cache | `_YFINANCE_CACHE` | `ApplicationCaches.yfinance` |
| quant manifest cache | `_QUANT_MANIFEST_CACHE` | `ApplicationCaches.quant_manifest` |
| market insights cache | `_MARKET_INSIGHTS_CACHE` | `ApplicationCaches.market_insights` |
| FinMind token／backoff | module globals | `AppRuntime` |

重型 import 仍只允許在執行路徑：pandas／numpy lazy module，sklearn／LightGBM 在模型函式，Gemini 在首次生成，PDF stack 僅在 `reporting`。`create_app()` 不得讀完整 snapshot、訓練模型、生成 PDF 或下載行情。

## Compatibility 策略

- 最終 root `app.py` 保持 `app = create_app()`，因此 Gunicorn `app:app` 不變。
- 現階段使用 module identity facade 保留既有 root patch 語意；待 route／handler 改成顯式 dependency 後，再收斂成少量顯式 exports，禁止 `import *`。
- 在 `stock_app.<symbol>` test mock 全數遷移前，保留相容 export；新 production module 不得反向 import root `app.py`。
- Route 拆檔先使用 registration function 與原 endpoint name；不使用會改變名稱的 Blueprint。

## Symbol inventory（搬移前）

| symbol | current_file | responsibility | callers | dependencies | related_tests | is_heavy | has_side_effects | target_module | migration_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| settings、limits、model feature constants | `app.py:180-312` | settings／quant constants | 全 app | env、stdlib | prediction、web | 否 | env read | `settings.py`、`quant/constants.py` | 1、8 |
| `redact_secrets`、formatter helpers | `app.py:45-141` | logging sanitation | app、line state | re、logging | line／security tests | 否 | logger mutation | `shared/logging.py` | 1 |
| `_safe_float`、`_clamp`、ticker helpers | `app.py:412-437,2077-2088` | pure validation／formatting | web、LINE、analysis | stdlib | prediction／web | 否 | 否 | `shared/validation.py`、`shared/formatting.py` | 1 |
| `_gcs_get_allowed_object`、quant snapshot readers | `app.py:438-681` | verified artifact reader | analysis、reports | requests、gzip、hash | prediction／report web | 否 | HTTP | `repositories/gcs.py`、`repositories/quant_snapshots.py` | 4 |
| market／option／chip data helpers | `app.py:682-1019` | data normalisation | `get_data`、quant | lazy pandas、providers | prediction | 是 | HTTP | `quant/data.py` | 8 |
| `calc_all`、target、splits、engine、projection | `app.py:1270-1463,905-932` | quant core | analysis／LINE | pandas、sklearn、LightGBM | prediction | 是 | model fit | `quant/*` | 8 |
| news provider parsers／sentiment | `app.py:1020-1249,1502-1713` | external news／pure scoring | analysis | requests、XML | prediction | 否 | HTTP (provider) | `integrations/news`、`services/sentiment.py` | 6 |
| `analyze`、`_do_analyze` | `app.py:1714-1817` | stock orchestration | routes、LINE | snapshot、quant、news | prediction／line／web | 是 | cache／fallback | `services/stock_analysis.py` | 7 |
| dashboard／market payload builders | `app.py:1818-1904,3604-3635` | service orchestration | dashboard routes | analysis／cache | web product | 是 | cache | `services/dashboard.py`、`services/market.py` | 5 |
| Papi／sector helpers | `app.py:2089-2566` | LINE analysis support | message handler | requests、Gemini、analysis | line flow | 是 | HTTP／Gemini | `services/papi.py`、`services/sectors.py` | 5、9 |
| Flex builders | `app.py:2637-3469` | LINE presentation | handlers／tests | LINE model JSON | line flow／web product | 否 | 否 | `integrations/line/flex.py` | 2 |
| report readers／routes | `app.py:3510-3569` | verified report presentation | Web | reporting.web、GCS | report web | 否 | HTTP via reader | `repositories/report_store.py`、`services/reports.py`、`web/routes/reports.py` | 3 |
| dashboard／market／stock routes | `app.py:3470-3718` | HTTP adapters | browser／tests | Flask／services | web product | 否 | request | `web/routes/*.py` | 5、7、10 |
| webhook／command／notification handlers | `app.py:3721-4153` | LINE adapter | LINE SDK | state、services、Flex | line flow | 否 | API send | `integrations/line/*.py` | 9 |

## Migration phases

0. Baseline, route inventory and caller inventory.
1. `shared` pure settings／formatting／validation with compatibility exports.
2. LINE Flex builders with structural equality fixtures.
3. Report store, service and route adapter.
4. GCS transport plus verified quant／market-insight repositories.
5. Dashboard／market services and route adapters.
6. News provider and pure sentiment service with golden dict fixtures.
7. Stock-analysis orchestration and stock routes.
8. Quant core last, with deterministic metric regression.
9. LINE webhook／commands／handlers／notifications.
10. Per-app runtime, app factory and explicit route registration.

## Testing、rollback 與完成條件

- 新增 route inventory（URL、endpoint、methods）、compatibility export、Flex equality、GCS rejection、sentiment golden、quant regression、cache owner、multi-app isolation、cold-start tests。
- 每 phase：focused test → full `unittest` → compilation → JS check → cold import → `git diff --check` → commit。
- 任一 phase failure 只修正該 phase；不繼續堆疊搬移。
- 每次 commit 是可單獨 revert 的語意單位；不含 generated PDF、font、snapshot 或全 repo formatting。

## 2026-07-13 完成狀態

- 根目錄 `app.py` 由 4,153 行降為 17 行，保留 Gunicorn `app:app` 與 module-identity compatibility facade。
- routes 已移至 `web/routes/`，並由 `web/route_registration.py` 集中註冊；inventory 為 20 條公開 rule，URL、endpoint 與 methods 均由 regression test 固定。
- reports、GCS、quant snapshots、market insights、news、sentiment、market、dashboard、stock analysis 與 quant 核心已有各自 repository／integration／service／quant 邊界。
- LINE Flex、notifications、webhook routes、message 與 postback handlers 已移出 compatibility module；handler 透過明確 dependency mapping 協調舊 patch points。
- `create_app()` 每次建立新的 Flask instance，config 與 URL map 不共用；process-level data caches 仍刻意共享，以保留既有 TTL 與 fallback semantics。
- `application.py` 已縮為 process runtime 組裝、route／handler dependency mapping 與舊測試仍 patch 的薄 compatibility wrappers；Papi、news、market providers、LINE state／presentation 與 payload 實作均已移至各自模組。新 production code 不得再往 compatibility layer 新增業務邏輯。
- quant `uncompressed_size`、SHA-256、compressed size、path allowlist 與 schema 驗證均保留在 repository fail-closed 路徑。
- 目前 Windows App Control 封鎖 worktree／新安裝 NumPy、SciPy 的 `.pyd`，且既有 `.deps` 未含 matplotlib；最終本機結果為 355/358。三項未通過均為科學運算／PDF binary dependency，focused Web、LINE、repository、factory、route 與 cold-start 回歸均通過。

## `local_quant.py` 後續設計

本次不拆 `local_quant.py`。下一輪應獨立規劃 `local_pipeline/cli.py`、`runner.py`、`checkpoint.py`、`artifacts.py`、`manifest.py`、`publisher.py`、`retention.py` 與 `status.py`。拆分順序應從純 artifact／manifest schema 開始，再搬 checkpoint 與 publisher；每一步固定 immutable object、atomic latest、排程時間、失敗保留上一版與刪除路徑限制，不與模型公式修改同時進行。
