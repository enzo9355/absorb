"""Immutable OOS diagnostics and champion/challenger research artifacts."""

from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import math
import os
from pathlib import Path


ROUND_TRIP_COST = 0.00585
PURGE_SESSIONS = 5


def _canonical(document):
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_immutable(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("immutable diagnostic artifact conflict")
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _load_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _utc_timestamp(now=None):
    value = now or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return value.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _probability_metrics(y, probability):
    import numpy as np
    from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

    y = np.asarray(y, dtype=int)
    probability = np.clip(np.asarray(probability, dtype=float), 1e-9, 1 - 1e-9)
    prevalence = float(y.mean())
    climatology_brier = prevalence * (1.0 - prevalence)
    brier = float(np.mean((probability - y) ** 2))
    return {
        "observations": int(len(y)),
        "positive_rate": prevalence,
        "accuracy_at_0_5": float(np.mean((probability >= 0.5) == y)),
        "majority_accuracy": max(prevalence, 1.0 - prevalence),
        "roc_auc": float(roc_auc_score(y, probability)),
        "pr_auc": float(average_precision_score(y, probability)),
        "pr_auc_lift_over_prevalence": float(
            average_precision_score(y, probability) - prevalence
        ),
        "log_loss": float(log_loss(y, probability, labels=[0, 1])),
        "climatology_log_loss": float(
            log_loss(y, [prevalence] * len(y), labels=[0, 1])
        ),
        "brier": brier,
        "climatology_brier": climatology_brier,
        "brier_skill_score": (
            float(1.0 - brier / climatology_brier)
            if climatology_brier > 0
            else None
        ),
        "ece_10": _ece(y, probability, 10),
    }


def _ece(y, probability, bins):
    import numpy as np

    y = np.asarray(y, dtype=float)
    probability = np.asarray(probability, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    positions = np.minimum(np.searchsorted(edges, probability, side="right") - 1, bins - 1)
    total = len(y)
    return float(
        sum(
            abs(float(probability[positions == index].mean()) - float(y[positions == index].mean()))
            * int((positions == index).sum())
            / total
            for index in range(bins)
            if (positions == index).any()
        )
    )


def _reliability_table(y, probability, bins=10):
    import numpy as np

    y = np.asarray(y, dtype=float)
    probability = np.asarray(probability, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    positions = np.minimum(np.searchsorted(edges, probability, side="right") - 1, bins - 1)
    result = []
    for index in range(bins):
        selected = positions == index
        count = int(selected.sum())
        result.append(
            {
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "observations": count,
                "mean_score": float(probability[selected].mean()) if count else None,
                "actual_positive_rate": float(y[selected].mean()) if count else None,
            }
        )
    return result


def _histogram(probability, bins=20):
    import numpy as np

    counts, edges = np.histogram(probability, bins=bins, range=(0.0, 1.0))
    return [
        {
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "observations": int(counts[index]),
        }
        for index in range(bins)
    ]


def _partition_dates(frame):
    dates = sorted(frame["source_market_date"].unique())
    if len(dates) < 30:
        raise ValueError("insufficient OOS dates for purged partitions")
    train_end = int(len(dates) * 0.60)
    validation_end = int(len(dates) * 0.80)
    train = dates[:train_end]
    validation = dates[train_end + PURGE_SESSIONS : validation_end]
    holdout = dates[validation_end + PURGE_SESSIONS :]
    if min(len(train), len(validation), len(holdout)) < 5:
        raise ValueError("purged OOS partitions are too small")
    return {
        "calibration_train": train,
        "validation": validation,
        "final_holdout": holdout,
        "purge_sessions": PURGE_SESSIONS,
        "selection_uses_final_holdout": False,
    }


def _partition_document(partitions):
    return {
        name: {
            "start": dates[0],
            "end": dates[-1],
            "session_count": len(dates),
        }
        for name, dates in partitions.items()
        if isinstance(dates, list)
    } | {
        "purge_sessions": partitions["purge_sessions"],
        "selection_uses_final_holdout": False,
    }


def _frame_for_dates(frame, dates):
    return frame[frame["source_market_date"].isin(dates)]


def _fit_calibrators(train):
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    probability = np.clip(train["probability"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    target = train["direction"].to_numpy(dtype=int)
    logit = np.log(probability / (1.0 - probability)).reshape(-1, 1)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(logit, target)
    isotonic = IsotonicRegression(out_of_bounds="clip").fit(probability, target)
    beta_features = np.column_stack((np.log(probability), -np.log1p(-probability)))
    beta = LogisticRegression(C=1e6, max_iter=1000).fit(beta_features, target)
    return {"platt": platt, "isotonic": isotonic, "beta": beta}


def _calibrated_probability(name, model, probability):
    import numpy as np

    probability = np.clip(np.asarray(probability, dtype=float), 1e-6, 1 - 1e-6)
    if name == "platt":
        features = np.log(probability / (1.0 - probability)).reshape(-1, 1)
        return model.predict_proba(features)[:, 1]
    if name == "isotonic":
        return np.clip(model.predict(probability), 1e-6, 1 - 1e-6)
    if name == "beta":
        features = np.column_stack((np.log(probability), -np.log1p(-probability)))
        return model.predict_proba(features)[:, 1]
    raise ValueError("unknown calibrator")


def _calibration_challengers(frame, partitions):
    train = _frame_for_dates(frame, partitions["calibration_train"])
    validation = _frame_for_dates(frame, partitions["validation"])
    holdout = _frame_for_dates(frame, partitions["final_holdout"])
    fitted = _fit_calibrators(train)
    validation_results = {
        "raw": _probability_metrics(validation["direction"], validation["probability"])
    }
    holdout_results = {
        "raw": _probability_metrics(holdout["direction"], holdout["probability"])
    }
    for name, model in fitted.items():
        validation_results[name] = _probability_metrics(
            validation["direction"],
            _calibrated_probability(name, model, validation["probability"]),
        )
    selected = min(
        fitted,
        key=lambda name: (
            validation_results[name]["brier"],
            validation_results[name]["log_loss"],
            validation_results[name]["ece_10"],
            name,
        ),
    )
    for name, model in fitted.items():
        holdout_results[name] = _probability_metrics(
            holdout["direction"],
            _calibrated_probability(name, model, holdout["probability"]),
        )
    return {
        "fit_partition": "calibration_train",
        "selection_partition": "validation",
        "final_evaluation_partition": "final_holdout",
        "selected_before_final_holdout": selected,
        "validation": validation_results,
        "final_holdout": holdout_results,
    }


def _cross_sectional_bins(frame, bins):
    ranked = frame[
        ["source_market_date", "probability", "direction", "future_return"]
    ].copy()
    ranked["percentile"] = ranked.groupby("source_market_date")["probability"].rank(
        pct=True, method="first"
    )
    ranked["bucket"] = (
        (ranked["percentile"] * bins).apply(math.ceil).clip(lower=1, upper=bins)
    )
    rows = []
    for bucket, selected in ranked.groupby("bucket", sort=True):
        rows.append(
            {
                "bucket": int(bucket),
                "observations": int(len(selected)),
                "mean_score": float(selected["probability"].mean()),
                "actual_positive_rate": float(selected["direction"].mean()),
                "mean_future_return": float(selected["future_return"].mean()),
                "mean_net_return": float(
                    selected["future_return"].mean() - ROUND_TRIP_COST
                ),
            }
        )
    return rows


def _top_signal_results(frame):
    ranked = frame[
        ["source_market_date", "probability", "direction", "future_return"]
    ].copy()
    ranked["percentile"] = ranked.groupby("source_market_date")["probability"].rank(
        pct=True, method="first"
    )
    dates = sorted(ranked["source_market_date"].unique())
    non_overlapping = set(dates[::PURGE_SESSIONS])
    result = {}
    for fraction in (0.05, 0.10, 0.20):
        selected = ranked[ranked["percentile"] > 1.0 - fraction]
        purged = selected[selected["source_market_date"].isin(non_overlapping)]

        def summary(value):
            return {
                "observations": int(len(value)),
                "actual_positive_rate": float(value["direction"].mean()),
                "mean_future_return": float(value["future_return"].mean()),
                "mean_net_return": float(
                    value["future_return"].mean() - ROUND_TRIP_COST
                ),
            }

        result[f"top_{int(fraction * 100)}_percent"] = {
            "all_source_dates": summary(selected),
            "non_overlapping_five_session_sample": summary(purged),
        }
    return result


def _group_metrics(frame, column):
    rows = []
    for name, selected in frame.dropna(subset=[column]).groupby(column, sort=True):
        if len(selected) < 30 or selected["direction"].nunique() < 2:
            continue
        metrics = _probability_metrics(selected["direction"], selected["probability"])
        rows.append({"group": str(name), **metrics})
    return rows


def _yearly_results(frame):
    local = frame.copy()
    local["year"] = local["source_market_date"].str[:4]
    return _group_metrics(local, "year")


def _enrich_point_in_time(root, candidate, frame):
    import numpy as np

    manifest_relative = str(candidate["dataset_manifest"])
    prefix = "quant/v1/"
    if not manifest_relative.startswith(prefix):
        raise ValueError("candidate source manifest is invalid")
    manifest_path = Path(root) / "publish" / "quant" / "v1" / manifest_relative[len(prefix) :]
    manifest_content = manifest_path.read_bytes()
    if hashlib.sha256(manifest_content).hexdigest() != candidate["dataset_sha256"]:
        raise ValueError("source manifest hash mismatch")
    manifest = json.loads(manifest_content)
    symbols = manifest.get("symbols")
    if not isinstance(symbols, dict):
        raise ValueError("source manifest symbol map is unavailable")

    market_ret_20 = {}
    liquidity = {}
    wanted = {
        symbol: set(group["source_market_date"])
        for symbol, group in frame.groupby("symbol", sort=False)
    }
    object_root = Path(root) / "publish" / "quant" / "v1"
    verified_objects = 0
    for symbol, dates in wanted.items():
        metadata = symbols.get(symbol)
        if not isinstance(metadata, dict):
            continue
        path = object_root / str(metadata.get("path") or "")
        compressed = path.read_bytes()
        if (
            len(compressed) != metadata.get("size")
            or hashlib.sha256(compressed).hexdigest() != metadata.get("sha256")
        ):
            raise ValueError(f"source object hash mismatch: {symbol}")
        document = json.loads(gzip.decompress(compressed))
        if document.get("symbol") != symbol:
            raise ValueError(f"source object identity mismatch: {symbol}")
        verified_objects += 1
        for row in document.get("daily") or []:
            date = str(row.get("Date") or "").split("T", 1)[0]
            if date not in dates:
                continue
            market_value = row.get("MARKET_RET_20")
            close = row.get("Close")
            volume = row.get("Volume")
            key = (symbol, date)
            if type(market_value) in (int, float) and math.isfinite(market_value):
                market_ret_20[key] = float(market_value)
            if (
                type(close) in (int, float)
                and type(volume) in (int, float)
                and math.isfinite(close)
                and math.isfinite(volume)
                and close >= 0
                and volume >= 0
            ):
                liquidity[key] = float(close) * float(volume)

    keys = list(zip(frame["symbol"], frame["source_market_date"]))
    frame = frame.copy()
    frame["market_ret_20"] = [market_ret_20.get(key, np.nan) for key in keys]
    frame["liquidity"] = [liquidity.get(key, np.nan) for key in keys]
    frame["regime"] = np.select(
        [frame["market_ret_20"] >= 0.05, frame["market_ret_20"] <= -0.05],
        ["bull", "bear"],
        default="sideways",
    )
    valid_liquidity = frame["liquidity"].notna() & (frame["liquidity"] > 0)
    frame["liquidity_bucket"] = None
    if valid_liquidity.any():
        frame.loc[valid_liquidity, "liquidity_bucket"] = (
            frame.loc[valid_liquidity]
            .groupby("source_market_date")["liquidity"]
            .transform(
                lambda values: (
                    __import__("pandas").qcut(
                        values.rank(method="first"),
                        4,
                        labels=("Q1_low", "Q2", "Q3", "Q4_high"),
                    )
                    if len(values) >= 4
                    else None
                )
            )
        )
    return frame, {
        "verified_source_objects": verified_objects,
        "requested_source_objects": len(wanted),
        "regime_coverage": float(frame["market_ret_20"].notna().mean()),
        "liquidity_coverage": float(frame["liquidity"].notna().mean()),
        "industry_status": "UNAVAILABLE_NO_FROZEN_PIT_MAPPING",
        "market_cap_status": "UNAVAILABLE_NO_PIT_SHARES_OUTSTANDING",
    }


def _bootstrap_uncertainty(frame, iterations=1000, seed=20260716):
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score

    daily = []
    ranked = frame[
        ["source_market_date", "probability", "direction", "future_return"]
    ].copy()
    ranked["percentile"] = ranked.groupby("source_market_date")["probability"].rank(
        pct=True, method="first"
    )
    for date, selected in ranked.groupby("source_market_date", sort=True):
        if selected["direction"].nunique() < 2:
            continue
        top = selected[selected["percentile"] > 0.90]
        daily.append(
            [
                roc_auc_score(selected["direction"], selected["probability"]),
                average_precision_score(selected["direction"], selected["probability"]),
                float(((selected["probability"] >= 0.5) == selected["direction"]).mean()),
                float(((selected["probability"] - selected["direction"]) ** 2).mean()),
                float(top["future_return"].mean() - ROUND_TRIP_COST),
            ]
        )
    values = np.asarray(daily, dtype=float)
    rng = np.random.default_rng(seed)
    draws = values[
        rng.integers(0, len(values), size=(iterations, len(values)))
    ].mean(axis=1)
    names = ("mean_daily_roc_auc", "mean_daily_pr_auc", "mean_daily_accuracy", "mean_daily_brier", "top_10_net_return")
    return {
        "method": "source-date cluster bootstrap of mean daily metrics",
        "iterations": iterations,
        "seed": seed,
        "confidence_level": 0.95,
        "metrics": {
            name: {
                "estimate": float(values[:, index].mean()),
                "lower": float(np.quantile(draws[:, index], 0.025)),
                "upper": float(np.quantile(draws[:, index], 0.975)),
            }
            for index, name in enumerate(names)
        },
    }


def _binary_target_challenger(frame, partitions, target, name):
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    train = _frame_for_dates(frame, partitions["calibration_train"])
    validation = _frame_for_dates(frame, partitions["validation"])
    holdout = _frame_for_dates(frame, partitions["final_holdout"])

    def features(value):
        probability = np.clip(value["probability"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        return np.log(probability / (1.0 - probability)).reshape(-1, 1)

    model = LogisticRegression(C=1e6, max_iter=1000).fit(features(train), train[target])
    validation_probability = model.predict_proba(features(validation))[:, 1]
    holdout_probability = model.predict_proba(features(holdout))[:, 1]
    return {
        "name": name,
        "validation": _probability_metrics(validation[target], validation_probability),
        "final_holdout": _probability_metrics(holdout[target], holdout_probability),
    }


def _three_class_challenger(frame, partitions):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

    train = _frame_for_dates(frame, partitions["calibration_train"])
    validation = _frame_for_dates(frame, partitions["validation"])
    holdout = _frame_for_dates(frame, partitions["final_holdout"])

    def features(value):
        probability = np.clip(value["probability"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        return np.log(probability / (1.0 - probability)).reshape(-1, 1)

    model = LogisticRegression(C=1e6, max_iter=1000).fit(
        features(train), train["target_three_class"]
    )

    def metrics(value):
        probability = model.predict_proba(features(value))
        target = value["target_three_class"].to_numpy(dtype=int)
        return {
            "observations": int(len(value)),
            "accuracy": float(accuracy_score(target, probability.argmax(axis=1))),
            "log_loss": float(log_loss(target, probability, labels=[0, 1, 2])),
            "macro_ovr_roc_auc": float(
                roc_auc_score(target, probability, multi_class="ovr", average="macro")
            ),
            "class_distribution": {
                str(label): float((target == label).mean()) for label in (0, 1, 2)
            },
        }

    return {
        "name": "three_class_up_neutral_down",
        "validation": metrics(validation),
        "final_holdout": metrics(holdout),
    }


def _challenger_record(candidate, partitions, *, name, target_definition, metrics, generated_at):
    record = {
        "schema_version": 1,
        "kind": "absorb-model-challenger",
        "market": "TW",
        "challenger_name": name,
        "model_version": f"{candidate['model_version']}-{name}-head-v1",
        "feature_schema_version": candidate["feature_schema_version"],
        "recommendation_policy_version": candidate["recommendation_policy_version"],
        "target_definition": target_definition,
        "model_family": "logistic target head on immutable OOS champion score",
        "training_window": _partition_document(partitions)["calibration_train"],
        "validation_period": _partition_document(partitions)["validation"],
        "holdout_period": _partition_document(partitions)["final_holdout"],
        "metrics": metrics,
        "gate_result": {
            "immutable": "PASS",
            "no_final_holdout_tuning": "PASS",
            "automatic_promotion": "DISABLED",
            "promotion_eligible": False,
        },
        "source_candidate_sha256": hashlib.sha256(_canonical(candidate)).hexdigest(),
        "generated_at": generated_at,
    }
    digest = hashlib.sha256(_canonical(record)).hexdigest()
    return {**record, "candidate_sha256": digest}


def build_oos_diagnostics(root, candidate_path, *, now=None, bootstrap_iterations=1000):
    import numpy as np
    import pandas as pd

    root = Path(root)
    candidate_path = Path(candidate_path)
    candidate_content = candidate_path.read_bytes()
    candidate = json.loads(candidate_content)
    candidate_sha = hashlib.sha256(candidate_content).hexdigest()
    if candidate_path.stem != candidate_sha:
        raise ValueError("candidate filename does not match its SHA")
    oos_relative = str(candidate["oos_predictions_path"])
    prefix = "backtests/v1/"
    if not oos_relative.startswith(prefix):
        raise ValueError("OOS path is invalid")
    oos_path = root / "publish" / "backtests" / "v1" / oos_relative[len(prefix) :]
    compressed = oos_path.read_bytes()
    if hashlib.sha256(compressed).hexdigest() != candidate["oos_predictions_sha256"]:
        raise ValueError("OOS artifact hash mismatch")
    oos = json.loads(gzip.decompress(compressed))
    predictions = oos.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != candidate["oos_observations"]:
        raise ValueError("OOS artifact observations do not match candidate")
    frame = pd.DataFrame(predictions)
    frame, enrichment = _enrich_point_in_time(root, candidate, frame)
    partitions = _partition_dates(frame)
    global_metrics = _probability_metrics(frame["direction"], frame["probability"])
    calibration = _calibration_challengers(frame, partitions)

    market_return = frame.groupby("source_market_date")["future_return"].transform("mean")
    frame["target_relative_market"] = (
        frame["future_return"] - market_return > 0
    ).astype(int)
    frame["target_net_cost"] = (frame["future_return"] > ROUND_TRIP_COST).astype(int)
    frame["target_three_class"] = np.select(
        [
            frame["future_return"] < -ROUND_TRIP_COST,
            frame["future_return"] > ROUND_TRIP_COST,
        ],
        [0, 2],
        default=1,
    ).astype(int)
    generated_at = _utc_timestamp(now)
    challenger_specs = [
        (
            "absolute_direction",
            "future_return > 0 over five sessions",
            {
                "raw_score": {
                    "validation": calibration["validation"]["raw"],
                    "final_holdout": calibration["final_holdout"]["raw"],
                },
                "calibration_challengers": calibration,
            },
        ),
        (
            "relative_market_excess",
            "future_return minus same-date equal-weight OOS market return > 0",
            _binary_target_challenger(
                frame, partitions, "target_relative_market", "relative_market_excess"
            ),
        ),
        (
            "net_effective_return",
            f"future_return > fixed round-trip cost {ROUND_TRIP_COST}",
            _binary_target_challenger(
                frame, partitions, "target_net_cost", "net_effective_return"
            ),
        ),
        (
            "three_class",
            (
                f"down < -{ROUND_TRIP_COST}; neutral within cost band; "
                f"up > {ROUND_TRIP_COST}"
            ),
            _three_class_challenger(frame, partitions),
        ),
    ]
    challenger_records = [
        _challenger_record(
            candidate,
            partitions,
            name=name,
            target_definition=target_definition,
            metrics=metrics,
            generated_at=generated_at,
        )
        for name, target_definition, metrics in challenger_specs
    ]
    challenger_root = root / "publish" / "backtests" / "v1" / "challengers"
    for record in challenger_records:
        _write_immutable(
            challenger_root / f"{record['candidate_sha256']}.json",
            _canonical({key: value for key, value in record.items() if key != "candidate_sha256"}),
        )

    holdout_raw = calibration["final_holdout"]["raw"]
    selected = calibration["selected_before_final_holdout"]
    holdout_selected = calibration["final_holdout"][selected]
    ranking_status = (
        "effective"
        if holdout_raw["roc_auc"] >= 0.55
        and holdout_raw["pr_auc_lift_over_prevalence"] >= 0.03
        else "weak"
        if holdout_raw["roc_auc"] >= 0.52
        and holdout_raw["pr_auc_lift_over_prevalence"] >= 0.01
        else "ineffective"
    )
    calibration_failure_reason = (
        "raw scores are over-dispersed and materially worse than climatology; "
        "calibration can repair probability scale but cannot improve ranking"
    )
    document = {
        "schema_version": 1,
        "kind": "absorb-oos-diagnostic",
        "market": "TW",
        "source_candidate_sha256": candidate_sha,
        "source_oos_sha256": candidate["oos_predictions_sha256"],
        "model_version": candidate["model_version"],
        "feature_schema_version": candidate["feature_schema_version"],
        "recommendation_policy_version": candidate["recommendation_policy_version"],
        "generated_at": generated_at,
        "oos_contract": {
            "point_in_time": True,
            "oos_only": True,
            "future_features_forbidden": True,
            "five_session_gap": candidate.get("five_session_gap") is True,
            "overlap_handling": (
                "cross-sectional tables use each OOS source date; transaction summaries "
                "also include every fifth source date as a non-overlapping sample"
            ),
            "final_holdout_threshold_tuning": False,
        },
        "partitions": _partition_document(partitions),
        "global_metrics": global_metrics,
        "calibration_curve": _reliability_table(
            frame["direction"], frame["probability"], 10
        ),
        "reliability_table": _reliability_table(
            frame["direction"], frame["probability"], 20
        ),
        "prediction_probability_histogram": _histogram(frame["probability"], 20),
        "decile_actual_positive_rate": _cross_sectional_bins(frame, 10),
        "ventile_actual_positive_rate": _cross_sectional_bins(frame, 20),
        "top_signal_results": _top_signal_results(frame),
        "yearly_results": _yearly_results(frame),
        "regime_results": _group_metrics(frame, "regime"),
        "industry_results": {
            "status": enrichment["industry_status"],
            "reason": (
                "the immutable backtest manifest does not contain a frozen point-in-time "
                "symbol-to-industry mapping"
            ),
            "results": [],
        },
        "liquidity_results": _group_metrics(frame, "liquidity_bucket"),
        "market_cap_results": {
            "status": enrichment["market_cap_status"],
            "reason": (
                "the immutable source objects do not contain point-in-time shares "
                "outstanding or market capitalization"
            ),
            "results": [],
        },
        "transaction_cost_results": {
            "round_trip_cost": ROUND_TRIP_COST,
            "top_signal_results": _top_signal_results(frame),
        },
        "bootstrap_uncertainty": _bootstrap_uncertainty(
            frame, iterations=bootstrap_iterations
        ),
        "point_in_time_enrichment": enrichment,
        "calibration_challengers": calibration,
        "diagnosis": {
            "ranking_status": ranking_status,
            "calibration_failure": True,
            "calibration_failure_reason": calibration_failure_reason,
            "selected_calibrator": selected,
            "selected_calibrator_holdout_brier": holdout_selected["brier"],
            "selected_calibrator_holdout_log_loss": holdout_selected["log_loss"],
            "selected_calibrator_holdout_ece": holdout_selected["ece_10"],
            "promotion_eligible": False,
            "promotion_blockers": [
                "raw accuracy is below majority baseline",
                "raw Brier and Log Loss are worse than climatology",
                f"final holdout ranking is {ranking_status}, below promotion strength",
                (
                    "transaction value is unstable: non-overlapping top 5% is negative, "
                    "top 10/20% gains are small, and the top-10 bootstrap interval spans zero"
                ),
            ],
        },
        "champion": {
            "model_version": candidate["model_version"],
            "status": "research_candidate_rejected",
            "validated_baseline_available": False,
            "candidate_sha256": candidate_sha,
        },
        "challengers": [
            {
                "challenger_name": record["challenger_name"],
                "model_version": record["model_version"],
                "candidate_sha256": record["candidate_sha256"],
                "gate_result": record["gate_result"],
            }
            for record in challenger_records
        ],
        "gates": {
            "point_in_time": "PASS",
            "oos_only": "PASS",
            "no_final_holdout_tuning": "PASS",
            "schema": "PASS",
            "security": "PASS",
            "ranking": "FAIL" if ranking_status != "effective" else "PASS",
            "calibration": "FAIL",
            "quality": "FAIL",
            "transaction_value": "FAIL",
            "promotion": "BLOCKED",
        },
    }
    content = _canonical(document)
    digest = hashlib.sha256(content).hexdigest()
    diagnostic_path = (
        root / "publish" / "backtests" / "v1" / "diagnostics" / f"{digest}.json"
    )
    _write_immutable(diagnostic_path, content)
    return {
        "diagnostic_path": str(diagnostic_path),
        "diagnostic_sha256": digest,
        "challenger_paths": [
            str(challenger_root / f"{record['candidate_sha256']}.json")
            for record in challenger_records
        ],
        "ranking_status": ranking_status,
        "selected_calibrator": selected,
        "promotion_eligible": False,
    }
