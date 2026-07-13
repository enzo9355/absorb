"""Central registration for the public Flask route inventory."""

from stock_papi.web.routes.dashboard import register_dashboard_page
from stock_papi.web.routes.market import register_market_routes
from stock_papi.web.routes.reports import register_report_routes
from stock_papi.web.routes.system import register_system_routes
from stock_papi.integrations.line.webhook import register_line_routes


def register_routes(app, dependencies):
    register_dashboard_page(app)
    register_system_routes(app, search_stock=dependencies["search_stock"])
    register_report_routes(
        app,
        load_index=dependencies["load_report_index"],
        load_pdf=dependencies["load_report_pdf"],
        sample_report_path=dependencies["sample_report_path"],
        sample_report_filename=dependencies["sample_report_filename"],
        max_pdf_bytes=dependencies["max_pdf_bytes"],
    )
    register_market_routes(
        app,
        analyze=dependencies["analyze"],
        dashboard_sector_cards=dependencies["dashboard_sector_cards"],
        cached_opportunities=dependencies["cached_opportunities"],
        build_market_heatmap=dependencies["build_market_heatmap"],
        dashboard_top_picks=dependencies["dashboard_top_picks"],
        industry_map=dependencies["industry_map"],
        market_insights_payload=dependencies["market_insights_payload"],
        twstock_codes=dependencies["twstock_codes"],
        is_us_ticker=dependencies["is_us_ticker"],
        find_industry_peers=dependencies["find_industry_peers"],
        get_stock_name=dependencies["get_stock_name"],
    )
    register_line_routes(
        app,
        handler=dependencies["handler"],
        get_line_bot_api=dependencies["get_line_bot_api"],
        get_line_store=dependencies["get_line_store"],
        get_broadcast_token=dependencies["get_broadcast_token"],
        get_alert_task_token=dependencies["get_alert_task_token"],
        analyze=dependencies["analyze"],
        get_broadcast_insight=dependencies["get_broadcast_insight"],
        refresh_sector_signals=dependencies["refresh_sector_signals"],
        run_alert_checks=dependencies["run_alert_checks"],
    )
