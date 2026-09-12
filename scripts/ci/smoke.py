"""部署前後的煙霧測試。

檢查的是「這個 revision 端得出東西」，不是「資料對不對」——
資料正確性由產製端的驗證與 fail-closed 閘門負責，不是這裡。

fail-closed：任何一項無法判定（連不上、JSON 壞掉、欄位缺席）都算不通過。
部署流程裡「不確定」必須當成「不通過」。
"""

import json
import sys
import urllib.error
import urllib.request


TIMEOUT_SECONDS = 30
ATTEMPTS = 5
RETRY_DELAY_SECONDS = 6

# 這些頁面不需要已發布的產物也該回 200。
# /reports 與 /us 刻意不列入：沒有已驗證的報告時它們**應該**回 503，
# 那是 fail-closed 正常運作，不是壞掉。拿它們當煙霧測試會讓
# 「還沒發報告」變成「不准部署」。
REQUIRED_OK = ("/healthz", "/dashboard", "/market", "/stocks", "/learn")


def _get(url, timeout=TIMEOUT_SECONDS):
    request = urllib.request.Request(url, headers={"User-Agent": "absorb-ci"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def _check_pages(base):
    problems = []
    for path in REQUIRED_OK:
        url = base.rstrip("/") + path
        try:
            status, _ = _get(url)
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:  # 連不上也是不通過
            problems.append(f"{path}：{type(error).__name__} {error}")
            continue
        if status != 200:
            problems.append(f"{path}：HTTP {status}")
    return problems


def _check_data_health(base):
    """/health/data 要回得出兩個市場的狀態。

    刻意**不**要求狀態是 current：盤中、假日、或報告還沒發的時候
    updating / unavailable 都是正常的，拿它擋部署會把程式修復也一起擋掉。
    這裡只確認這個端點本身活著而且格式正確 —— 端不出來才是 revision 壞了。
    """
    url = base.rstrip("/") + "/health/data"
    try:
        status, body = _get(url)
    except Exception as error:
        return [f"/health/data：{type(error).__name__} {error}"]
    if status != 200:
        return [f"/health/data：HTTP {status}"]
    try:
        document = json.loads(body.decode("utf-8"))
    except Exception:
        return ["/health/data：回應不是合法 JSON"]
    markets = document.get("markets")
    if not isinstance(markets, dict):
        return ["/health/data：缺少 markets"]
    missing = [name for name in ("TW", "US") if name not in markets]
    if missing:
        return [f"/health/data：缺少市場 {', '.join(missing)}"]
    return []


def run(base):
    import time

    last = None
    for attempt in range(1, ATTEMPTS + 1):
        problems = _check_pages(base) + _check_data_health(base)
        if not problems:
            print(f"煙霧測試通過：{base}")
            return 0
        last = problems
        if attempt < ATTEMPTS:
            # 新 revision 冷啟動要時間，重試是為了等它起來，
            # 不是為了把失敗重試掉 —— 次數用完仍然失敗就是失敗。
            print(f"第 {attempt} 次未通過，{RETRY_DELAY_SECONDS}s 後重試")
            time.sleep(RETRY_DELAY_SECONDS)
    print(f"煙霧測試失敗：{base}", file=sys.stderr)
    for problem in last or []:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：smoke.py <base-url>")
    sys.exit(run(sys.argv[1]))
