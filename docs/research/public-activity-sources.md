# 公開操作來源與核對紀錄（交易助手 v1）

日期：2026-09-24（Asia/Taipei）。本文件只記錄已核對範圍，不承諾即時更新。

## 來源一覽

| 來源 | 用途 | 使用依據狀態 | 最近核對 |
|---|---|---|---|
| X @aleabitoreddit 公開貼文（FxTwitter 取得＋官方 oEmbed 交叉核對） | 自述持倉／公開觀點（TW 3006） | 已核對作者與 permalink；頁面只保存人工摘要，不重發全文 | 2026-09-18T01:07:19+08:00（沿用既有 catalog coverage） |
| 美國眾議院 PTR（ethics.house.gov / disclosure.house.gov） | Pelosi 家庭交易揭露 | pending：使用範圍與 5 USC 13107(c) 商業用途限制尚未確認；只保留官方來源入口，不匯入第三方轉載 | 未開放（pending） |
| SEC 13F（sec.gov） | Berkshire 機構季底持倉 | source_only：申報為季底持倉、季末後 45 日內提交，不含完整空頭；需按文件核對金額單位；本次未匯入可比較兩期 | 未開放（source_only） |

- 政治人物交易 feed 未完成：Pelosi–INTC 在目前已核對範圍內未找到匹配紀錄（未證實≠沒有買）。頁面顯示檢查範圍與原始查詢入口，不以其他股票替代。
- 13F 僅在同一機構、相鄰季度、同一證券／股別／期權類型／數量單位、兩期完整可比較時顯示增加／減少／新出現／未再列示；否則不推導清倉。
- 試用期間每天人工查核一次已納入來源；頁面標「最近核對時間」。zero_new（無新資料）與 failure（抓取失敗）分開記錄。

## 操作種子資料

- `serenity-tw-3006-self-001`：TW 3006 自述持倉（self_reported_trade 的持倉揭露，交易日未揭露）。
  - 主體：serenity-author（person，X @aleabitoreddit，identity verified，來源 https://x.com/aleabitoreddit）。
  - 證券：TW 3006 普通股；動作：holding（原文僅揭露持倉，未揭露交易日、數量、成本）。
  - 來源：https://x.com/aleabitoreddit/status/2099411795131924487（house 種子以 X post 作為自述來源；rights approved 僅限人工摘要）。
  - 公開日：2026-09-14T08:15:51Z；first_seen 2026-09-17T06:49:06Z；reviewed 2026-09-18T01:07:19+08:00。
  - 限制：未揭露交易日／數量／成本；不推定買入時點與報酬；不進交易計畫的進場觸發（instrument 為 common_stock 但無交易日，僅作來源紀錄展示）。
- Pelosi 家庭（pelosi-household，household）：身份來源 https://ethics.house.gov，identity pending；無已核對活動。INTC 未證實。
- Berkshire（berkshire-hathaway，institution）：身份來源 https://www.sec.gov，source_only；無已核對持倉快照。未宣稱 Buffett 本人下單。

## 法律與營運界線（摘要，非法律意見）

- 眾議院 PTR 一般期限為知悉交易後 30 日或交易後 45 日較早者，部分申報門檻超過 1,000 美元；產品保留交易與揭露兩日期，不稱即時追蹤。
- 5 USC 13107(c) 對報告商業用途有限制與新聞傳播例外；未確認試用依據前不商品化，只留官方入口。
- 投信投顧法第 4、6 條：免費同學試用非自動豁免；收費／公開招攬／個人化配置前另行確認。
