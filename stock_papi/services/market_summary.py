"""Verified professional-report data adapted for market research pages."""

from reporting.professional_schema import ProfessionalPostCloseReport
from stock_papi.services.us_presentation import (
    build_us_market_observation_view,
    localize_us_key_event,
)


def build_market_summary_view(report: ProfessionalPostCloseReport) -> dict:
    """Return only literal, verified fields needed by the market summary shell."""
    if not isinstance(report, ProfessionalPostCloseReport):
        raise TypeError("report must be ProfessionalPostCloseReport")

    market_observation = report.market.to_document()
    return {
        "market": report.identity.market,
        "source_market_date": report.identity.source_market_date.isoformat(),
        "applicable_trading_date": report.identity.applicable_trading_date.isoformat(),
        "executive_summary": report.executive_summary.to_document(),
        "key_events": [localize_us_key_event(event) for event in report.key_events],
        "market_observation": market_observation,
        "market_observation_view": build_us_market_observation_view(market_observation),
        "industries": report.industries.to_document(),
        "securities": report.securities.to_document(),
        "validation": report.validation.to_document(),
    }
