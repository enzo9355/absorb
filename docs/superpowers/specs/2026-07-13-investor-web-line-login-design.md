# Stock Papi 一般投資人 Web、HTML 日報與 LINE Login 設計

## 目標與現況

本次在已完成的漸進式模組化分支上，新增一個 Web、LINE 與報告共用的確定性推薦層，將首頁與個股頁改為「結論與行動 → 判斷依據 → 專業資料」三級閱讀，並把 HTML 日報改為唯一公開報告入口。公開分析維持免登入；關注、提醒與帳戶功能使用 LINE Login，直接共用目前 `line_users/{LINE user id}` 的 `state`，不複製第二份關注資料。

目前可驗證基線：

- 19 條非 static 公開 URL rule；根目錄 `app.py` 18 行。
- 358 項 unittest 中 355 項通過。其餘 2 failures、1 error 是本機 Windows Application Control 封鎖科學運算原生模組與 `.deps` 缺少 matplotlib，不是 route、Web、LINE 或 trust-boundary 回歸。
- `import app` 不載入 pandas、numpy、sklearn、LightGBM、matplotlib、reportlab、pypdf 或 Gemini，也不發出 HTTP request。
- 日報 index、metadata、PDF 均為 content-addressed／SHA-256 驗證物件；目前公開 preview／download 仍會回傳 PDF bytes。
- LINE Bot 關注與提醒儲存在 `line_users/{line_user_id}` 的正規化 `state` JSON；Web 可用已驗證 LINE Login `sub` 直接共用。

## 非目標

- 不更改 LightGBM、五日預測目標、特徵、進場門檻、0.585% 交易成本、非重疊或 point-in-time 規則。
- 不加入付款、訂閱分級、Google／Email 登入或自訂密碼。
- 不實作 LIFF。缺少 Console App 與真實 Provider 驗證時，LINE Login 已涵蓋本輪必要價值；LIFF 留作後續同一 session 邊界的入口。
- 不在 Cloud Run request 期間產生 PDF、重跑全市場回測或訓練模型。
- 不修改或提交既有未追蹤 `static/samples/`。

## 統一推薦引擎

新增 `stock_papi/services/recommendation_engine.py`。它只接受 typed input、只回傳 `RecommendationResult`，不依賴 Flask、LINE、Firestore、網路或生成式 AI。

固定輸出：scope、entity id、action、level、headline、confidence、supporting reasons、risk reasons、suggested action、invalidation conditions、未持有／已持有指引、data as of、source metrics。`to_dict()` 是 Web、LINE 與報告共用序列化邊界。

集中門檻只復用 repository 既有規則：

- 偏多／偏弱機率：60／45。
- RSI 過熱／超賣：70／30。
- 量能異常／不足：2.0／0.8。
- 波動率升高：3%。
- 產業強建議最低覆蓋：80%。
- 回測樣本：少於 12 為低、12–23 有限、24–47 中等、48 以上相對完整。
- 資料新鮮度：超過一個市場工作日即禁止強建議；週末不把星期五資料誤判過期。

任何必要欄位缺失、資料過期、樣本不足、價格來源警示、重要來源不一致或產業覆蓋不足，都先降級。生成式 AI 不參與 action label；現有 Gemini 只可處理已決定內容的文字潤飾，失敗時使用 deterministic 結果。

## 回測統計與白話層

`stock_papi.quant.backtest` 與 `reporting.industry_backtest` 在不改交易路徑的前提下，從既有非重疊 OOS period returns 計算：平均獲利、平均虧損、平均每次進場報酬、payoff ratio、profit factor、最長連續獲利／虧損、空手比例、年度結果與 0／1／2 倍既有交易成本敏感度。

`reporting/interpretation.py` 只負責把已計算指標翻成白話，不重做推薦規則。市場狀態分組沒有可信的 point-in-time regime label，因此本輪不近似計算「不同市場狀態表現」。

## Web 資訊架構

首頁由 `/api/dashboard` 取得：

1. 市場推薦與查股票雙入口。
2. 市場行動、優先方向、最大風險。
3. 分組後的產業推薦卡。
4. 焦點個股推薦卡。
5. 既有市場熱力圖與學習內容。

個股頁由現有分析 payload 加入 `recommendation` 與 `backtest_interpretation`。第一屏呈現 action、headline、做法、失效條件及四張摘要卡；支持／反對理由在第二層；Sharpe、Brier、OOS、特徵與完整指標放入預設收合的 `<details>`。K 線、試算、籌碼、情緒、同儕與新聞維持。

個人狀態不混入可公開快取的個股 HTML。頁面透過 `GET /api/account/state?code=...` 讀取 private/no-store 狀態，使用 CSRF token 呼叫 `POST /api/account/watchlist`。

## HTML 日報與 PDF 退役

新增 `GET /reports/<report_date>`，它只讀取 index 指定且通過 path、size、SHA-256 與 schema 驗證的 immutable metadata。publisher 在 metadata 內新增 `public_report`，包含市場推薦、三件重要事項、產業／股票解方、回測白話、圖表等價文字、專業數據、方法與限制。舊 metadata 缺少此欄位時顯示安全的歷史摘要降級頁，不猜測缺失數據。

index 增加經驗證的 `market_action`、`headline` 與 `key_industries`，讓列表以讀者結論為主；既有技術欄位移入 `<details>`。

以下 endpoint 保留名稱與 method，但不再回傳 PDF：

- `/reports/<report_date>/preview` → 302 至 HTML 報告。
- `/reports/<report_date>/download` → 302 至 HTML 報告。
- `/reports/sample/download` → 302 至報告列表。

PDF 仍由本地 pipeline 產生、驗證與保存於 private GCS，不提供公開 bytes 或 GCS URL。

## LINE Login 與 server-side session

使用 LINE Login v2.1 Authorization Code Flow：

1. `GET /auth/line/login` 產生 cryptographically secure state、nonce、PKCE verifier／S256 challenge，把一次性 login attempt 寫入 Firestore，瀏覽器只收到簽章後的 opaque attempt cookie。
2. callback 先原子 consume attempt、固定時間比對 state，再以完全相同 redirect URI 與 verifier 換 token。
3. 後端呼叫 LINE 官方 `/oauth2/v2.1/verify` 驗證 ID token signature、issuer、audience、expiration 與 nonce；不自行實作 JWT 密碼學。
4. 只取已驗證 `sub`、`name`、HTTPS `picture`，不保存 access token、refresh token 或完整 ID token。
5. 建立新的 opaque session id 與 CSRF token，使用 `SESSION_SECRET` HMAC 簽章 cookie；舊 session 失效，避免 fixation。

Firestore collection：

- `oauth_attempts/{opaque_id}`：state、nonce、PKCE verifier、safe return path、expires_at；callback 原子讀取並刪除。
- `web_sessions/{opaque_id}`：line_user_id、csrf_token、created_at、expires_at；登出刪除。
- `users/{line_user_id}`：allowlist profile、server timestamps、login_count、active/free/schema v1。
- `line_users/{line_user_id}`：沿用既有 watchlist、alerts、pending、signals。

公開頁缺少設定時照常可讀；登入入口若缺任何 Channel／redirect／session／GCP 設定則 503 fail closed。生產環境 cookie 固定 Secure、HttpOnly、SameSite=Lax、Path=/、明確 Max-Age。Return URL 只允許同站 `/...` 相對路徑，拒絕 `//`、scheme、host、反斜線與控制字元。

新增 routes：

- `GET /auth/line/login`
- `GET /auth/line/callback`
- `POST /auth/logout`
- `GET /account`
- `GET /account/watchlist`
- `GET /api/account/state`
- `POST /api/account/watchlist`

## 安全與快取

- 個人頁與 API：`Cache-Control: private, no-store`；所有 mutation 驗證 session 與 CSRF，user id 只取自 session。
- 公開 HTML 日報：`Cache-Control: public, max-age=300`，payload 不含任何 session／關注資料。
- 全站加入 CSP、`frame-ancestors 'none'`、`base-uri 'self'`、`form-action 'self'`、nosniff、referrer policy 與 permissions policy。
- 動態 dashboard 文字在前端 escape；股票代碼 URL 使用 `encodeURIComponent`，不直接信任 API 字串。
- 外部連結固定 `rel="noopener noreferrer"`；picture 只接受 HTTPS。
- 日誌不記錄 token、code、state、nonce、session id、完整 profile 或 Firestore document。

## 單一聲明

`stock_papi/presentation/content.py` 維護 AI 量化解方聲明。base template、HTML report、說明 dialog 與 PDF 都讀同一常數；不在 templates 複製不同版本。

## 驗證與 rollback

每階段先建立失敗測試，再做最小實作；focused tests 通過後建立小型 commit。最後執行 358 項既有測試加新增測試、compileall、py_compile、Node syntax、route inventory、cold import、secret scan、PDF bytes route、cache、open redirect、CSRF、user isolation、桌面／手機與 keyboard 檢查。

各階段 commit 可依序 `git revert <sha>`。若認證設定有問題，可先移除 LINE Login 環境變數，公開功能仍可用且登入 fail closed；HTML report 可獨立回滾至舊 routes，但不得公開 PDF storage。
