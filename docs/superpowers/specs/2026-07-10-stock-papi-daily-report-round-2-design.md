# Stock Papi 日報第二輪修正設計

## 目標

在不降低既有 SHA-256、壓縮大小、解壓上限、JSON schema、market、symbol 與日期驗證的前提下，安全遷移缺少 `uncompressed_size` 的舊 TW manifest，並提升日報的每日比較、產業輪動、回測揭露、觀察名單與 PDF 排版。

## 邊界

- 保留 `reporting.source_loader` 對缺少或錯誤 `uncompressed_size` 的拒絕行為。
- migration 只讀取既有 immutable manifest 與 content-addressed 股票物件，不抓行情、不重訓模型、不修改舊 manifest。
- 所有股票驗證完成後才寫新 manifest，最後才以 `os.replace` 更新 `latest-TW.json`。
- 真實報告只從 migration 後能通過正式 loader 的資料生成；SAMPLE 仍禁止正式發布。
- 不改 Cloud Run 啟動路徑；`matplotlib`、`reportlab`、`pypdf` 維持延遲載入。

## Migration 資料流

1. `reporting.migrate_quant_manifest` 解析 `--root`、`--market`、`--latest`、`--dry-run`。
2. 驗證 latest 格式、舊 manifest 路徑與 SHA-256，再驗證 manifest 結構。
3. 對每個 entry 先串流計算壓縮 bytes 數與 SHA-256，再以 `gzip.GzipFile` 分塊解壓，累計實際 bytes；超過 `ReportConfig.max_uncompressed_bytes` 立即失敗。
4. 對解壓 bytes 驗證 UTF-8 JSON、有限數字、schema version、market、symbol、as_of、model_version 與最後交易日。
5. 建立只新增正確 `uncompressed_size` 的新 manifest，使用 canonical UTF-8 JSON bytes 計算 SHA-256 與 content-addressed 檔名。
6. dry-run 僅輸出統計；正式模式先原子寫入新 manifest，最後原子替換 latest。任一物件失敗時不寫 latest。

## 分析資料模型

- `MarketSnapshot` 增加 MA60 廣度、上漲／下跌家數、20 日新高／新低、量能相對值、資料新鮮度與前期變化。
- `IndustrySnapshot` 增加前日排名、排名變化、機率變化、前日輪動、階段變化、樣本品質、接近分界與 `signal_profile`。
- 高機率只使用 `>= 60%`，偏弱只使用 `<= 45%`，兩者互斥；沒有偏弱產業時顯示明確空狀態。
- `build_daily_report(..., previous_source=None)` 接受可選的前期來源；沒有可驗證前期來源時使用 `None`，摘要顯示「無前期報告可比較」，不補零。
- pooled 模型品質逐一使用歷史 OOS `AI_P` 與其後五日實際方向，計算樣本數、方向準確率、Brier Score、高分訊號勝率與機率分桶。

## 回測與觀察名單

- 回測分開記錄再平衡、進場、獲利、虧損與空手期數；勝率分母只使用進場期數。
- 全程空手時策略績效欄位顯示 `—`，但保留再平衡與進場期數。
- 低樣本結果標示樣本品質；Sharpe 與勝率不作產業推薦排序依據。
- 觀察名單使用來源內的真實名稱，拒絕正式資料中的「測試股票」；技術狀態統一為站上、跌破、接近 MA20。
- 外資欄位只在資料欄位可確認單位時顯示對應單位；`ForeignNet` 直接由來源買進股數減賣出股數且未除以 1,000，PDF 表頭標示「股」。

## PDF

- 使用流式 Platypus story，移除固定 `PageBreak`；必要的章節分隔使用自然換頁與重複表頭。
- 首頁改成研究摘要與絕對門檻名單；第二頁使用 KPI cards、進度條與小型圖表。
- 產業主表只放前 10、後 5、名次變化與輪動改變；完整表拆為附錄表格，避免超寬欄位。
- 輪動圖加入四象限淡色背景、中性帶、泡泡圖例與偏移標籤，並在圖外提供可擷取文字。
- 回測圖使用實際再平衡日期；每頁只放代表性圖，並在圖旁揭露日期、期數、樣本品質與回撤。
- 內文字型與標題字型分開設定；優先使用 Noto Sans CJK TC 與 Noto Serif CJK TC，找不到時不偽稱使用 Noto。
- 方法論列出來源 manifest、版本、Git SHA、日期、模型版本、覆蓋率、sample flag 與自動生成揭露，不顯示本機路徑或私有 bucket。

## 驗證

- unittest 先覆蓋 migration 成功／失敗原子性、分析門檻與比較、輪動中性帶、回測樣本拆分、正式名稱與 PDF 文字／日期軸。
- 先跑 migration dry-run；成功後才建立新 immutable manifest，再用正式 2026-07-08 快照生成 PDF。
- 使用 pypdf 擷取文字，Poppler 渲染全部頁面後逐頁檢查裁切、重疊、空白頁、字型與圖表。
- 最後執行完整 unittest、`py_compile`、PowerShell／Node 語法檢查（若變更相關檔案）與 `git diff --check`。
