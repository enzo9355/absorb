# Stock Papi 一般投資人 Web、HTML 日報與 LINE Login 實作計畫

> 本計畫由主 Agent 直接執行；不使用 subagent 或 superpowers skills。

## 1. 凍結新契約並建立推薦引擎

- 新增推薦 typed dataclasses、集中門檻、股票／市場／產業決策與 deterministic serialization。
- 先測強多一致、過熱、趨勢分歧、低樣本、過期、防守市場、輪動分界、缺資料與重複輸入一致。
- 把推薦結果接入 stock analysis、dashboard 與 LINE stock Flex，保留舊函式 signature。
- focused tests、cold-start、commit。

## 2. 擴充可信回測統計與白話解讀

- 先測平均盈虧、期望值、profit factor、streak、all-cash、零交易、低樣本、成本敏感度與既有 parity。
- 只從目前 non-overlapping OOS returns 衍生，不改 signal／execution。
- 新增共用 interpretation mapping，接入 Web／報告；不實作缺少可信 regime labels 的市場狀態分組。
- focused tests、commit。

## 3. 首頁、個股頁與前端安全改版

- 先更新 Web payload／template tests，固定三級閱讀、空狀態、details、aria、外部連結與公開快取不含個資。
- 更新 dashboard API、templates、CSS 與 JS；修正動態 `innerHTML` escaping。
- 個股頁新增 public account-state 容器，但個人資料只由 private endpoint 取得。
- Node、Web tests、桌面／手機初步渲染、commit。

## 4. HTML 日報與 private PDF

- 先建立 publisher metadata、metadata validation、HTML route、404／503、legacy redirect 與無 PDF bytes 測試。
- 擴充 immutable metadata `public_report` 與 index 摘要；保留 SHA-256、size、path allowlist。
- 新增 report template，更新列表；舊 preview／download／sample endpoints 只轉址。
- 報告、publisher、upload script tests、commit。

## 5. LINE Login domain、storage 與 OAuth

- 先測 safe return path、state、nonce、PKCE、callback、issuer／audience／exp／nonce、token errors、cancel、replay、session rotation、logout、missing config。
- 實作無 Flask 的 OAuth service；使用 LINE 官方 token 與 ID token verify endpoints。
- 實作 Firestore auth store與 in-memory test store；server timestamp、opaque signed cookie、session TTL、atomic attempt consume。
- Auth focused tests、cold-start、commit。

## 6. 帳戶、關注同步與 CSRF

- 先測公開可讀、未登入拒絕 mutation、A/B user isolation、CSRF、no-store、profile allowlist、Firestore failure、無 client user id。
- 新增 account／watchlist templates、private APIs，沿用 `line_users/{sub}` state。
- 個股頁 AJAX 加入／取消關注，顯示提醒數與 login return flow。
- focused tests、commit。

## 7. 全站安全 headers、聲明與文件

- 新增單一 AI 聲明常數並接入 Web／HTML report／PDF。
- 加入 CSP 與 security headers；評估現有 Google Fonts／unpkg，未新增 CDN。
- 更新 `.env.example`、README、LINE Console／同 Provider、Secret Manager、Firestore、CSRF、rollback、troubleshooting。
- security tests、secret scan、commit。

## 8. 完整驗證與交付

- 全部 unittest、compileall、py_compile、Node、PowerShell syntax（若有修改）、git diff check。
- route inventory、factory isolation、cold-start、無 HTTP import、無公開 PDF bytes、cache、open redirect、CSRF、user isolation。
- 啟動本機服務，以桌面與手機 viewport 檢查首頁、個股、報告列表／內頁、帳戶與關注頁；檢查 overflow、對比、keyboard、reduced motion。
- 列出環境限制、外部 Console 步驟、commits、routes、環境變數與 rollback。
