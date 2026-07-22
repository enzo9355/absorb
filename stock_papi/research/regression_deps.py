# -*- coding: utf-8 -*-
"""Lazy import wrapper for statsmodels and econometric dependencies."""

from typing import Any


def get_statsmodels_api() -> Any:
    """Lazy import statsmodels.api inside function scope."""
    import statsmodels.api as sm
    return sm


def get_breusch_pagan_test() -> Any:
    """Lazy import het_breuschpagan from statsmodels.stats.diagnostic."""
    from statsmodels.stats.diagnostic import het_breuschpagan
    return het_breuschpagan


def get_durbin_watson_test() -> Any:
    """Lazy import durbin_watson from statsmodels.stats.stattools."""
    from statsmodels.stats.stattools import durbin_watson
    return durbin_watson


def get_jarque_bera_test() -> Any:
    """Lazy import jarque_bera from statsmodels.stats.stattools."""
    from statsmodels.stats.stattools import jarque_bera
    return jarque_bera


def get_vif_calculator() -> Any:
    """Lazy import variance_inflation_factor from statsmodels.stats.outliers_influence."""
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    return variance_inflation_factor
