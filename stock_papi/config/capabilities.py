"""Fail-closed product capability state for Observation and Prediction."""

import os
import re
from dataclasses import dataclass


_MODES = frozenset({"research", "validated_preview", "production"})
_PREVIEW_PREFIX = re.compile(r"previews/[a-z0-9][a-z0-9-]{0,79}")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _boolean(name, default, warnings):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    warnings.append(f"invalid_{name.lower()}")
    return default


def conditional_advice_allowed(principal: str, allowed_users: frozenset[str]) -> bool:
    """受邀使用者可用條件式建議（日線規則試用版）。研究／預測旗標不受影響。"""
    if not isinstance(principal, str) or not isinstance(allowed_users, (set, frozenset)):
        return False
    if not principal.startswith("line:"):
        return False
    user_id = principal[5:]
    if re.fullmatch(r"U[0-9A-Za-z]{16,64}", user_id or "") is None:
        return False
    return user_id in allowed_users


def trading_beta_users_from_environment() -> frozenset[str]:
    raw = os.getenv("ABSORB_TRADING_BETA_USERS", "")
    users = {item.strip() for item in raw.split(",") if item.strip()}
    return frozenset(users)


@dataclass(frozen=True)
class PredictionCapabilityState:
    mode: str
    observation_enabled: bool
    probability_allowed: bool
    ranking_allowed: bool
    strong_action_allowed: bool
    performance_endorsement_allowed: bool
    preview_candidate_prefix: str | None
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls):
        warnings = []
        requested_mode = os.getenv("ABSORB_PREDICTION_MODE", "research").strip().lower()
        if requested_mode not in _MODES:
            warnings.append("invalid_prediction_mode")
            mode = "research"
        else:
            mode = requested_mode

        observation_enabled = _boolean(
            "ABSORB_OBSERVATION_ENABLED", True, warnings
        )
        requested_probability = _boolean(
            "ABSORB_PREDICTION_PROBABILITY_ENABLED", False, warnings
        )
        requested_ranking = _boolean(
            "ABSORB_PREDICTION_RANKING_ENABLED", False, warnings
        )
        requested_strong_actions = _boolean(
            "ABSORB_PREDICTION_STRONG_ACTIONS_ENABLED", False, warnings
        )
        requested_performance = _boolean(
            "ABSORB_PREDICTION_PERFORMANCE_ENDORSEMENT_ENABLED", False, warnings
        )

        prefix = os.getenv("ABSORB_PREVIEW_CANDIDATE_PREFIX", "").strip().rstrip("/")
        if prefix and _PREVIEW_PREFIX.fullmatch(prefix) is None:
            warnings.append("invalid_preview_candidate_prefix")
            prefix = ""
        preview_candidate_prefix = prefix or None

        probability_allowed = requested_probability
        ranking_allowed = requested_ranking
        strong_action_allowed = requested_strong_actions
        performance_endorsement_allowed = requested_performance

        if mode == "research":
            if probability_allowed:
                warnings.append("probability_disabled_in_research")
            if ranking_allowed:
                warnings.append("ranking_disabled_in_research")
            if strong_action_allowed:
                warnings.append("strong_actions_disabled_in_research")
            if performance_endorsement_allowed:
                warnings.append("performance_endorsement_disabled_in_research")
            probability_allowed = False
            ranking_allowed = False
            strong_action_allowed = False
            performance_endorsement_allowed = False
        elif mode == "validated_preview":
            if preview_candidate_prefix is None:
                warnings.append("validated_preview_prefix_missing")
                probability_allowed = False
                ranking_allowed = False
            if strong_action_allowed:
                warnings.append("strong_actions_require_production_mode")
            if performance_endorsement_allowed:
                warnings.append("performance_endorsement_requires_production_mode")
            strong_action_allowed = False
            performance_endorsement_allowed = False

        return cls(
            mode=mode,
            observation_enabled=observation_enabled,
            probability_allowed=probability_allowed,
            ranking_allowed=ranking_allowed,
            strong_action_allowed=strong_action_allowed,
            performance_endorsement_allowed=performance_endorsement_allowed,
            preview_candidate_prefix=preview_candidate_prefix,
            warnings=tuple(warnings),
        )

    def to_document(self):
        return {
            "mode": self.mode,
            "observation_enabled": self.observation_enabled,
            "probability_allowed": self.probability_allowed,
            "ranking_allowed": self.ranking_allowed,
            "strong_action_allowed": self.strong_action_allowed,
            "performance_endorsement_allowed": (
                self.performance_endorsement_allowed
            ),
        }
