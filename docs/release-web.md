# 網站改版怎麼上線

寫這份文件的原因：2026-09 這一輪介面改版全部 merge 進 `main` 之後，
打開網站看到的還是舊版。不是快取，不是部署失敗 —— 是**根本沒有任何東西
會因為 merge 而上線**。這件事從 repo 本身看不出來，所以寫下來。

## 為什麼 merge 不等於上線

- 這個 repo 沒有 push-to-deploy。`.github/workflows/ci.yml` 只跑測試，
  不部署。
- 正式站是 Google Cloud Run：專案 `line-stock-bot-498908`、
  服務 `line-stock-bot`、區域 `asia-east1`。
- 部署由 `scripts/deploy_observation_production.ps1` 在 Windows 上手動執行，
  而且它用的是 `--source $RepoRoot`，也就是**執行當下那台機器的工作目錄**，
  不是 GitHub 上的 `main`。本機沒有 pull，部署出去的就還是舊的。
- 就算腳本跑了，預設也**不會**切流量。它用 `--no-traffic --tag`，
  新 revision 只拿到一個帶 tag 的預覽網址、流量 0%。
  正式流量只有在加 `-ApplyTraffic` 時才會切（腳本裡的 `update-traffic` 那段）。

所以「以為部署了但還是舊版」有兩個獨立的原因，兩個都要排除：
**本機沒 pull**，以及**沒切流量**。

## 上線步驟

在 Windows 那台機器上：

```powershell
# 1. 把要上線的版本拉下來 —— 這步不能省，部署吃的是本機目錄
git -C <repo> fetch origin main
git -C <repo> checkout main
git -C <repo> merge --ff-only origin/main
git -C <repo> log -1 --oneline   # 確認 commit 就是你要上的那一版

# 2. 取得 Observation LKG 收據（deploy 腳本的必填參數）
./scripts/capture_observation_lkg.ps1

# 3. 部署並切流量
./scripts/deploy_observation_production.ps1 `
    -ObservationLkgReceipt <上一步產生的收據路徑> `
    -ApplyTraffic
```

第 3 步會先建一個 no-traffic revision、驗證環境變數
（research 模式、Observation 開啟、所有 prediction flags 關閉）、
跑 cutover 驗證，通過之後才把流量切到 100%，失敗會自動回滾。
詳細的控制點見 `docs/absorb-cutover-checklist.md`。

## 怎麼確認線上現在是哪一版

部署時 commit 會寫進 revision 的環境變數 `ABSORB_SOURCE_COMMIT`
和 label `absorb-source-commit`：

```powershell
# 現在誰在收流量
gcloud run services describe line-stock-bot `
    --project line-stock-bot-498908 --region asia-east1 `
    --format="value(status.traffic)"

# 那個 revision 是哪個 commit
gcloud run revisions describe <revision> `
    --project line-stock-bot-498908 --region asia-east1 `
    --format="value(metadata.labels.absorb-source-commit)"
```

把結果跟 `git log -1 --format=%H origin/main` 對一下就知道差幾版。

**不要用 `/healthz` 判斷版本** —— 它只回 `ok`，任何版本都一樣
（`stock_papi/web/routes/system.py:218`）。

## 不是快取的問題

`static/` 與 `templates/` 裡沒有 service worker，也沒有 `sw.js` 註冊，
所以不會有舊資產被釘在瀏覽器裡。看到舊版就是還沒部署，硬重新整理沒有用。

## 自動建候選 revision（尚未建立）

可以再加一條 workflow，在 `main` 有變動時自動建一個 **流量 0%** 的
Cloud Run 候選 revision，把「main 建不建得起來」跟「要不要上線」分開，
切流量仍然留給上面第 3 步的腳本（因為只有它會驗 LKG 收據、
檢查 prediction flags、寫部署收據、失敗回滾）。

那需要先在 GCP 設好 Workload Identity Federation，並在 repo 設兩個
repository variables：`GCP_WORKLOAD_IDENTITY_PROVIDER`、`GCP_SERVICE_ACCOUNT`。
還沒做，要做再說。

## CI 跑的範圍

`scripts/check_ci.sh`（CI 用）在 Linux 上跑 1483 個測試。它明確排除了
需要 Windows（`powershell.exe` / `cscript.exe` / `D:\` 路徑）或需要選用依賴
（statsmodels、CJK 字型）的模組，排除清單連同理由寫在腳本裡。

`scripts/check_ui.sh`（介面改動用）是其中較快的 204 個。

完整的 `python -m unittest discover -s tests` 在 Linux 上會有 54 個紅的，
**全部**是上面那些平台/依賴原因，不是程式壞了。正確的修法是讓那些測試
在非 Windows 上自己 skip（`@unittest.skipUnless(sys.platform == "win32")`），
而不是長期靠排除清單 —— 還沒做。
