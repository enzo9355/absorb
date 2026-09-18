# ABSORB 安全評估與 hardening（2026-09-18）

- **標的**：ABSORB — LINE Bot + Flask Web（Cloud Run 唯讀讀取已驗證 artifacts）
- **方法**：白箱原始碼審計（read-only），涵蓋 Web 對外攻擊面、認證/授權、LINE Webhook、自然語言/工具層、儲存層、部署設定
- **範圍聲明**：受測系統為擁有者本人資產（authorized security testing）。審計期間未對線上 production 發送任何流量。

## 總評

程式庫的安全防護水準高。審計**未發現可直接利用的 Critical / High 漏洞**（無 RCE、SQLi、路徑穿越、認證繞過、SSRF、IDOR）。以下為 Medium 以下的 hardening / 縱深防禦項目，其中多數已在同一分支修補。

## Findings 與狀態

| # | 嚴重度 | 標題 | 狀態 |
|---|--------|------|------|
| 1 | Medium | `/api/conversation`（接 LLM）無應用層速率限制 | ✅ 已修補（每 IP 30 req/60s，per-instance） |
| 2 | Medium | Gunicorn `--timeout 0` + 單 worker/8 threads | ✅ 已修補（`--timeout 120 --graceful-timeout 30`） |
| 3 | Low | 廣播端點以 GET query string 傳 token | ✅ 已修補（改收 `Authorization: Bearer`；保留 query 為過渡相容，見下方 ops note） |
| 4 | Low | 容器以 root 執行 | ✅ 已修補（新增非 root `appuser`，`USER appuser`） |
| 5 | Low | `requirements.txt` 核心相依未鎖版本 | ✅ 已修補（top-level 全部 `==` 鎖版本 + `pip-audit` CVE 掃描 + Dependabot 週更） |
| 6 | Low | 缺少 HSTS 標頭 | ✅ 已修補（`Strict-Transport-Security: max-age=63072000; includeSubDomains`） |
| 7 | Info | `.env.example` 預設 `AUTH_COOKIE_SECURE=false` | ✅ 已修補（改為 true，並加註本機例外） |
| 8 | Info | unpkg 第三方腳本 | 保留（已用 SRI + CSP 緩解；可選自我 host） |

## 本次已在此分支套用的修補

| Finding | 檔案 | 變更 |
|---------|------|------|
| 1 | `absorb/conversation/web.py` | 新增 per-IP 記憶體型速率限制（30 req/60s，超過回 `429 + Retry-After`）。 |
| 2 | `Dockerfile` | `--timeout 0` → `--timeout 120 --graceful-timeout 30`。 |
| 3 | `stock_papi/integrations/line/webhook.py` | 廣播改優先接受 `Authorization: Bearer <token>` header；`?token=` 保留為過渡相容。 |
| 4 | `Dockerfile` | 建立 `appuser`（uid 10001），`COPY --chown`，`USER appuser`。 |
| 5 | `requirements.txt` / `requirements-dev.txt` / `.github/workflows/ci.yml` / `.github/dependabot.yml` | top-level 相依全部鎖為 `==`（在 py3.10 與 py3.11 各跑 1527 tests 驗證；`pypdf` 依既有守門測試維持 `>=5,<7`）；新增 `pip-audit`（CI advisory job，不擋 deploy）與 Dependabot 週更。 |
| 6 | `stock_papi/web/app_factory.py` | `security_headers` 新增 HSTS（不含 `preload`）。 |
| 7 | `.env.example` | `AUTH_COOKIE_SECURE=true`（本機開發才設 false）。 |

## ⚠️ 上線前必做的 Ops 步驟（Finding 3）

程式已優先採用 `Authorization` header，但 query 參數仍相容。要**完全消除** token 出現在 URL/log 的風險，請更新呼叫 `/broadcast_weekly` 的 **Cloud Scheduler** 工作：

- 移除 URL 上的 `?token=...`
- 改在 request header 加：`Authorization: Bearer <BROADCAST_TOKEN>`
- （`/tasks/check-alerts`、`/tasks/refresh-sector-signals` 早已使用此 header 形式，可對照。）

完成排程遷移後，可移除 `webhook.py` 中 `_broadcast_authorized` 的 query fallback 分支。

## 後續建議

### 需在 GCP 端做（程式無法代勞，建議用 Cloud Armor 一次解決）

限流的「跨實例」與「真實 client IP」兩個問題，正確的解法都在**邊界**，而不是在應用碼裡猜代理拓撲（猜錯會讓限流被 IP 偽造繞過，或誤傷同一 NAT 後的正常使用者）。建議在 Cloud Run 前面掛 **Cloud Armor** rate-limit policy：

- `rate_limit_options`：例如 `count=60, interval_sec=60`，`enforce_on_key=IP`（Cloud Armor 由可信邊界判定 client IP，天然免疫 XFF 偽造）。
- 對 `/api/conversation`、`/broadcast_weekly`、`/tasks/*` 套用；超限回 429。
- 這同時取代目前應用層 per-instance 限流的「跨實例」缺口；應用層限流保留為第二層防護即可。
- 若不用 Cloud Armor 而要在應用層以真實 IP 限流，必須依實際代理跳數設定 `ProxyFix(x_for=n)`，否則 `request.remote_addr` 不是真正的 client IP。

### 相依套件

- `pip-audit` 已在 CI 掃描；首次掃描即發現 `setuptools`（基底映像自帶、非宣告相依）有 `PYSEC-2026-3447`，修復版 `>=83.0.0`。建議在部署基底層升級 setuptools，或於映像建置後 `pip install -U 'setuptools>=83'`。
- 若日後要更嚴格的可重現建置，可再進一步用 pip-tools/uv 產生含 hash 的完整 transitive lock，CI 以 `--require-hashes` 安裝（本次未做，因跨 py3.10/3.11 與 slim 映像的 hash 鎖較脆弱，須另行驗證）。

## 已確認正確的既有防護（節錄）

- LINE Login：PKCE(S256) + `state` HMAC cookie + `nonce` + callback 重新驗證 OIDC claims。
- Session/CSRF：HMAC opaque token、登入輪替 session、double-submit CSRF、全面 `hmac.compare_digest`。
- 報告載入：content-addressed（`sha256==expected` 且路徑須等於 `objects/canonical/{sha}.json`），fail-closed。
- 工具層：分級權限 + symbol allow-list + 每工具 timeout + 結果大小上限 + prompt-injection 過濾 + 數字 grounded 檢查。
- GCS/Firestore：前綴 allow-list + `quote(safe='')`；user_id 來自已驗證 session（`U[0-9a-f]{32}`）。
- Log 秘密遮蔽；Jinja 自動跳脫 + `|tojson` + 嚴格 CSP。
