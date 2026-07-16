"""Shared model-evidence presentation rules for Web, LINE, reports and chat."""

from __future__ import annotations

import copy


BOOTSTRAP_STATUS = "initial_backtest_bootstrap"
VALIDATED_STATUS = "validated_compatible"
SAFE_ACTION = "等待確認"
SAFE_HEADLINE = "尚未完成機率校準驗證；目前僅供量化觀察"
CALIBRATION_NOTICE = "尚未完成機率校準驗證"


def _direction_text(value):
    return (
        str(value)
        .replace("五日上漲機率", "模型方向分數")
        .replace("模型機率", "模型方向分數")
        .replace("上漲機率", "模型方向分數")
        .replace("%", "")
    )


def presentation_policy(baseline_status):
    validated = baseline_status == VALIDATED_STATUS
    return {
        "baseline_status": baseline_status,
        "model_output_label": "五日上漲機率" if validated else "模型方向分數",
        "calibration_notice": None if validated else CALIBRATION_NOTICE,
        "confidence_cap": "normal" if validated else "low",
        "strong_action_allowed": validated,
        "performance_endorsement_allowed": validated,
        "top_picks_label": "精選標的" if validated else "量化觀察名單",
    }


def sanitize_recommendation(recommendation, baseline_status):
    value = copy.deepcopy(recommendation) if isinstance(recommendation, dict) else {}
    if baseline_status != BOOTSTRAP_STATUS:
        return value
    risks = [
        _direction_text(item)
        for item in value.get("risk_reasons") or []
        if "準確率" not in str(item) and "勝率" not in str(item)
    ]
    if CALIBRATION_NOTICE not in risks:
        risks.insert(0, CALIBRATION_NOTICE)
    return {
        **value,
        "action": SAFE_ACTION,
        "level": "insufficient",
        "headline": SAFE_HEADLINE,
        "confidence": "可信度低",
        "supporting_reasons": [
            _direction_text(item)
            for item in value.get("supporting_reasons") or []
            if "準確率" not in str(item) and "勝率" not in str(item)
        ],
        "risk_reasons": risks[:4],
        "suggested_action": "只列入觀察，不依此分數調高排序或部位。",
        "unheld_guidance": "只列入量化觀察名單，等待 validated baseline。",
        "held_guidance": "模型分數與市場技術風險分開檢視，沿用既有風險計畫。",
        "invalidation_conditions": [
            CALIBRATION_NOTICE,
            "validated compatible baseline 尚未建立",
        ],
        "strong_action_allowed": False,
    }


def sanitize_analysis(data, evidence):
    value = copy.deepcopy(data) if isinstance(data, dict) else data
    if not isinstance(value, dict):
        return value
    status = (evidence or {}).get("baseline_status")
    policy = presentation_policy(status)
    value.update(policy)
    probability = value.get("prob")
    if status == BOOTSTRAP_STATUS:
        value["direction_score"] = probability
        value["recommendation"] = sanitize_recommendation(
            value.get("recommendation"), status
        )
        value["bt"] = {
            "trades": 0,
            "days": 0,
            "strat_cum": 0.0,
            "bh_cum": 0.0,
            "accuracy": 0.0,
            "win_rate": 0.0,
            "mdd": 0.0,
            "sharpe": 0.0,
            "brier": 0.0,
            "top_features": [],
            "conclusion": "bootstrap 階段不顯示歷史績效背書。",
        }
        value["backtest_interpretation"] = {
            "advantage": "尚無 validated compatible baseline，不提供策略優勢背書。",
            "cumulative_return": "bootstrap 階段不顯示歷史累積報酬。",
            "maximum_drawdown": "bootstrap 階段不顯示歷史最大回撤。",
            "win_rate": "bootstrap 階段不顯示歷史績效統計。",
            "cash_ratio": "bootstrap 階段不顯示績效相關統計。",
            "sharpe": "bootstrap 階段不顯示報酬效率。",
            "brier": CALIBRATION_NOTICE,
        }
        value["backtest_as_of"] = None
    return value


def sanitize_public_report(report, baseline_status):
    value = copy.deepcopy(report) if isinstance(report, dict) else {}
    if baseline_status != BOOTSTRAP_STATUS:
        return value
    policy = presentation_policy(baseline_status)
    value["presentation"] = policy
    value["model_quality"] = {
        "samples": 0,
        "direction_accuracy": None,
        "brier_score": None,
        "calibration_bins": [],
        "status": CALIBRATION_NOTICE,
    }
    value["key_points"] = [
        (
            _direction_text(item)
            .replace("機率變化", "方向分數變化")
            .replace("模型偏多產業", "模型分數較高產業")
            .replace("模型偏弱產業", "模型分數較低產業")
            if "機率" in str(item) or "模型偏" in str(item)
            else str(item)
        )
        for item in value.get("key_points") or []
    ]
    backtest = value.get("backtest") if isinstance(value.get("backtest"), dict) else {}
    value["backtest"] = {
        **backtest,
        "periods": 0,
        "sample_quality": "可信度低",
        "performance_endorsement_allowed": False,
        "interpretation": {
            "advantage": "尚無 validated compatible baseline，不提供策略優勢背書。",
            "brier": CALIBRATION_NOTICE,
            "cash_ratio": "bootstrap 階段不顯示績效相關統計。",
            "cumulative_return": "bootstrap 階段不顯示歷史累積報酬。",
            "maximum_drawdown": "bootstrap 階段不顯示歷史最大回撤。",
            "sharpe": "bootstrap 階段不顯示報酬效率。",
            "win_rate": "bootstrap 階段不顯示歷史績效統計。",
        },
    }
    for collection in ("industries", "stocks"):
        sanitized = []
        for item in value.get(collection) or []:
            if not isinstance(item, dict):
                continue
            row = copy.deepcopy(item)
            if "probability" in row:
                row["direction_score"] = row.pop("probability")
            row["model_output_label"] = policy["model_output_label"]
            row["calibration_notice"] = policy["calibration_notice"]
            row["action"] = SAFE_ACTION
            row["confidence"] = "可信度低"
            row["headline"] = SAFE_HEADLINE
            row["supporting_reasons"] = [
                _direction_text(reason)
                for reason in row.get("supporting_reasons") or []
                if "準確率" not in str(reason) and "勝率" not in str(reason)
            ]
            if isinstance(row.get("risks"), list):
                row["risks"] = [
                    _direction_text(reason)
                    if "機率" in str(reason)
                    else str(reason)
                    for reason in row["risks"]
                ]
            if "機率" in str(row.get("risk") or ""):
                row["risk"] = _direction_text(row["risk"])
            sanitized.append(row)
        value[collection] = sanitized
    market = value.get("market_recommendation")
    if isinstance(market, dict):
        value["market_recommendation"] = sanitize_recommendation(
            market, baseline_status
        )
    return value
