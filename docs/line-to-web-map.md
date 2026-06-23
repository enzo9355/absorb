# LINE → Web 導流規格

LINE 負責關注清單、提醒與快速摘要；Web 只負責完整圖表、模型解釋與分析建議。

## Rich Menu 四個入口

| 區塊 | LINE 動作 | Web 目的地 |
| --- | --- | --- |
| 今日盤勢 | 傳送文字 `今日盤勢`，回覆大盤摘要卡 | `/market` |
| 我的關注 | 傳送文字 `我的關注`，在 LINE 內回覆關注清單 | 無 |
| 提醒管理 | 傳送文字 `提醒管理`，在 LINE 內列出提醒並提供取消按鈕 | 無 |
| 完整分析 | 傳送文字 `完整分析`，回覆單一 CTA 卡 | `/dashboard` |

LINE Official Account Manager 建立 Rich Menu 時，依上表設定四個 message action。`功能選單` 可用來預覽相同資訊架構，不需要額外後端狀態。

## Flex Message 結構

所有卡片共用 `build_line_summary_card()`，維持一致的深色表面、綠色主動作，且每張卡只保留一個明確 CTA。

| 卡片 | 摘要內容 | CTA |
| --- | --- | --- |
| 每日摘要 | 大盤趨勢、五日上漲機率、風險提示 | `/market` |
| 強勢股票 | 股票名稱、最新價格、五日上漲機率 | `/stock/<code>` |
| 異常波動 | 漲跌或量能異常及白話說明 | `/stock/<code>` |
| 關注提醒 | 觸發條件、目前值、觸發時間 | LINE Push；CTA 前往 `/stock/<code>` |

目前關注與提醒使用 LINE `userId` 加 Firestore 保存；舊 `/watchlist` 只保留相容性轉址到 `/dashboard`。
