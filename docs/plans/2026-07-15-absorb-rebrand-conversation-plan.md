# ABSORB 實作與驗收計畫

1. 建立 canonical Logo derivatives、DESIGN.md、品牌 token 與 user-facing asset tests。
2. 將 Web、LINE、prompt、report producer 與目前文件的使用者品牌改為 ABSORB；保留歷史與 compatibility allowlist。
3. 建立 `absorb` canonical facade 與共用 conversation schema、TTL context、policy、tool registry、orchestrator、renderer。
4. 以原 handler 順序接上 LINE fallback，新增 Web `/api/conversation` 與安全、no-store 的 chat UI。
5. 加入 action proposal／confirmation、provider timeout／failure、prompt injection、cross-user、stale／missing-data tests。
6. 加入 ABSORB env compatibility、`D:\AbsorbData` copy-verify migration 與 `ABSORB-*` scheduler shadow migration；只執行 WhatIf／dry-run。
7. 新報告 writer 使用 ABSORB，reader 接受舊／新 schema kind；舊 immutable 產物不改寫。
8. 執行 focused tests、450+ full suite、compile、JS、route、cold-start、asset、PDF、Flex、migration dry-run、legacy／secret／link scan與 desktop／390px visual QA。
9. 每個可獨立驗收階段小 commit；外部 GitHub、GCP、LINE 與 production cutover 列為待人工操作。
