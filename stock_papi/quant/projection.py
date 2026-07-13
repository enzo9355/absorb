import math


def _annualized_percent(total_percent, days):
    if not days or days <= 0 or total_percent <= -100:
        return None
    return ((1 + total_percent / 100) ** (252 / days) - 1) * 100


def calculate_investment_projection(amount, data):
    try:
        amount = float(amount)
        price = float(data["price"])
        bt = data["bt"]
    except (KeyError, TypeError, ValueError):
        return {"ok": False}
    if amount <= 0 or price <= 0:
        return {"ok": False}
    shares = int(amount // price)
    if shares <= 0:
        return {"ok": False}
    deployed = shares * price
    strat = float(bt.get("strat_cum", 0))
    buy_hold = float(bt.get("bh_cum", 0))
    days = int(bt.get("days", 0))
    return {
        "ok": True,
        "amount": amount,
        "shares": shares,
        "deployed_amount": deployed,
        "strategy_profit": deployed * strat / 100,
        "buy_hold_profit": deployed * buy_hold / 100,
        "strategy_annualized": _annualized_percent(strat, days),
        "buy_hold_annualized": _annualized_percent(buy_hold, days),
    }
