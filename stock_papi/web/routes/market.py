"""Market-facing Flask route registration."""

from flask import abort, jsonify, render_template

from stock_papi.shared.formatting import safe_float as _safe_float


def register_market_routes(
    app, *, analyze, dashboard_sector_cards, cached_opportunities,
    build_market_heatmap, dashboard_top_picks, industry_map,
    market_insights_payload, twstock_codes, is_us_ticker,
    find_industry_peers, get_stock_name,
):
    def dashboard_api():
        market = analyze("TAIEX")
        if not market:
            return jsonify({"error": "market data unavailable"}), 503
        sector_cards = dashboard_sector_cards()
        sectors = [
            {"name": name, "count": len(codes)}
            for name, codes in list(industry_map().items())[:8]
        ]
        return jsonify({
            "market": {
                "price": float(market["price"]), "prob": int(market["prob"]),
                "trend": market["trend"],
                "as_of": str(market.get("as_of") or ""),
                "sentiment_status": str(market.get("s_status") or "資料不足"),
                "sentiment_score": round(_safe_float(market.get("s_score")), 1),
                "confidence": str(market.get("news_confidence") or "低"),
            },
            "opportunities": cached_opportunities(),
            "sector_cards": sector_cards,
            "heatmap": build_market_heatmap(sector_cards),
            "top_picks": dashboard_top_picks(sector_cards),
            "watchlist_hint": {
                "title": "關注與提醒在 LINE 管理",
                "steps": ["在 LINE 查詢個股", "點選加入關注", "從提醒管理設定通知"],
            },
            "sectors": sectors,
        })

    def market_insights_api():
        return jsonify(market_insights_payload())

    def market_map_page():
        return render_template("market_map.html", insights=market_insights_payload())

    def stock_page(code):
        code = code.upper()
        if code not in twstock_codes() and not is_us_ticker(code):
            abort(404)
        data = analyze(code)
        peer_group = find_industry_peers(code)
        peers = [{"code": peer, "name": get_stock_name(peer)} for peer in peer_group["codes"]]
        return render_template(
            "stock_detail.html", d=data, peers=peers,
            peer_category=peer_group["category"],
        ) if data else "查無資料"

    def market_page():
        data = analyze("TAIEX")
        return render_template("stock_detail.html", d=data) if data else "資料更新中"

    app.add_url_rule("/api/dashboard", "dashboard_api", dashboard_api)
    app.add_url_rule("/api/market-insights", "market_insights_api", market_insights_api)
    app.add_url_rule("/market-map", "market_map_page", market_map_page)
    app.add_url_rule("/stock/<code>", "stock_page", stock_page)
    app.add_url_rule("/market", "market_page", market_page)
