"""Time-series split and out-of-sample strategy scoring."""

from stock_papi.quant.constants import (
    ENTRY_THRESHOLD,
    PREDICTION_HORIZON,
    ROUND_TRIP_COST,
)


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
    }
