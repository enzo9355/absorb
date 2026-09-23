# LINE → Web 導流規格

LINE 負責關注清單、提醒與快速摘要；Web 只負責完整圖表、模型解釋與分析建議。

## Rich Menu 六個入口

| 區塊 | LINE 動作 | Web 目的地 |
| --- | --- | --- |
| 看大盤 | 開啟 `/market` | `/market` |
| 看產業 | 開啟 `/industries` | `/industries` |
| 查自選 | 傳送文字 `我的關注`，在 LINE 內回覆關注清單 | 無 |
| 設提醒 | 傳送文字 `提醒管理`，在 LINE 內列出提醒並提供取消按鈕 | 無 |
| 查股票 | 傳送文字 `2330`，在 LINE 內回覆個股觀察卡 | 無 |
| 市場觀察 | 開啟 `/dashboard` | `/dashboard` |

LINE Official Account Manager 建立 Rich Menu 時，依上表設定六個 action。`03 查自選` 是六格中唯一的墨色反白格；`查股票` 的 `2330` 是可替換的範例代號。

## Flex Message 結構

LINE 卡片共用 PRESS BLOCK 色票：紙色 `#F0ECE3`、墨色 `#17151A`、磚紅 `#8A2F18`、規則線 `#8A8377`。按鈕保留原有 postback／URI data，只調整視覺層。

所有卡片共用 PRESS BLOCK 元件，維持紙色、墨色與磚紅層級，且每張卡只保留一個明確 CTA。

| 卡片 | 摘要內容 | CTA |
| --- | --- | --- |
| 每日摘要 | 大盤趨勢、五日上漲機率、風險提示 | `/market` |
| 強勢股票 | 股票名稱、最新價格、五日上漲機率 | `/stock/<code>` |
| 投資試算 | 股票卡提供「投資試算」按鈕，再選 1 萬 / 5 萬 / 10 萬或自訂格式 | `/stock/<code>` |
| 異常波動 | 漲跌或量能異常及白話說明 | `/stock/<code>` |
| 關注提醒 | 觸發條件、目前值、觸發時間 | LINE Push；CTA 前往 `/stock/<code>` |

目前關注與提醒使用 LINE `userId` 加 Firestore 保存；舊 `/watchlist` 只保留相容性轉址到 `/dashboard`。
