"""將已驗證回測指標轉成一般投資人可理解的文字。"""

import math


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ten_thousand(amount):
    value = amount / 10_000
    return f"{value:.1f}".rstrip("0").rstrip(".")


def interpret_backtest(metrics, *, initial_amount=100_000):
    strategy = _number(metrics.get("strat_cum"))
    buy_hold = _number(metrics.get("bh_cum"))
    drawdown = _number(metrics.get("mdd"))
    win_rate = _number(metrics.get("win_rate"))
    cash_ratio = _number(metrics.get("cash_period_ratio"))
    sharpe = _number(metrics.get("sharpe"))
    brier = _number(metrics.get("brier"))

    if strategy is None or buy_hold is None:
        advantage = "資料不足：目前無法比較策略與單純買進持有。"
    elif strategy > buy_hold:
        advantage = "過去相同規則的結果優於單純買進持有，但不代表未來仍會維持。"
    else:
        advantage = "過去相同規則未優於單純買進持有，暫無足夠歷史優勢。"

    cumulative = (
        f"投入 10 萬元，歷史結果約變成 {_ten_thousand(initial_amount * (1 + strategy / 100))} 萬元。"
        if strategy is not None
        else "資料不足：無法換算歷史累積報酬。"
    )
    maximum_drawdown = (
        f"最差階段，10 萬元可能一度剩下約 {_ten_thousand(initial_amount * (1 - abs(drawdown) / 100))} 萬元。"
        if drawdown is not None
        else "資料不足：無法換算最差資金跌幅。"
    )
    win_text = (
        f"每 100 次進場約有 {round(win_rate)} 次獲利；勝率不代表每次盈虧相同。"
        if win_rate is not None
        else "資料不足：目前沒有可靠的策略交易勝率。"
    )
    cash_text = (
        f"約 {round(cash_ratio * 100)}% 的再平衡期間沒有進場。"
        if cash_ratio is not None
        else "資料不足：目前無法判斷空手比例。"
    )
    sharpe_text = (
        f"報酬效率（Sharpe Ratio）為 {sharpe:.2f}，用來比較承擔波動後的歷史報酬。"
        if sharpe is not None
        else "資料不足：目前無法計算報酬效率。"
    )
    brier_text = (
        f"機率可信度（Brier Score）為 {brier:.3f}；它檢查模型說 60% 時，歷史實際上漲率是否接近 60%。"
        if brier is not None
        else "資料不足：目前無法檢查模型機率是否準確。"
    )
    return {
        "advantage": advantage,
        "cumulative_return": cumulative,
        "maximum_drawdown": maximum_drawdown,
        "win_rate": win_text,
        "cash_ratio": cash_text,
        "sharpe": sharpe_text,
        "brier": brier_text,
    }
