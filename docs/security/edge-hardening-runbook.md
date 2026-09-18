# 邊界強化 Runbook（GCP 端操作）

程式端的修補已完成並合併在 security hardening 分支；這份 runbook 收錄**只能在 GCP 端執行**的步驟。
對應 [`assessment-2026-09-18.md`](assessment-2026-09-18.md) 的 Finding 1、3。

專案座標（取自 `.github/workflows/deploy.yml`）：

| 項目 | 值 |
| --- | --- |
| `GCP_PROJECT` | `line-stock-bot-498908` |
| `CLOUD_RUN_SERVICE` | `line-stock-bot` |
| `CLOUD_RUN_REGION` | `asia-east1` |

---

## 1.（必做，5 分鐘）Cloud Scheduler 廣播工作改用 Authorization header

**為什麼**：舊寫法把 token 放在 URL query（`?token=...`），會留在 access log、proxy log 與 Referer。
程式已優先接受 `Authorization: Bearer`，並暫時保留 query 相容，所以**現在改不會斷線**。

先找出工作名稱：

```bash
gcloud scheduler jobs list --location=asia-east1 --project=line-stock-bot-498908
```

改成 header（把 `<JOB_NAME>`、`<BROADCAST_TOKEN>`、`<HOST>` 換掉）：

```bash
gcloud scheduler jobs update http <JOB_NAME> \
  --location=asia-east1 \
  --project=line-stock-bot-498908 \
  --uri="https://<HOST>/broadcast_weekly" \
  --update-headers="Authorization=Bearer <BROADCAST_TOKEN>"
```

驗證（應為 200；若回 403 代表 header 沒帶到）：

```bash
gcloud scheduler jobs run <JOB_NAME> --location=asia-east1 --project=line-stock-bot-498908
```

> token 會存在 Scheduler job 設定裡（受 IAM 保護），不再出現在 URL。
> 確認排程穩定後，可移除 `stock_papi/integrations/line/webhook.py` 中 `_broadcast_authorized` 的 query fallback 分支。

---

## 2.（建議先做，最省事）用 max-instances 封住成本放大的上限

**為什麼**：應用層限流是 per-instance 的。Cloud Run 會自動擴充實例，所以在「攻擊者狂打 LLM 端點」的情境下，
真正決定荷包上限的是**最大實例數**。這一步不需要負載平衡器，最省事且立即見效。

```bash
# 先看目前設定
gcloud run services describe line-stock-bot \
  --region=asia-east1 --project=line-stock-bot-498908 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"

# 設一個你能接受的天花板（示例：10）
gcloud run services update line-stock-bot \
  --region=asia-east1 --project=line-stock-bot-498908 \
  --max-instances=10
```

搭配已上線的應用層限流（每 IP 30 req/60s per instance），最壞情況的 LLM 呼叫量即被
「max-instances × per-instance 限流」雙重夾住。

另外建議在 GCP **Billing** 設定預算告警（Budgets & alerts），把成本異常變成會通知你的事件。

---

## 3.（完整解，需評估成本）Cloud Armor 邊界限流

> ⚠️ **前提**：Cloud Armor **無法直接掛在 `*.run.app` 網址上**。必須先在 Cloud Run 前面架
> 一個 External Application Load Balancer（serverless NEG）。這會產生額外費用，也會換掉對外網址／憑證設定。
> 如果目前用的是預設 run.app 網址，請先評估再動；只想擋成本的話，第 2 步已經足夠。

Cloud Armor 的價值在於它由**可信邊界**判定 client IP，天然免疫 `X-Forwarded-For` 偽造，
而且是**跨實例**的全域限流——這正是應用層 per-instance 限流補不到的缺口。

### 3.1 建立 serverless NEG 與 backend service

```bash
gcloud compute network-endpoint-groups create absorb-neg \
  --region=asia-east1 --project=line-stock-bot-498908 \
  --network-endpoint-type=serverless \
  --cloud-run-service=line-stock-bot

gcloud compute backend-services create absorb-backend \
  --global --project=line-stock-bot-498908 \
  --load-balancing-scheme=EXTERNAL_MANAGED

gcloud compute backend-services add-backend absorb-backend \
  --global --project=line-stock-bot-498908 \
  --network-endpoint-group=absorb-neg \
  --network-endpoint-group-region=asia-east1
```

（其餘 URL map / target HTTPS proxy / SSL 憑證 / forwarding rule 依你既有的網域設定建立。）

### 3.2 建立限流 policy

```bash
gcloud compute security-policies create absorb-ratelimit \
  --project=line-stock-bot-498908 \
  --description="Rate limit ABSORB public endpoints"
```

對 LLM 端點限流（最重要的一條，成本放大就靠它）：

```bash
gcloud compute security-policies rules create 1000 \
  --security-policy=absorb-ratelimit \
  --project=line-stock-bot-498908 \
  --expression="request.path.matches('/api/conversation')" \
  --action=throttle \
  --rate-limit-threshold-count=60 \
  --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow \
  --exceed-action=deny-429 \
  --enforce-on-key=IP
```

對管理端點加一條更緊的（這些本來就只該被排程器呼叫）：

```bash
gcloud compute security-policies rules create 1100 \
  --security-policy=absorb-ratelimit \
  --project=line-stock-bot-498908 \
  --expression="request.path.matches('/broadcast_weekly') || request.path.matches('/tasks/')" \
  --action=throttle \
  --rate-limit-threshold-count=10 \
  --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow \
  --exceed-action=deny-429 \
  --enforce-on-key=IP
```

### 3.3 掛上 policy

```bash
gcloud compute backend-services update absorb-backend \
  --global --project=line-stock-bot-498908 \
  --security-policy=absorb-ratelimit
```

---

## 4. 若不走 Cloud Armor，又想用真實 client IP 限流

應用層目前以 `request.remote_addr` 為 key（沿用既有 LINE Login limiter 的慣例）。
在代理後面，那不一定是真正的 client IP。**不要盲目信任 `X-Forwarded-For`**——
信錯跳數會造成兩種結果：被 IP 偽造繞過限流，或把同一個 NAT 後的正常使用者一起擋掉。

要改的話，必須依實際代理跳數設定，而不是猜：

```python
from werkzeug.middleware.proxy_fix import ProxyFix

# n = 你環境中「可信代理」的實際跳數，需實測確認
flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=n, x_proto=1)
```

實測方法：暫時記錄 `request.headers.get("X-Forwarded-For")` 的實際內容，
確認自可信邊界起算的位置後，再設定 `x_for`。

---

## 檢查清單

- [ ] 1. Scheduler 廣播工作改用 `Authorization: Bearer`，並實跑驗證
- [ ] 2. Cloud Run 設定 `--max-instances`，並設 Billing 預算告警
- [ ] 3.（選用）Cloud Armor 邊界限流
- [ ] 4.（選用）確認代理跳數後再啟用 ProxyFix
