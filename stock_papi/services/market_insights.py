"""Market-insights response assembly independent of Flask."""


def market_insights_payload(fetch_insights, get_stock_name, industry_map, today, build_industries, build_supply_chains):
    document = fetch_insights()
    if document:
        return document
    fallback_metrics = {
        str(code).upper(): {
            "name": get_stock_name(code),
            "prob": None,
            "trend": "資料待更新",
            "as_of": "",
        }
        for category, codes in industry_map.items()
        if category not in {"全市場", "ETF專區"}
        for code in codes
    }
    return {
        "schema_version": 1,
        "as_of": today().isoformat(),
        "industries": build_industries(industry_map, fallback_metrics),
        "mops": [],
        "etfs": [],
        "supply_chains": build_supply_chains({}),
        "sources": ["Stock Papi fallback"],
        "degraded": True,
    }
