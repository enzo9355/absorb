"""Weekly validation report built from promoted backtests and matured forecasts."""

import datetime
import json
import math

from stock_papi.batch.backtest_store import assess_backtest_compatibility


class WeeklyModelReportError(ValueError):
    """Weekly model evidence is missing, stale, or semantically ambiguous."""


METRICS = (
    "oos_direction_accuracy",
    "brier_score",
    "high_score_realized_rate",
    "strategy_win_rate",
    "expectancy",
    "profit_factor",
    "max_drawdown",
    "longest_winning_streak",
    "longest_losing_streak",
)


def _json_value(value, label):
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WeeklyModelReportError(f"invalid weekly {label}") from exc
    return value


def build_weekly_model_report(
    backtest,
    ledger,
    *,
    generated_at,
    previous_candidate_sha256=None,
):
    if (
        not isinstance(backtest, dict)
        or not hasattr(ledger, "accuracy_summary")
        or not callable(ledger.accuracy_summary)
        or not isinstance(generated_at, datetime.datetime)
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
    ):
        raise WeeklyModelReportError("invalid weekly model input")
    model_version = backtest.get("model_version")
    try:
        compatibility = assess_backtest_compatibility(
            backtest, expected_model_version=model_version
        )
    except Exception as exc:
        raise WeeklyModelReportError("backtest is not promoted") from exc
    if not compatibility["compatible"]:
        raise WeeklyModelReportError("backtest is not promoted")
    candidate_sha = backtest.get("candidate_sha256")
    if candidate_sha == previous_candidate_sha256:
        raise WeeklyModelReportError("no new promoted backtest")
    metrics = backtest.get("metrics")
    if (
        not isinstance(metrics, dict)
        or any(
            type(metrics.get(name)) not in (int, float)
            or not math.isfinite(metrics[name])
            for name in METRICS
        )
    ):
        raise WeeklyModelReportError("weekly backtest metrics are incomplete")
    accuracy = ledger.accuracy_summary()
    if (
        not isinstance(accuracy, dict)
        or type(accuracy.get("matured")) is not int
        or accuracy["matured"] < 1
        or type(accuracy.get("correct")) is not int
        or type(accuracy.get("accuracy")) not in (int, float)
        or not 0 <= accuracy["accuracy"] <= 1
        or type(accuracy.get("invalid")) is not int
        or accuracy["invalid"] < 0
    ):
        raise WeeklyModelReportError("matured prediction ledger is unavailable")
    try:
        cutoff = datetime.date.fromisoformat(str(backtest["cutoff"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise WeeklyModelReportError("backtest cutoff is invalid") from exc
    sections = {}
    for name in (
        "calibration",
        "yearly",
        "regimes",
        "cost_sensitivity",
        "drift",
        "data_quality",
    ):
        value = backtest.get(name)
        if not isinstance(value, (dict, list)) or not value:
            raise WeeklyModelReportError(f"weekly {name} is unavailable")
        sections[name] = _json_value(value, name)
    iso_year, iso_week, _weekday = generated_at.date().isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    content = {
        "week_id": week_id,
        "candidate_sha256": candidate_sha,
        "probability_model": {
            "matured_forecasts": accuracy["matured"],
            "invalid_forecasts": accuracy["invalid"],
            "ledger_direction_accuracy": float(accuracy["accuracy"]),
            "oos_direction_accuracy": float(metrics["oos_direction_accuracy"]),
            "high_score_realized_rate": float(metrics["high_score_realized_rate"]),
            "brier_score": float(metrics["brier_score"]),
            "calibration": sections.pop("calibration"),
        },
        "strategy": {
            "win_rate": float(metrics["strategy_win_rate"]),
            "expectancy": float(metrics["expectancy"]),
            "profit_factor": float(metrics["profit_factor"]),
            "max_drawdown": float(metrics["max_drawdown"]),
            "longest_winning_streak": int(metrics["longest_winning_streak"]),
            "longest_losing_streak": int(metrics["longest_losing_streak"]),
        },
        **sections,
    }
    published = generated_at.astimezone(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "schema_version": 2,
        "report_type": "weekly_model",
        "market": "TW",
        "source_market_date": cutoff.isoformat(),
        "applicable_trading_date": cutoff.isoformat(),
        "published_at": published,
        "forecast_start_date": cutoff.isoformat(),
        "forecast_end_date": cutoff.isoformat(),
        "backtest_as_of": cutoff.isoformat(),
        "data_as_of": cutoff.isoformat(),
        "source_manifest": backtest["dataset_manifest"],
        "source_manifest_sha256": backtest["dataset_sha256"],
        "model_versions": {model_version: 1},
        "title": f"Stock Papi 模型驗證週報 {week_id}",
        "summary": [
            f"成熟預測 {accuracy['matured']} 筆，方向準確率 {accuracy['accuracy']:.1%}",
            f"策略勝率 {metrics['strategy_win_rate']:.1%}，Brier {metrics['brier_score']:.3f}",
        ],
        "warnings": (
            []
            if accuracy["invalid"] == 0
            else [f"另有 {accuracy['invalid']} 筆 invalid settlement，未納入準確率"]
        ),
        "content": content,
    }
