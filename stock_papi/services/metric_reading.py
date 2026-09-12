"""市場指標的白話解讀（規格書 §5.3 第 3 層）。

為什麼放在服務層而不是模板：解讀必須是數值的函式。寫在模板裡的話，
數值變了解讀不會變，會產生錯誤陳述 —— 那是規格書明文禁止的。
放在批次產生器裡也不對：那會改動已發布產物的內容雜湊，而且既有產物
不會回填。這裡在呈現層由已發布的數值推導，所有歷史產物立即適用。

規則：
- 只陳述**這個數值本身**與**它跨過了哪個門檻**。
- 不比較「近三個月平均」這類手上沒有的東西。
- 不做方向性推論。廣度高不等於會漲，波動大不等於要減碼。
"""

from __future__ import annotations


# 與 stock_papi/batch/observation_products.py 的 risk_state 判定共用同一組門檻。
# 兩邊若各寫各的，畫面會出現「波動程度：一般」配「風險狀態：升高」這種
# 自我矛盾的組合。
VOLATILITY_ELEVATED_PCT = 25.0
VOLATILITY_CAUTIOUS_PCT = 20.0

BREADTH_BROAD_PCT = 60.0
BREADTH_NARROW_PCT = 40.0

VOLUME_ACTIVE_RATIO = 1.5
VOLUME_QUIET_RATIO = 0.7


def _breadth_reading(value):
    if value >= BREADTH_BROAD_PCT:
        return f"{value:.1f}% 的股票收在近一個月平均價之上，參與的家數偏多。"
    if value <= BREADTH_NARROW_PCT:
        return f"只有 {value:.1f}% 的股票收在近一個月平均價之上，參與的家數偏少。"
    return f"{value:.1f}% 的股票收在近一個月平均價之上，多空分布接近均衡。"


def _volume_reading(value):
    if value >= VOLUME_ACTIVE_RATIO:
        return f"成交量是近期常態的 {value:.2f} 倍，交易明顯活躍。"
    if value <= VOLUME_QUIET_RATIO:
        return f"成交量只有近期常態的 {value:.2f} 倍，交易偏清淡。"
    return f"成交量是近期常態的 {value:.2f} 倍，與平常相近。"


def _volatility_reading(value):
    if value >= VOLATILITY_ELEVATED_PCT:
        return f"年化 {value:.1f}%，已越過風險檢查的升高門檻（{VOLATILITY_ELEVATED_PCT:.0f}%）。"
    if value >= VOLATILITY_CAUTIOUS_PCT:
        return f"年化 {value:.1f}%，已越過風險檢查的謹慎門檻（{VOLATILITY_CAUTIOUS_PCT:.0f}%）。"
    return f"年化 {value:.1f}%，低於風險檢查的兩道門檻。"


def _risk_reading(state, market):
    """說明這個狀態是被什麼推動的。

    判定規則見 observation_products._market_observation：
    下跌家數多於上漲家數，且（創新低家數多於創新高，或波動越過升高門檻）→ elevated；
    下跌多於上漲，或波動越過謹慎門檻 → cautious；否則 normal。
    """
    advancing = market.get("advancing_count")
    declining = market.get("declining_count")
    new_highs = market.get("new_high_20d_count")
    new_lows = market.get("new_low_20d_count")
    volatility = market.get("realized_volatility_20d_pct")

    drivers = []
    if isinstance(declining, int) and isinstance(advancing, int) and declining > advancing:
        drivers.append(f"下跌家數（{declining}）多於上漲家數（{advancing}）")
    if isinstance(new_lows, int) and isinstance(new_highs, int) and new_lows > new_highs:
        drivers.append(f"創近月新低（{new_lows}）多於創新高（{new_highs}）")
    if isinstance(volatility, (int, float)):
        if volatility >= VOLATILITY_ELEVATED_PCT:
            drivers.append(f"波動年化 {volatility:.1f}% 越過升高門檻")
        elif volatility >= VOLATILITY_CAUTIOUS_PCT:
            drivers.append(f"波動年化 {volatility:.1f}% 越過謹慎門檻")

    if state == "normal":
        return "三項檢查都沒有越過門檻。這只描述已經發生的波動，不預告接下來會發生什麼。"
    if not drivers:
        # 狀態與可見欄位對不上時，寧可不解釋，也不要編一個理由
        return None
    return "由以下條件觸發：" + "、".join(drivers) + "。"


def market_metric_readings(market):
    """回傳 {指標鍵: 解讀字串}。缺值的指標不會出現在結果裡。"""
    if not isinstance(market, dict):
        return {}

    readings = {}
    breadth = market.get("ma20_breadth_pct")
    if isinstance(breadth, (int, float)) and not isinstance(breadth, bool):
        readings["ma20_breadth_pct"] = _breadth_reading(float(breadth))

    volume = market.get("median_volume_ratio")
    if isinstance(volume, (int, float)) and not isinstance(volume, bool):
        readings["median_volume_ratio"] = _volume_reading(float(volume))

    volatility = market.get("realized_volatility_20d_pct")
    if isinstance(volatility, (int, float)) and not isinstance(volatility, bool):
        readings["realized_volatility_20d_pct"] = _volatility_reading(float(volatility))

    state = market.get("risk_state")
    if state in ("normal", "cautious", "elevated"):
        reading = _risk_reading(state, market)
        if reading:
            readings["risk_state"] = reading

    return readings
