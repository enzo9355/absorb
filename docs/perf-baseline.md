# 介面層效能基準

**量測時間**：ORDER 6 完成時（`order4` 分支）
**方法**：Chromium（Playwright）、1440×900、`waitUntil: networkidle`、無快取（每條路由新 context）、本地伺服器。
**用途**：規格書 §12.3 —— 後續改動不得使傳輸量或首屏時間回歸超過 10%。

> 規格書要求「ORDER 2 開始前先量測基準」，但當時沒有人做。這份是事後補的，
> 因此它是**目前狀態的基準**，不是改版前的對照。要拿改版前後比較，
> 需要 checkout `10ddcad` 重跑同一份腳本。

## 傳輸量（bytes，未壓縮）

| 資源 | 大小 | 說明 |
|---|---|---|
| `app.css` | 125,149 | 建置時由六個原始檔串接，單一請求，帶版本參數 |
| `app.js` | 40,807 | 單檔，`defer` |
| 文字標誌字型 | 1,540 | Allura 子集，僅 A b o r s 五個字元，自架 |
| HTML | 6,618–15,219 | 依路由 |

外部相依只有 Lightweight Charts（unpkg，僅在有 K 線資料的頁面載入，
`integrity` 已釘），CSP 未放寬。無框架、無 UI kit、無建置工具（F-3）。

## 時間（毫秒）

| 路由 | FCP | LCP | DOMContentLoaded |
|---|---|---|---|
| `/` | 176 | 376 | 25 |
| `/market` | 100 | 308 | 72 |
| `/industries` | 96 | 284 | 64 |
| `/stocks` | 100 | 308 | 75 |
| `/reports` | 88 | 264 | 23 |
| `/learn` | 144 | 348 | 24 |
| `/ask` | 108 | 308 | 26 |

本地伺服器、無網路延遲，數字只能用來比較「同一台機器上的前後差異」，
不是真實使用者的體感時間。

## 回歸門檻

任一路由的 FCP、LCP，或 `app.css`／`app.js` 的位元組數，
**不得比上表高出 10% 以上**。

重跑方式：啟動本地伺服器後執行 `scripts/measure_perf.js`
（需要 `PLAYWRIGHT_BROWSERS_PATH` 指向本機 Chromium）。

## 已知的最大單一項目

`app.css` 125 KB 是目前最大的單一資源。它是六個原始檔的串接，
**不要為了縮小它而改回 `@import`** —— `@import` 會讓 `STATIC_ASSET_VERSION`
只覆蓋匯入語句（部署後版本號不變、真正的樣式檔沒有版本參數），
而且多一層 render-blocking 的串行請求。要縮小就從移除死規則著手
（ORDER 6 已移除 28 條，減少 2,701 bytes）。
