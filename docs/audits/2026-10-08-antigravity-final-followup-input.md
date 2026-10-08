最後補充，請對目前最新差異複核，繁體中文 600 字內，不使用工具或修改檔案。
你上次已確認無新增可操作 P1/P2；我另外找到黑名單外的自然語句「台積電資料日那天偏強還是偏弱？」仍會被吞掉分析。已先重現失敗，再在純日期判定加上封閉的日期／來源 suffix 檢查，未知 suffix 一律保留分析路徑。原始純日期來源問題仍通過；擴充相關回歸現在 323 項全部通過。下面附最新函式與新增 JS 可執行檢查。
完整 unittest discover 首次結果：1903 項，2 failures，2 skipped，其餘 1899 passed。兩失敗為既有 test_pipeline_scheduler 的 abandoned mutex 和 US 重試窗口（測試期待5h、腳本為12h）。我以 git show fa1cf7c 將 tests/test_pipeline_scheduler.py、scripts/invoke_pipeline_task.ps1、scripts/install_pipeline_tasks.ps1 放進臨時目錄，只跑這兩項，亦重現同樣兩個失敗；三檔與目前程式相同。本次沒有修改或註冊排程。最新日期邊界之後正在再跑完整測試，不宣稱全部綠燈。
是否有最新變更引入的可操作 P1/P2？請同時確認網站修正可保存為本機提交，但正式部署仍保留既有排程與資料阻擋限制。不要把兩個基底失敗改寫成測試通過，也不用重新評分。
最新日期意圖函式：
def _observation_date_intent(question):
    explicit_date = any(term in question for term in ("資料日", "資料截至", "過期", "更新時間"))
    if not explicit_date and "最新資料" not in question:
        return None
    analysis = any(term in question.lower() for term in (
        "價格", "價位", "收盤", "均線", "走勢", "表現", "報酬", "漲跌", "指標",
        "量比", "成交", "籌碼", "風險事件", "摘要", "內容", "說明", "多少",
        "幾元", "如何", "怎麼", "rsi", "macd", "ma20", "ma60",
    ))
    if explicit_date and not analysis:
        suffix = re.split(r"資料日|資料截至|過期|更新時間", question, maxsplit=1)[1]
        # Unknown suffixes keep the analysis path rather than dropping a second request.
        if re.fullmatch(
            r"(?:[？?。.!！,，、：:；;\s]|資料日|資料截至|過期|狀態|更新時間|哪一天|哪天|幾號|何時|日期|時間|"
            r"什麼時候|是不是|是否|有沒有|已經|是|到|為|的|了|嗎|呢|與|和|及|請|附上|附|提供|可驗證|來源|連結|出處)*",
            suffix,
        ):
            return "only"
    return "mixed"


def _with_observation_freshness(answer, date_answer):
    if date_answer is None:
JS 執行檢查（已通過）：
// Run: node tests/check_dashboard_focus.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let active = false;
let rendered = [];
const focus = {replaceChildren(...items) { rendered = items; }};
const document = {
  body: {dataset: {}},
  querySelector(selector) { return active && selector === '[data-daily-focus]' ? focus : null; },
  querySelectorAll() { return []; }, addEventListener() {},
  createElement() { return {children: [], setAttribute() {}, append(child) { this.children.push(child); }}; },
};
const context = {document, window: {location: {pathname: '/stocks', hash: ''}, addEventListener() {}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
active = true;
context.renderDashboard({product_mode: 'observation', daily_focus: [null, 23, {}, '市場風險狀態：normal']});
assert.equal(rendered.length, 1);
assert.equal(rendered[0].children[1].textContent, '市場風險狀態：一般');
context.renderDashboard({product_mode: 'observation', daily_focus: null});
assert.equal(rendered[0].textContent, '今日焦點資料不足。');
console.log('PASS: actual app.js ignores non-string focus items and handles a null list.');

基底重現結果：
{
  "baseline": "fa1cf7c8cd02b5dfed092ded5ad5f74eabe9978d",
  "files_unchanged": {
    "tests/test_pipeline_scheduler.py": true,
    "scripts/invoke_pipeline_task.ps1": true,
    "scripts/install_pipeline_tasks.ps1": true
  },
  "tests_run": 2,
  "failures": [
    "test_mutex_abandonment_and_partial_timeout_release_exactly_once",
    "test_us_post_close_retries_through_yahoo_eod_finalization"
  ],
  "errors": []
}
