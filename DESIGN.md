# ABSORB Design System

ABSORB 是 AI 量化市場情報與決策輔助系統。介面先服務資料閱讀，再表達品牌；任何視覺處理都不得暗示保證獲利。

## 1. Brand concept

「吸收資料、辨識證據、形成可驗證判斷」。品牌名稱在所有內文、標題、報告與 LINE 訊息中固定寫作 `ABSORB`；唯一例外是導覽文字標誌，依 §4 寫作 `Absorb`。不得使用舊品牌、人格式暱稱或蝴蝶意象。

## 2. Design principles

- Evidence first：結論、依據、反對證據、限制依序呈現。
- Quiet precision：白色畫布、深藍識別、細邊界、少裝飾。
- Honest states：缺值保留缺值，過期資料標日期，不用顏色掩飾資料品質。
- Same meaning everywhere：Web、LINE 與報告使用相同 action label、日期與限制。

## 3. Visual atmosphere

研究平台而非促銷頁。大量留白、清楚層級、平面表面；不使用玻璃擬態、金屬感、黑金風、裝飾性 K 線或漸層堆疊。

## 4. Logo usage

- Canonical 圖形來源維持 `static/brand/absorb-mark.png`，SHA-256 `2e7b3950809748d5e02648dfc26b0b403f7cabd2d706ce3130b28bad86c9443d`，供 favicon、社群預覽、LINE 與其他非導覽用途使用。
- Canonical 圖形維持純白背景、原始比例與安全邊距；不得裁切、重畫、改色、加字、陰影或漸層。使用圖形時 HTML alt 固定為「ABSORB logo」。
- 導覽文字標誌固定為手寫草寫的 `Absorb`（首字大寫、其餘小寫），不得搭配圓形圖示，並連回目前市場的研究摘要。
- 文字標誌使用自架的 `static/fonts/absorb-wordmark-allura.woff2`（Allura，OFL，僅含 A b o r s 五個字元），family 名稱維持 `ABSORB Wordmark`。Allura 只有一個字重，加粗一律以 `-webkit-text-stroke:.024em currentColor` 完成，不得改用 `font-weight` 觸發合成粗體。字級取 type scale 內的值（§6）：桌機 32px、行動版 28px —— Allura 字面比 Caveat 小，取較大的一級補回等視覺大小。字距 0、行高 1.3（容納大寫 A 的起筆）；不得加陰影、漸層或外框色。

## 5. Color system

Logo 實測主要深藍為 `#122643`。CSS token（ORDER 2 起單一命名空間：保留
`--absorb-*` 命名、採用原 `--command-*` 實際值；`tokens.css` 為唯一來源）：

```css
/* 品牌與中性 */
--absorb-navy: #183147;
--absorb-navy-hover: #21445d;
--absorb-navy-active: #0b1b31;
--absorb-navy-soft: #eaf0f7;
--absorb-canvas: #f1f4f4;
--absorb-surface: #f7f6f2;
--absorb-surface-raised: #faf9f6;
--absorb-ink: #152638;
--absorb-muted: #536575;
--absorb-subtle: #7a8798;
--absorb-hairline: #d9e1e2;
--absorb-line-strong: #b7c1cf;
--absorb-focus: #2b6cb0;
--absorb-pure-white: #ffffff;
/* 語意色（唯一用途） */
--absorb-success: #18704a;
--absorb-warning: #8a5b00;
--absorb-danger: #a33a44;
--absorb-info: #245b91;
/* 支援色與色票 */
--absorb-blue: #4e7d91;
--absorb-blue-light: #8fb9c8;
--absorb-coral: #b85f55;
--absorb-sage: #3f8060;
--absorb-sage-soft: #e3eee8;
--absorb-accent-surface: #e8eff1;
/* 邊界與表面色票 */
--absorb-border-soft: #ccd9df;
--absorb-border-mid: #cbd8de;
--absorb-border-faint: #dce5ea;
--absorb-border-track: #d3dfe4;
--absorb-border-dashed: #b9c8cf;
--absorb-border-hover: #b9c9d1;
--absorb-border-strong: #aebbc5;
--absorb-border-active: #a9bdc6;
--absorb-border-cool: #c8d5de;
--absorb-border-green: #a8cfc0;
--absorb-border-salmon: #d99b8b;
--absorb-surface-highlight: #e2ecef;
--absorb-surface-warm: #ebe8e1;
--absorb-surface-neutral: #e6e1d8;
--absorb-surface-switch: #e7edf1;
--absorb-surface-sky: #edf3fa;
--absorb-surface-muted: #f2f5f7;
--absorb-surface-alert: #fff5f1;
--absorb-surface-amber: #fff8e8;
--absorb-surface-amber-deep: #fef3c7;
--absorb-surface-red: #fee2e2;
--absorb-surface-red-soft: #fff1f1;
--absorb-surface-green: #e7f4ed;
--absorb-surface-gold: #ead9aa;
/* 強調與狀態色票 */
--absorb-danger-strong: #8b2e1e;
--absorb-ink-faint: #43515d;
--absorb-purple: #6b5b95;
--absorb-purple-deep: #5c557a;
--absorb-rose: #713548;
--absorb-olive: #75601f;
--absorb-brick: #8a4e38;
--absorb-rose-muted: #9b4d5c;
--absorb-green-deep: #176b57;
--absorb-green: #05a948;
--absorb-green-bright: #06c755;
--absorb-brown: #665f58;
--absorb-amber-strong: #b45309;
--absorb-amber-deep: #92400e;
--absorb-red: #991b1b;
--absorb-red-strong: #b91c1c;
--absorb-green-ok: #047857;
--absorb-blue-strong: #1d4ed8;
--absorb-amber-soft: #f59e0b;
--absorb-severity-high: #9b263e;
--absorb-severity-medium: #b7791f;
/* 漲跌方向色（依市場語境） */
--price-up: var(--absorb-danger);    /* 台股紅漲 */
--price-down: var(--absorb-success); /* 台股綠跌 */
body[data-market="US"] { --price-up: var(--absorb-success); --price-down: var(--absorb-danger); }
--absorb-on-dark-up: #f2aaa3;
--absorb-on-dark-down: #a9dbc3;
--price-up-on-dark: var(--absorb-on-dark-up);
--price-down-on-dark: var(--absorb-on-dark-down);
body[data-market="US"] { --price-up-on-dark: var(--absorb-on-dark-down); --price-down-on-dark: var(--absorb-on-dark-up); }
```

文字與背景對比至少符合 WCAG AA。漲跌顏色必須同時搭配文字或符號。

### 語意色的唯一用途

| Token | 唯一用途 |
| --- | --- |
| `--absorb-success` / `--absorb-danger` | 漲跌方向的來源色，經 `--price-up` / `--price-down` 依市場映射 |
| `--absorb-warning` | 僅 stale 狀態與資料品質警示 |
| `--absorb-info` | 僅「這是模型估計」的標記，含 K 線預測帶 |
| `--absorb-navy` | 僅導覽、主要按鈕與品牌元素，**不參與任何資料語意** |

承載內容的深色面板使用中性的 `--absorb-ink-surface`，不使用品牌深藍。
深色底上的漲跌色另用 `--price-up-on-dark` / `--price-down-on-dark`，以維持 WCAG AA。所有方向
元件一律從 `--price-up` / `--price-down` 取色；深色面板（`.forecast-panel`、
`.us-index-forecast-list article`）內以 `--price-*-on-dark` 重映射維持對比。

## 6. Typography

英文字優先使用系統已安裝的 `Avenir Next` 或 `Avenir`，繁體中文搭配 `Noto Sans TC`，再依序退回 `PingFang TC`、`Microsoft JhengHei` 與 `sans-serif`。不下載、內嵌或提交專有字型，也不建立外部 font request；文字標誌字型自架於 `static/fonts/`，授權全文一併保留（見 `OFL-Allura.txt`）。草寫只用於導覽文字標誌，內容標題維持人文無襯線。

### Type scale（封閉集合）

八個級距為全站唯一允許的字級，由 `static/tokens.css` 定義並由測試鎖住。中文行高一律不低於 1.3。

| Token | 字級／行高 | 用途 |
| --- | --- | --- |
| `--type-display` | 32 / 1.35 | 頁面主標題，每頁一個 |
| `--type-title` | 24 / 1.4 | 區塊標題、研究版章節標題 |
| `--type-subtitle` | 19 / 1.5 | 卡片標題、研究版小節 |
| `--type-body` | 15 / 1.75 | 內文、白話解讀、缺值說明、限制陳述 |
| `--type-caption` | 13 / 1.65 | 次要說明、表格內容 |
| `--type-label` | 11 / 1.5 | 欄位標籤、術語標籤，letter-spacing .08em |
| `--type-data-lg` | 28 / 1.2 | 主要數值，tabular-nums |
| `--type-data-md` | 19 / 1.3 | 次要數值、統計量，tabular-nums |

10px 全面廢除。`.breadth-chart` 內的 7／3.2px 為 SVG viewBox 座標而非 CSS px，為明確豁免。
免責與限制文字一律使用 `--type-body`；縮小限制的字級等同於淡化限制。


## 7. Numeric typography

價格、機率、報酬、日期與表格數字使用 `font-variant-numeric: tabular-nums`。小數位由資料契約決定，不以補零假裝精度。

## 8. Spacing

基準 4px；常用 token 為 4、8、12、16、24、32、48px。內容卡內距以 16 或 24px 為主。

## 9. Radius

封閉集合，只允許四個值，由 token 定義並由測試鎖住：`--radius-sm` 6px（小元件、標籤）、`--radius-md` 8px（按鈕與輸入）、`--radius-lg` 10px（卡片）、`--radius-pill` 999px（狀態膠囊）。其餘數值一律禁止。

## 10. Borders

一般邊界 1px `--absorb-hairline`；focus 不以 border 替代，使用可見的 2px outline。

同一視覺層級內不得同時以 1px 邊界與底色區隔，兩者擇一 —— 兩者並用是畫面雜訊的主因。卡片內距下限 16px（§8）。此規則針對卡片，不適用於按鈕與輸入等以填色表達可互動性的控制項。

## 11. Shadows

預設無陰影。需要區分浮層時只用 `0 8px 24px rgb(18 38 67 / 8%)`，不得套用於 Logo。不做 hover 浮起；擁擠感的解法是 §10 的「邊界與底色擇一」與內距，不是加陰影。

## 12. Surfaces

Canvas 使用淡中性，主要內容使用純白；raised surface 僅用於選單、dialog 或必要層級。

## 13. Cards

卡片只包一個決策單位，順序為標籤、結論、數據、限制。禁止把每段文字各包一張卡。

**巢狀上限一層。** 卡片內不得再出現有邊界或底色的卡片。需要分區時用留白、標題或分隔線，不是再包一層框。分段容器（例如頁面的四段式）是純版面容器：沒有 padding、border、background、border-radius，其中的卡片才是同一層的平行卡片。

卡片內距下限 16px（§8）。同一張卡不得同時有 1px 邊界與底色（§10）。

## 14. Buttons

Primary 為深藍底白字；secondary 為白底深藍邊界；danger 僅用於確實具破壞性的確認。disabled 不可只靠降低透明度。

## 15. Inputs

永遠有可見 label。錯誤文字緊鄰欄位並可由 screen reader 關聯。placeholder 不替代 label。

## 16. Tables

表頭固定語意，數字靠右，文字靠左；小螢幕優先水平捲動或轉為成組定義列，不藏核心欄位。

## 17. Navigation

**五個核心入口**：今日 `/`、市場 `/market`、產業 `/industries`、個股 `/stocks`、報告 `/reports`。桌面與行動版一致，不因寬度增減項目；560px 以下改用兩字縮寫，不隱藏任何一個。

**輔助入口**與核心入口分組呈現：ASK ABSORB 維持全站浮動觸發器與完整頁，學習不進主導覽（由術語標籤與頁尾進入），帳戶維持工具性入口。

**台股／美股切換器置於側欄最上方**，因為它決定下面所有項目的內容；不得放在頂欄另一角，否則從屬關係沒有被表達。市場切換必須導向實際存在且通過驗證的市場內容，不得只換標籤。

**所有明細頁提供具名的上一層**：「返回個股與 ETF」而非泛用的「返回」。多入口頁面上的泛用返回沒有意義 —— 讀者不知道會去哪裡。

長內容頁（研究版報告）提供常駐章節索引，標示當前章節，並在末端提供回到索引。

## 18. Charts

圖表只呈現可驗證資料。座標、資料日、**單位**、圖例與缺值狀態必須在圖表自身可見 —— 讀者不該為了知道一條線是什麼而翻別頁。

**折線不填色。** 不可用面積、3D 或動畫誇大變化。不加光暈或發光效果。

**所有顏色取自 token。** 方向性元素（K 線漲跌、方向量條）一律從 `--price-up` / `--price-down` 取色（§5）；非方向的輔助線（均價線）使用 `--chart-ma`；模型估計使用 `--absorb-info`。圖表內不得出現十六進位色字面值。圖形元素對底色的對比不得低於 3:1（WCAG 1.4.11）。

**模型估計必須與已發生資料視覺分區。** 圖例逐條標明哪些是已發生、哪一條是估計；估計的摘要數字自成區塊，標題直接說明它是估計，不與實際價格共用同一張卡。

## 19. Data states

資料狀態固定為 available、partial、stale、unavailable。`None` 不轉為 0；stale 必須顯示資料日期且不得使用「現在」。

**缺值不是數值。** unavailable 時該格不進入數值的字級與顏色軌道，改用 `.value-unavailable`（內文字級、muted 色），整格的視覺重量必須低於有資料時；數值與單位一起消失，不得出現 `—／—` 或裸的 `%`。狀態以 `.state-chip`（`is-partial` / `is-stale` / `is-unavailable`）標示：stale 用 warning，partial 與 unavailable 維持中性 —— 取不到資料不是錯誤，是狀態。

同一區塊內若超過半數為 unavailable，收合為單一的 `.state-note`，置於區塊最上方，不逐格重複。文案三句式：發生什麼 ＋ 為什麼 ＋ 何時；禁止只寫「請稍後再試」。

元件的每一種狀態都在 `/_catalog` 有實例，該頁為單一事實來源。

## 20. Empty states

說明缺少什麼、是否可稍後重試，以及仍可採取的安全操作；不得補 SAMPLE 或假資料。

**零筆不佔版面。** 多類別的清單（例如七類個股事件）在 0 件時不得各佔一張卡片。件數一律進單一摘要列（0 件也是資訊：代表沒有越過門檻，不是資料缺失），只有件數大於 0 才展開為區塊。全部為 0 時以一則 `.state-note` 說明「沒有觸發」不等於「資料缺失」。

`.empty-state` 必須帶 `grid-column:1 / -1` —— 它經常被放進 grid 容器，沒有這一條會掉進第一個欄軌並逐字換行。

## 21. Loading states

使用固定尺寸 skeleton 避免版面位移（`.skeleton`，is-text / is-value / is-block）；超過合理等待時間顯示可理解的降級訊息。`prefers-reduced-motion` 下不套用動畫。

## 22. Error states

對外只顯示安全錯誤與下一步，不顯示 stack trace、路徑、object name、token 或 provider 細節。

## 23. Mobile behavior

**四種驗收寬度**：390 / 768 / 1440 / 2560px，每一種都必須無文字裁切、無元素遮蔽、無整頁水平溢出。360px 與 320px 為額外檢查點（200% 縮放等同於半寬）。

**密度目標**：主版面的「今天怎麼了」與「最新更新」必須落在第一個 800px 畫面內（已驗證資料的情境）。事實列在窄寬度維持兩欄，不逐項堆疊成一列一項 —— 那只會把下一段推出畫面。

觸控目標至少 44px，表單不造成水平溢出，結論、風險、失效條件與資料日期不可因篇幅被刪除。

**固定定位的浮動元素必須預留安全距離**：主內容底部保留大於浮動鈕高度加底距的空間（目前 96px），否則最後一列內容會永遠被蓋住，而且捲到底也躲不掉。

## 24. Accessibility

支援鍵盤、skip link、語意標題、可見 focus、reduced motion、非顏色語意與有意義的 alt。裝飾圖使用空 alt。

**鍵盤**：所有主要流程可由鍵盤完成。浮層開啟時焦點鎖在浮層內，Esc 關閉並把焦點還給觸發器。分頁（tablist）支援方向鍵、Home、End。

**縮放**：200% 縮放下仍可操作，等同於在半寬視窗檢查（1440 → 720、768 → 384）。

**顏色不是唯一線索**：方向、狀態、選取與當前位置都必須同時有文字、符號或字重／底線的差異。灰階截圖下必須仍可辨識 —— 這一條包含章節索引的當前章節、分頁的選取狀態、產業強弱分組。

**圖表替代內容**：每張圖提供 `role="img"` 與描述性 `aria-label`，並附一份 `sr-only` 的資料表列出最近數期的實際數值。圖例以文字說明每一個視覺元素代表什麼。

**表單**：永遠有可見 label（§15）。grid 項目記得 `min-width:0`，否則按鈕的 min-content 會把整個表單撐出容器。

## 25. Motion

只用 120–180ms 的狀態回饋；遵守 `prefers-reduced-motion`。資料更新不得以持續閃爍吸引注意。

## 26. Dark mode

目前不自動提供。未完成逐元件對比驗證前，不以反相或純黑加金色快速產生深色版。

## 27. Report layout

報告採研究文件層級：標題與資料日、執行摘要、證據、反對證據、限制、附錄。新報告 producer 顯示 ABSORB；歷史 immutable 產物不改寫。

## 28. LINE Flex visual rules

以深藍標題、白色 surface、清楚分隔線為主。每張卡只保留一個主 CTA；文字 fallback 必須含結論、風險、失效條件、資料日與限制。

## 29. Anti-patterns

禁止舊品牌、蝴蝶、父系／長輩人格、Logo watermark、圖片內嵌文字、暖米色主題、玻璃擬態、大面積純黑、金色裝飾、過量圓角、無來源即時數字、只靠顏色表示漲跌，以及把 Dashboard 改成促銷 Landing Page。

## 30. 術語對照表

主版面用白話，研究版用術語。兩邊指的是同一件事，對照表是唯一事實來源；學習頁 `/learn` 的每個條目固定回答四件事：白話定義、如何閱讀、常見誤解、在 ABSORB 哪裡出現。

| 主版面白話 | 研究版術語 | 學習頁錨點 |
|---|---|---|
| 股價在近一個月平均價之上的比例 | 市場廣度 / MA20 breadth | `#term-breadth` |
| 今天成交量相對平常的倍數 | 量比 / volume ratio | `#term-volume-ratio` |
| 最近一個月的波動程度 | 已實現波動 / 20D realized volatility | `#term-realized-vol` |
| 今天的風險檢查結果 | 風險狀態 / risk state | `#term-risk-state` |
| 某產業比大盤強或弱多少 | 相對大盤報酬 / relative return | `#term-relative-return` |
| 法人買賣超的中位數 | 法人淨流 / institution net flow | `#term-institution-flow` |

主版面不得出現未配對白話標題的術語字串。術語以 11px 標籤形式保留在白話標題旁，並連到上表對應的錨點 —— **標籤文字必須與它指向的條目是同一個指標**，不是「錨點存在就好」。個股頁與報告頁不重寫這些解釋，一律連回學習頁。
