# 網站改版怎麼上線

寫這份文件的原因：2026-09 這一輪介面改版全部 merge 進 `main` 之後，
打開網站看到的還是舊版。不是快取，不是部署失敗 —— 是**根本沒有任何東西
會因為 merge 而上線**。這件事從 repo 本身看不出來，所以寫下來。

## 以前為什麼 merge 不等於上線

（2026-09 之前的狀況，現在已由下一節的自動流程解決。留著是因為
之後若停用 workflow，同樣的坑會再出現一次。）

- 這個 repo 完全沒有 CI，也沒有 push-to-deploy。
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

## 現在的上線方式：自動

`main` 有變動 → `.github/workflows/deploy.yml` 自動上線，你不用做任何事。

流程與保留的閘門：

1. **測試先綠**（`scripts/check_ci.sh`），紅的不准部署
2. 建**流量 0%** 的候選 revision，不是直接蓋掉線上
3. 驗候選 revision 的環境變數 —— research 模式、Observation 開啟、
   四個 prediction flags 全關、preview prefix 不得殘留。
   等同 PowerShell 的 `Assert-ObservationEnvironment`
4. 對候選網址做煙霧測試（`/healthz`、`/dashboard`、`/market`、`/stocks`、
   `/learn`、`/health/data`），新 revision 冷啟動會重試
5. 全部通過才切 100% 流量
6. 切完再驗一次，失敗**自動把流量切回原本的 revision**

判斷邏輯在 `scripts/ci/cloud_run.py` 與 `scripts/ci/smoke.py`，
有測試釘著（`tests/test_ci_deploy_helpers.py`）。其中
`test_ci_gate_matches_the_powershell_gate` 會逐字比對 CI 與 PowerShell
兩邊的環境變數清單 —— 兩條上線路徑的閘門一旦分岔就會紅，
免得出現「PowerShell 擋得住、CI 擋不住」而且兩邊各自都綠的破口。

### 這條自動路徑沒有做的事

`verify_cutover.ps1` 對 `D:\AbsorbData` 的 **LKG 收據綁定檢查**。
那需要本機資料根目錄，CI 碰不到。它驗的是「已發布的資料指標與收據相符」，
也就是資料層的保證；程式層的保證（旗標、煙霧測試、回滾）CI 都有做。

需要那一層資料保證時（例如資料管線剛改過、或要做一次正式的 cutover），
仍然走下面的手動路徑。日常的程式修改不需要。

### 首次設定

workflow 在沒有憑證時會**整個跳過**（不是紅）。要啟用需要：

1. 在 GCP 設定 Workload Identity Federation，讓這個 repo 能以
   服務帳號身分部署（角色至少要有 Cloud Run Admin、Cloud Build Editor、
   Artifact Registry Writer、Service Account User）
2. 在 repo 的 Settings → Secrets and variables → Actions → **Variables**
   新增兩個 repository variables：
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`
   - `GCP_SERVICE_ACCOUNT`

設好之後下一次 push 到 `main` 就會自動上線。

## 手動上線步驟（需要 LKG 資料保證時）

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

## CI 跑的範圍

`scripts/check_ci.sh`（CI 用）在 Linux 上跑 1496 個測試。它明確排除了
需要 Windows（`powershell.exe` / `cscript.exe` / `D:\` 路徑）或需要選用依賴
（statsmodels、CJK 字型）的模組，排除清單連同理由寫在腳本裡。

`scripts/check_ui.sh`（介面改動用）是其中較快的 204 個。

`ci.yml` 只在 pull request 上跑；push 到 `main` 的測試由 `deploy.yml`
的第一個 job 負責，所以同一份測試不會跑兩次。

完整的 `python -m unittest discover -s tests` 在 Linux 上會有 54 個紅的，
**全部**是上面那些平台/依賴原因，不是程式壞了。正確的修法是讓那些測試
在非 Windows 上自己 skip（`@unittest.skipUnless(sys.platform == "win32")`），
而不是長期靠排除清單 —— 還沒做。
