"""Time-series split and out-of-sample strategy scoring."""

from stock_papi.quant.constants import (
    ENTRY_THRESHOLD,
    PREDICTION_HORIZON,
    ROUND_TRIP_COST,
)


def _compound(returns):
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def summarize_trade_returns(
    entry_returns,
    *,
    gross_period_returns,
    round_trip_cost,
    total_periods,
):
    """只從既有非重疊進場報酬衍生統計，不改變交易選擇。"""
    entries = [float(value) for value in entry_returns]
    profits = [value for value in entries if value > 0]
    losses = [value for value in entries if value <= 0]
    average_profit = sum(profits) / len(profits) if profits else None
    average_loss = sum(losses) / len(losses) if losses else None
    expected_return = sum(entries) / len(entries) if entries else None
    payoff_ratio = (
        average_profit / abs(average_loss)
        if average_profit is not None and average_loss not in (None, 0)
        else None
    )
    loss_total = abs(sum(losses))
    profit_factor = sum(profits) / loss_total if profits and loss_total else None
    longest_winning = longest_losing = current_winning = current_losing = 0
    for value in entries:
        if value > 0:
            current_winning += 1
            current_losing = 0
            longest_winning = max(longest_winning, current_winning)
        else:
            current_losing += 1
            current_winning = 0
            longest_losing = max(longest_losing, current_losing)

    gross = list(gross_period_returns)
    active_periods = sum(value is not None for value in gross)
    cash_ratio = (
        (total_periods - active_periods) / total_periods if total_periods else None
    )

    def scenario(cost_multiplier):
        return _compound(
            [
                0.0 if value is None else float(value) - round_trip_cost * cost_multiplier
                for value in gross
            ]
        ) if gross else None

    return {
        "average_profit": average_profit,
        "average_loss": average_loss,
        "expected_return": expected_return,
        "payoff_ratio": payoff_ratio,
        "profit_factor": profit_factor,
        "longest_winning_streak": longest_winning,
        "longest_losing_streak": longest_losing,
        "cash_period_ratio": cash_ratio,
        "cost_sensitivity": {
            "zero_cost": scenario(0),
            "current_cost": scenario(1),
            "double_cost": scenario(2),
        },
    }


def build_time_splits(n_samples, *, np):
    from sklearn.model_selection import TimeSeriesSplit

    splitter = TimeSeriesSplit(n_splits=5, gap=PREDICTION_HORIZON)
    return list(splitter.split(np.arange(n_samples)))


def score_oos_predictions(future_returns, probabilities, *, pd, np):
    frame = pd.DataFrame({"future": future_returns, "prob": probabilities}).dropna()
    target = (frame["future"] > 0).astype(int)
    sampled = frame.iloc[::PREDICTION_HORIZON]
    entries = sampled["prob"] >= ENTRY_THRESHOLD
    strategy_returns = np.where(entries, sampled["future"] - ROUND_TRIP_COST, 0.0)
    cumulative = np.cumprod(1 + strategy_returns)
    buy_hold = np.cumprod(1 + sampled["future"].to_numpy())
    active = sampled.loc[entries, "future"] - ROUND_TRIP_COST
    trade_summary = summarize_trade_returns(
        active.tolist(),
        gross_period_returns=[
            float(value) if bool(selected) else None
            for value, selected in zip(sampled["future"], entries)
        ],
        round_trip_cost=ROUND_TRIP_COST,
        total_periods=len(sampled),
    )
    mdd = (
        (cumulative / np.maximum.accumulate(cumulative) - 1).min() * 100
        if len(cumulative) else 0.0
    )
    std = np.std(strategy_returns)
    return {
        "days": len(frame),
        "accuracy": ((frame["prob"] >= 0.5).astype(int) == target).mean() * 100,
        "brier": np.mean((frame["prob"] - target) ** 2),
        "strat_cum": (cumulative[-1] - 1) * 100 if len(cumulative) else 0.0,
        "bh_cum": (buy_hold[-1] - 1) * 100 if len(buy_hold) else 0.0,
        "win_rate": (active > 0).mean() * 100 if len(active) else 0.0,
        "trades": int(entries.sum()),
        "mdd": mdd,
        "sharpe": (
            np.mean(strategy_returns) / std * np.sqrt(252 / PREDICTION_HORIZON)
            if std else 0.0
        ),
        **trade_summary,
    }
