import datetime

from stock_papi.services.recommendation_engine import (
    RecommendationInput,
    build_recommendation,
)
from stock_papi.shared.formatting import clamp as _clamp
from stock_papi.shared.formatting import safe_float as _safe_float


def dashboard_top_picks(cards, limit=3):
    if not cards:
        return []
    from stock_papi.shared.symbol import normalize_symbol, get_instrument_type
    
    unique_leaders = []
    seen_leaders = set()
    for card in cards:
        leader = card.get("leader")
        if not leader:
            continue
        code = leader.get("code")
        if not code:
            continue
        norm = normalize_symbol(code)
        if norm not in seen_leaders:
            seen_leaders.add(norm)
            unique_leaders.append((norm, leader))
            
    try:
        from stock_papi.application import industry_map
        ind_map = industry_map() if callable(industry_map) else industry_map
    except Exception:
        ind_map = {}
        
    card_by_name = {card["name"]: card for card in cards}
    
    candidate_items = []
    for norm, leader in unique_leaders:
        belonged = []
        for sec_name, sec_codes in (ind_map or {}).items():
            if sec_name in {"全市場", "ETF專區"}:
                continue
            if any(normalize_symbol(c) == norm for c in sec_codes):
                belonged.append(sec_name)
                
        found_sector = None
        for card in cards:
            if card.get("leader") and normalize_symbol(card["leader"]["code"]) == norm:
                found_sector = card["name"]
                break
        if found_sector and found_sector not in belonged:
            belonged.append(found_sector)
            
        if not belonged:
            belonged = ["未分類"]
            
        def get_sector_sort_key(sec_name):
            card = card_by_name.get(sec_name)
            score = 0.0
            action_strength = 3
            coverage = 0.0
            sample_count = 0
            rank = 9999
            if card:
                score = _safe_float(card.get("score"))
                rank = cards.index(card)
                ldr = card.get("leader") or {}
                rec = ldr.get("recommendation") or {}
                metrics = rec.get("source_metrics") or {}
                action = rec.get("action")
                action_strength = {"優先關注": 5, "分批觀察": 4, "等待確認": 3, "降低曝險": 2, "暫時避開": 1}.get(action, 3)
                coverage = _safe_float(metrics.get("industry_coverage") or rec.get("source_metrics", {}).get("industry_coverage"))
                sample_count = int(_safe_float(metrics.get("sample_count") or rec.get("source_metrics", {}).get("sample_count") or card.get("count", 0)))
            return (-score, -action_strength, -coverage, -sample_count, rank, sec_name)
            
        belonged.sort(key=get_sector_sort_key)
        primary = belonged[0]
        related = belonged[1:]
        
        candidate_items.append({
            "norm": norm,
            "leader": leader,
            "score": _safe_float(leader.get("score")),
            "primary": primary,
            "related": related,
        })
        
    candidate_items.sort(key=lambda item: (-item["score"], item["norm"]))
    
    selected_picks = []
    selected_primaries = set()
    for item in candidate_items:
        if item["primary"] not in selected_primaries:
            selected_picks.append(item)
            selected_primaries.add(item["primary"])
            if len(selected_picks) >= limit:
                break
                
    if len(selected_picks) < limit:
        for item in candidate_items:
            if item not in selected_picks:
                selected_picks.append(item)
                if len(selected_picks) >= limit:
                    break
                    
    picks = []
    for item in selected_picks:
        leader = item["leader"]
        code = leader["code"]
        is_etf = get_instrument_type(code) == "ETF"
        
        summary = f"五日上漲機率 {leader['prob']}%・{leader['trend']}"
        if not is_etf and leader.get("foreign_net_5") is not None:
            summary += f"・外資5日 {leader['foreign_net_5']:,}"
            
        picks.append({
            "code": code,
            "name": leader["name"],
            "headline": leader["recommendation"]["headline"],
            "summary": summary,
            "recommendation": leader["recommendation"],
            "primary_industry": item["primary"],
            "related_industries": item["related"],
            "is_etf": is_etf,
        })
    return picks


def build_market_heatmap(cards):
    from stock_papi.services.recommendation_engine import RecommendationThresholds
    thresholds = RecommendationThresholds()
    heatmap = []
    for card in cards or []:
        leader = card.get("leader") or {}
        rec = leader.get("recommendation") or {}
        metrics = rec.get("source_metrics") or {}
        
        coverage = metrics.get("industry_coverage") if metrics.get("industry_coverage") is not None else leader.get("coverage")
        sample_count = metrics.get("sample_count") if metrics.get("sample_count") is not None else leader.get("sample_count")
        
        prob = leader.get("prob")
        count = card.get("count", 0)
        
        if prob is None or count <= 0:
            continue
        if card.get("name") in {"全市場", "ETF專區"}:
            continue
            
        # Default to pass thresholds if the metrics are not provided in the data structure
        effective_coverage = coverage if coverage is not None else 1.0
        effective_sample_count = sample_count if sample_count is not None else 99
        
        if effective_coverage < thresholds.minimum_industry_coverage:
            continue
        if effective_sample_count < thresholds.minimum_sample_count:
            continue
            
        probability = _clamp(
            _safe_float(prob, card.get("score", 50)),
            0,
            100,
        )
        heatmap.append({
            "name": str(card.get("name") or "未分類"),
            "probability": round(probability, 1),
            "count": int(_safe_float(card.get("count"))),
            "tone": "hot" if probability >= 60 else "cold" if probability < 45 else "steady",
            "code": str(leader.get("code") or ""),
        })
    return sorted(heatmap, key=lambda item: item["probability"], reverse=True)


def cached_opportunities(cache, now, expiry_seconds, limit=5):
    from stock_papi.shared.symbol import normalize_symbol
    timestamp_now = now()
    items = []
    seen = set()
    for code, (data, timestamp) in cache.items():
        if code == "TAIEX" or timestamp_now - timestamp >= expiry_seconds:
            continue
        norm = normalize_symbol(code)
        if norm in seen:
            continue
        if all(key in data for key in ("name", "prob")):
            items.append({"code": code, "name": data["name"], "prob": data["prob"]})
            seen.add(norm)
    return sorted(items, key=lambda item: item["prob"], reverse=True)[:limit]


def dashboard_sector_cards(load_snapshot, line_store, fallback_items, safe_float, limit=6):
    try:
        snapshot = load_snapshot(line_store)
    except Exception:
        snapshot = {}
    cards = []
    for name, items in (snapshot or {}).get("sectors", {}).items():
        if not items:
            continue
        leader = items[0]
        try:
            as_of = datetime.date.fromisoformat(str(leader.get("as_of") or ""))
        except ValueError:
            as_of = None
        recommendation = build_recommendation(RecommendationInput(
            scope="industry",
            entity_id=str(name),
            probability=leader.get("prob"),
            trend=leader.get("trend"),
            data_as_of=as_of,
            current_date=datetime.date.today(),
            foreign_net_5=leader.get("foreign_net_5"),
            sample_count=leader.get("sample_count", leader.get("trades")),
            industry_coverage=leader.get("coverage"),
            rotation=leader.get("rotation"),
            near_rotation_boundary=leader.get("near_rotation_boundary") is True,
            data_quality_warning=leader.get("data_quality_warning") is True,
        )).to_dict()
        cards.append({
            "name": name,
            "count": len(items),
            "score": round(safe_float(leader.get("score")), 1),
            "leader": {
                "code": str(leader.get("code") or ""),
                "name": str(leader.get("name") or ""),
                "prob": int(safe_float(leader.get("prob"))),
                "trend": str(leader.get("trend") or "中性"),
                "foreign_net_5": int(safe_float(leader.get("foreign_net_5"))),
                "as_of": str(leader.get("as_of") or ""),
                "recommendation": recommendation,
            },
        })
    if cards:
        return sorted(cards, key=lambda item: item["score"], reverse=True)[:limit]
    fallback = []
    for item in fallback_items(limit):
        fallback.append({
            "name": "熱門觀察",
            "count": 1,
            "score": float(item["prob"]),
            "leader": {
                "code": item["code"],
                "name": item["name"],
                "prob": int(item["prob"]),
                "trend": "等待更新",
                "foreign_net_5": 0,
                "as_of": "",
                "recommendation": build_recommendation(RecommendationInput(
                    scope="industry", entity_id="熱門觀察",
                    probability=item["prob"], trend="等待更新",
                )).to_dict(),
            },
        })
    return fallback
