# X API v2 候選匯入

**更新：免費來源已成為預設。** 請優先使用 [FxTwitter 免費匯入](fxtwitter-ingestion.md)。本文件只說明需要明確指定 `--provider x-api` 的官方付費可能性路徑；不會自動啟用或作為免費來源失敗時的備援。

這個 connector 使用 X 官方 API v2 的 user timeline，將指定帳號的公開貼文寫成 **pending-review 候選 catalog**。它不使用瀏覽器自動化、不繞過登入或反爬，也不會直接修改 `data/research/public-opinions.json`。

## 設定

把 token 放在本機環境變數或 Secret Manager，不要貼進對話或提交到 Git：

```powershell
$env:X_API_BEARER_TOKEN = "..."
$env:X_API_MAX_PAGES = "3"
```

X 官方文件要求已核准的 Developer account、Project 與 App；user timeline 可依帳號取得貼文、分頁、排除 replies／retweets，並支援時間條件。請先確認帳號的 API 權限與費用設定：[Timelines](https://docs.x.com/x-api/posts/timelines/introduction)、[Usage and Billing](https://docs.x.com/x-api/fundamentals/post-cap)。

## 執行

以下只產生候選檔，不會自動進入公開頁：

```powershell
.venv\Scripts\python.exe -m stock_papi.batch.x_opinions_cli `
  --provider x-api `
  --username unusual_whales `
  --creator-id unusual-whales `
  --market US `
  --output tmp\x-unusual-whales-candidate.json `
  --max-pages 3
```

要指定股票與時間窗口可加 `--symbol NVDA --start-time 2026-09-10T00:00:00Z --end-time 2026-09-17T23:59:59Z`。沒有指定證券時，貼文仍會保存為 `unmapped`，不猜測它談的是哪一檔股票。

## 審核邊界

每筆候選保存 canonical permalink、X post ID、建立時間、抓取時間、原始 payload hash、內容分類與 `pending_review` 狀態。即使 API 回傳成功，也不能直接形成共識：人工必須核對帳號身分、是否本人觀點、證券與市場、條件／期限、是否轉貼，以及內容是否仍可回查。

X 貼文可能被編輯或刪除；正式儲存流程應依 post ID 回查並處理可用性，不能只依一次抓取結果永久展示。[Post Lookup](https://docs.x.com/x-api/posts/lookup/introduction) 與 [Compliance](https://docs.x.com/x-api/enterprise-gnip-2.0/fundamentals/firehouse) 說明了回查與合規同步方向。

Serenity 仍須先確認官方帳號身分；`candidate_serenity` 不會因 API 能查到某個 handle 就自動升格。Capafy Alpha Consensus 仍是產品參考，不是 X 原始來源。
