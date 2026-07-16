"""Purged walk-forward splits and strict research evaluation metrics."""

from __future__ import annotations

import math


PURGE_SESSIONS = 5
EMBARGO_SESSIONS = 5
ROUND_TRIP_COST = 0.00585


def build_split_plan(
    dates,
    *,
    fold_count=3,
    purge_sessions=PURGE_SESSIONS,
    embargo_sessions=EMBARGO_SESSIONS,
    final_holdout_fraction=0.20,
):
    unique = sorted({str(value) for value in dates})
    if (
        len(unique) < 80
        or type(fold_count) is not int
        or fold_count < 2
        or purge_sessions < 5
        or embargo_sessions < 5
        or not 0.1 <= final_holdout_fraction <= 0.3
    ):
        raise ValueError("insufficient dates or invalid split policy")
    holdout_size = max(10, int(len(unique) * final_holdout_fraction))
    holdout_start = len(unique) - holdout_size
    gap_size = purge_sessions + embargo_sessions
    development_end = holdout_start - gap_size
    if development_end < 50:
        raise ValueError("development partition is too small")
    development = unique[:development_end]
    final_gap = unique[development_end:holdout_start]
    holdout = unique[holdout_start:]

    initial_train_size = max(30, len(development) // 2)
    available = (
        len(development)
        - initial_train_size
        - purge_sessions
        - embargo_sessions * (fold_count - 1)
    )
    validation_size = available // fold_count
    if validation_size < 5:
        raise ValueError("walk-forward validation windows are too small")
    folds = []
    validation_start = initial_train_size + purge_sessions
    for index in range(fold_count):
        train_end = validation_start - purge_sessions
        validation_end = (
            len(development)
            if index == fold_count - 1
            else validation_start + validation_size
        )
        train_dates = development[:train_end]
        validation_dates = development[validation_start:validation_end]
        if len(train_dates) < 30 or len(validation_dates) < 5:
            raise ValueError("walk-forward fold is too small")
        folds.append(
            {
                "fold": index,
                "train_dates": train_dates,
                "purge_dates": development[train_end:validation_start],
                "validation_dates": validation_dates,
                "embargo_dates": development[
                    validation_end : validation_end + embargo_sessions
                ],
            }
        )
        validation_start = validation_end + embargo_sessions
    return {
        "method": "expanding_walk_forward",
        "purge_sessions": purge_sessions,
        "embargo_sessions": embargo_sessions,
        "selection_uses_final_holdout": False,
        "development_dates": development,
        "final_gap_dates": final_gap,
        "final_holdout_dates": holdout,
        "walk_forward_folds": folds,
    }


def _as_numpy(values, dtype=float):
    import numpy as np

    return np.asarray(values, dtype=dtype)


def _clip_probability(values):
    import numpy as np

    return np.clip(_as_numpy(values, float), 1e-9, 1.0 - 1e-9)


def _roc_auc(target, probability):
    import numpy as np

    target = _as_numpy(target, int)
    probability = _as_numpy(probability, float)
    positives = int(target.sum())
    negatives = len(target) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(probability, kind="mergesort")
    ranks = np.empty(len(probability), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while (
            end < len(order)
            and probability[order[end]] == probability[order[start]]
        ):
            end += 1
        average_rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    rank_sum = float(ranks[target == 1].sum())
    return (
        rank_sum - positives * (positives + 1) / 2.0
    ) / (positives * negatives)


def _calibration(target, probability):
    import numpy as np

    target = _as_numpy(target, float)
    probability = _clip_probability(probability)
    if len(target) < 10 or len(set(target.tolist())) < 2:
        return None, None
    logit = np.log(probability / (1.0 - probability))
    values = np.column_stack((np.ones(len(logit)), logit))
    beta = np.array(
        [
            math.log(target.mean() / (1.0 - target.mean())),
            1.0,
        ],
        dtype=float,
    )
    for _ in range(50):
        linear = np.clip(values @ beta, -30.0, 30.0)
        fitted = 1.0 / (1.0 + np.exp(-linear))
        weights = np.maximum(fitted * (1.0 - fitted), 1e-8)
        gradient = values.T @ (target - fitted)
        information = values.T @ (weights[:, None] * values)
        information += np.eye(2) * 1e-8
        try:
            step = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            return None, None
        beta += step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return float(beta[0]), float(beta[1])


def _ece(target, probability, bins=10):
    import numpy as np

    target = _as_numpy(target, float)
    probability = _clip_probability(probability)
    positions = np.minimum((probability * bins).astype(int), bins - 1)
    value = 0.0
    for index in range(bins):
        selected = positions == index
        count = int(selected.sum())
        if count:
            value += (
                abs(
                    float(probability[selected].mean())
                    - float(target[selected].mean())
                )
                * count
                / len(target)
            )
    return float(value)


def classification_metrics(target, probability):
    import numpy as np

    target = _as_numpy(target, int)
    probability = _clip_probability(probability)
    if (
        len(target) != len(probability)
        or len(target) < 2
        or not np.isin(target, (0, 1)).all()
    ):
        raise ValueError("classification inputs are invalid")
    prevalence = float(target.mean())
    intercept, slope = _calibration(target, probability)
    return {
        "observations": int(len(target)),
        "positive_rate": prevalence,
        "accuracy_at_0_5": float(
            np.mean((probability >= 0.5) == target)
        ),
        "majority_accuracy": max(prevalence, 1.0 - prevalence),
        "brier": float(np.mean((probability - target) ** 2)),
        "log_loss": float(
            -np.mean(
                target * np.log(probability)
                + (1 - target) * np.log1p(-probability)
            )
        ),
        "roc_auc": _roc_auc(target, probability),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "ece_10": _ece(target, probability, 10),
    }


def _ranked_frame(frame, score_column):
    import pandas as pd

    required = {
        "symbol",
        "source_market_date",
        "future_return_5",
        score_column,
    }
    if not required.issubset(frame.columns):
        raise ValueError("ranking frame is missing required columns")
    ranked = frame[list(required)].copy()
    ranked = ranked.dropna()
    ranked["score_rank"] = ranked.groupby("source_market_date")[
        score_column
    ].rank(method="average", pct=True)
    ranked["return_rank"] = ranked.groupby("source_market_date")[
        "future_return_5"
    ].rank(method="average", pct=True)
    return pd.DataFrame(ranked)


def ranking_metrics(frame, *, score_column="score"):
    import numpy as np

    ranked = _ranked_frame(frame, score_column)
    daily_ic = []
    spreads = []
    top_sets = []
    for date, selected in ranked.groupby("source_market_date", sort=True):
        if len(selected) < 10:
            continue
        correlation = selected["score_rank"].corr(selected["return_rank"])
        if correlation is not None and math.isfinite(float(correlation)):
            daily_ic.append(float(correlation))
        top = selected[selected["score_rank"] > 0.90]
        bottom = selected[selected["score_rank"] <= 0.10]
        if len(top) and len(bottom):
            spreads.append(
                float(
                    top["future_return_5"].mean()
                    - bottom["future_return_5"].mean()
                )
            )
        top_sets.append((str(date), set(top["symbol"].astype(str))))
    turnover = []
    for (_, previous), (_, current) in zip(top_sets, top_sets[1:]):
        union = previous | current
        if union:
            turnover.append(1.0 - len(previous & current) / len(union))
    return {
        "source_dates": len(top_sets),
        "spearman_ic": float(np.mean(daily_ic)) if daily_ic else None,
        "spearman_ic_std": float(np.std(daily_ic)) if daily_ic else None,
        "top_decile_spread": float(np.mean(spreads)) if spreads else None,
        "turnover": float(np.mean(turnover)) if turnover else None,
    }


def _top_decile(frame, score_column):
    selected = frame.copy()
    selected["score_rank"] = selected.groupby("source_market_date")[
        score_column
    ].rank(method="first", pct=True)
    return selected[selected["score_rank"] > 0.90]


def transaction_metrics(
    frame,
    *,
    score_column="score",
    round_trip_cost=ROUND_TRIP_COST,
):
    import numpy as np

    required = {
        "source_market_date",
        "future_return_5",
        "close",
        "volume",
        score_column,
    }
    if not required.issubset(frame.columns):
        raise ValueError("transaction frame is missing required columns")
    selected = _top_decile(frame[list(required)].dropna(), score_column)
    if selected.empty:
        raise ValueError("top decile transaction sample is empty")
    daily_gross = selected.groupby("source_market_date")[
        "future_return_5"
    ].mean()
    gross = float(daily_gross.mean())
    slippage = {}
    for basis_points in (0, 10, 25, 50):
        extra = basis_points / 10_000.0
        slippage[f"{basis_points}_bps"] = gross - round_trip_cost - extra

    dollar_volume = (
        selected["close"].astype(float) * selected["volume"].astype(float)
    ).clip(lower=1.0)
    capacity = {}
    for notional in (1_000_000, 5_000_000, 10_000_000):
        position_notional = notional / max(
            1, int(selected.groupby("source_market_date").size().median())
        )
        participation = position_notional / dollar_volume
        impact = np.minimum(
            0.05,
            0.001
            * np.sqrt(
                np.maximum(participation.to_numpy(dtype=float), 0.0)
                / 0.01
            ),
        )
        capacity[str(notional)] = {
            "median_participation": float(np.median(participation)),
            "estimated_round_trip_impact": float(np.median(impact)),
            "net_return": (
                gross - round_trip_cost - float(np.median(impact))
            ),
        }
    return {
        "top_decile_observations": int(len(selected)),
        "source_dates": int(daily_gross.shape[0]),
        "gross_return": gross,
        "round_trip_cost": round_trip_cost,
        "net_return_after_base_cost": gross - round_trip_cost,
        "slippage_scenarios": slippage,
        "capacity_method": (
            "equal-weight positions; square-root impact scaled to one percent "
            "participation; explicit market-cap Gate remains separate"
        ),
        "capacity_scenarios": capacity,
    }


def stability_metrics(
    frame,
    *,
    score_column="score",
    bootstrap_iterations=500,
    seed=20260717,
):
    import numpy as np

    if bootstrap_iterations < 50:
        raise ValueError("bootstrap_iterations is too small")
    source = frame.copy()
    source["month"] = source["source_market_date"].astype(str).str[:7]
    monthly = []
    for month, selected in source.groupby("month", sort=True):
        if len(selected) < 20 or selected["direction_5"].nunique() < 2:
            continue
        monthly.append(
            {
                "month": str(month),
                **classification_metrics(
                    selected["direction_5"],
                    selected[score_column],
                ),
            }
        )

    top = _top_decile(source, score_column)
    daily = (
        top.groupby("source_market_date")["future_return_5"].mean()
        - ROUND_TRIP_COST
    ).to_numpy(dtype=float)
    if not len(daily):
        raise ValueError("bootstrap source dates are unavailable")
    rng = np.random.default_rng(seed)
    draws = daily[
        rng.integers(0, len(daily), size=(bootstrap_iterations, len(daily)))
    ].mean(axis=1)
    return {
        "sample_count": int(len(source)),
        "source_date_count": int(source["source_market_date"].nunique()),
        "monthly": monthly,
        "industry": {
            "status": "NOT_RUN",
            "reason": "frozen point-in-time industry membership is unavailable",
        },
        "market_regime": {
            "status": "NOT_RUN",
            "reason": "validated point-in-time market regime labels are unavailable",
        },
        "bootstrap_ci": {
            "method": "source-date cluster bootstrap",
            "iterations": bootstrap_iterations,
            "seed": seed,
            "top_decile_net_return": {
                "estimate": float(daily.mean()),
                "lower": float(np.quantile(draws, 0.025)),
                "upper": float(np.quantile(draws, 0.975)),
            },
        },
    }


def evaluate_prediction_result(
    frame,
    result,
    *,
    bootstrap_iterations=500,
):
    if result.get("status") != "RUN":
        return {
            "status": result.get("status", "NOT_RUN"),
            "reason": result.get("reason"),
            "dependencies": result.get("dependencies", []),
        }
    evaluated = {
        "status": "RUN",
        "features": list(result.get("features") or []),
        "fit_source": result.get("fit_source"),
        "fit_evidence": result.get("fit_evidence"),
    }
    for partition_name in ("validation", "holdout"):
        partition = result[partition_name]
        selected = frame.iloc[partition["indices"]].copy()
        selected["score"] = partition["probability"]
        evaluated[
            "final_holdout" if partition_name == "holdout" else partition_name
        ] = {
            "classification": classification_metrics(
                selected["direction_5"], selected["score"]
            ),
            "ranking": ranking_metrics(selected, score_column="score"),
            "transaction": transaction_metrics(
                selected, score_column="score"
            ),
            "stability": stability_metrics(
                selected,
                score_column="score",
                bootstrap_iterations=bootstrap_iterations,
            ),
        }
    return evaluated


def evaluate_ranking_result(
    frame,
    result,
    *,
    bootstrap_iterations=500,
):
    import numpy as np

    if result.get("status") != "RUN":
        return {
            "status": result.get("status", "NOT_RUN"),
            "reason": result.get("reason"),
            "dependencies": result.get("dependencies", []),
        }
    evaluated = {
        "status": "RUN",
        "features": list(result.get("features") or []),
        "fit_source": result.get("fit_source"),
        "fit_evidence": result.get("fit_evidence"),
    }
    rng = np.random.default_rng(20260717)
    for partition_name in ("validation", "holdout"):
        partition = result[partition_name]
        selected = frame.iloc[partition["indices"]].copy()
        selected["score"] = partition["score"]
        ranking = ranking_metrics(selected, score_column="score")
        transaction = transaction_metrics(selected, score_column="score")
        monthly = []
        local = selected.copy()
        local["month"] = (
            local["source_market_date"].astype(str).str[:7]
        )
        for month, values in local.groupby("month", sort=True):
            if values["source_market_date"].nunique() < 5:
                continue
            monthly.append(
                {
                    "month": str(month),
                    **ranking_metrics(values, score_column="score"),
                }
            )
        top = _top_decile(selected, "score")
        daily = (
            top.groupby("source_market_date")["future_return_5"].mean()
            - ROUND_TRIP_COST
        ).to_numpy(dtype=float)
        draws = daily[
            rng.integers(
                0,
                len(daily),
                size=(bootstrap_iterations, len(daily)),
            )
        ].mean(axis=1)
        evaluated[
            "final_holdout" if partition_name == "holdout" else partition_name
        ] = {
            "ranking": ranking,
            "transaction": transaction,
            "stability": {
                "monthly": monthly,
                "industry": {
                    "status": "NOT_RUN",
                    "reason": (
                        "frozen point-in-time industry membership is unavailable"
                    ),
                },
                "bootstrap_ci": {
                    "top_decile_net_return": {
                        "estimate": float(daily.mean()),
                        "lower": float(np.quantile(draws, 0.025)),
                        "upper": float(np.quantile(draws, 0.975)),
                    }
                },
            },
        }
    return evaluated
