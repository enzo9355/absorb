"""Public research surfaces backed by reviewed, versioned research catalogs."""

import copy
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import abort, jsonify, render_template, request

from stock_papi.integrations.market_data.tw_security_master import is_taiwan_symbol
from stock_papi.integrations.market_data.us_universe import validate_us_ticker
from stock_papi.services.company_events import CompanyEventSchemaError, split_event_window
from stock_papi.services.industry_relationships import relationship_is_current
from stock_papi.services.opinion_consensus import build_consensus
from stock_papi.services.public_opinions import query_activities


_MARKETS = {"TW", "US"}
_WINDOWS = {1, 7, 28}
_VIEWS = {"latest", "consensus", "timeline"}
_STANCES = {"bullish", "bearish", "neutral", "unclear", "conditional", "news", "flow", "trade"}
_CONTENT_TYPES = {"original_opinion", "news_relay", "flow_observation", "trade_disclosure"}
_ACTIVITY_WINDOWS = {7, 28, 90}
_ACTIVITY_TABS = {"latest", "trades", "holdings", "opinions"}
_ACTIVITY_TYPES = {"trade_disclosure", "holding_snapshot", "self_reported_trade"}
_ACTIVITY_LABELS = {"trade_disclosure": "官方交易揭露", "self_reported_trade": "當事人自述",
                    "holding_snapshot": "機構季底持倉", "original_opinion": "公開觀點"}
_PAGE_SIZE = 20


def register_research_routes(
    app, *, load_relationships, load_events, load_opinions, load_events_status=None,
    stock_observation, get_stock_name, allowed_symbols,
):
    def add_graph(catalog):
        catalog = copy.deepcopy(catalog or {})
        stages = catalog.get("stages") or []
        graph_nodes = []
        positions = {}
        for stage_index, stage in enumerate(stages):
            nodes = stage.get("nodes") or []
            for node_index, node in enumerate(nodes):
                symbol = node.get("symbol")
                if not symbol:
                    continue
                point = {
                    "symbol": symbol,
                    "name": node.get("name") or symbol,
                    "stage": stage.get("name") or stage.get("id") or "",
                    "x": 120 + stage_index * 250,
                    "y": 90 + node_index * 78,
                }
                graph_nodes.append(point)
                positions[symbol] = point
        graph_edges = []
        for relation in catalog.get("relationships") or []:
            source = relation.get("from") or {}
            target = relation.get("to") or {}
            left = positions.get(source.get("symbol"))
            right = positions.get(target.get("symbol"))
            if left and right:
                graph_edges.append({
                    "x1": left["x"] + 92, "y1": left["y"],
                    "x2": right["x"] - 92, "y2": right["y"],
                    "type": relation.get("type", ""),
                })
        catalog["graph_nodes"] = graph_nodes
        catalog["graph_edges"] = graph_edges
        return catalog

    def relationship_view(catalog, focus=None):
        catalog = catalog or {}
        # The reviewed catalog already has the renderable shape. Keep the
        # legacy adapter below for callers that still provide the old shape.
        if isinstance(catalog, dict) and "topic" in catalog and "stages" in catalog:
            if catalog.get("schema_version") == 1:
                catalog = copy.deepcopy(catalog)
                catalog["relationships"] = [
                    item for item in catalog.get("relationships") or []
                    if relationship_is_current(item)
                ]
            if focus:
                catalog = copy.deepcopy(catalog)
                catalog["relationships"] = [
                    item for item in catalog.get("relationships") or []
                    if focus in {
                        str((item.get("from") or {}).get("symbol") or "").upper(),
                        str((item.get("to") or {}).get("symbol") or "").upper(),
                    }
                ]
            return add_graph(catalog)
        companies = {item["company_id"]: item for item in catalog.get("companies", [])}
        sources = {item["source_id"]: item for item in catalog.get("sources", [])}
        stages = {}
        for company in companies.values():
            for segment in company.get("segments", []):
                stages.setdefault(segment, []).append({
                    "symbol": company.get("symbol"), "name": company["name"],
                })
        relationships = []
        type_names = {
            "supply": "供應關係", "partnership": "合作關係",
            "competition": "競爭關係", "same_segment": "同一環節／題材",
        }
        for item in catalog.get("relationships", []):
            if "source_ids" in item:
                source = sources.get(item["source_ids"][0], {})
                row = {
                    "from": companies[item["from_company_id"]],
                    "to": companies[item["to_company_id"]],
                    "type": type_names.get(item["relation_type"], item["relation_type"]),
                    "product_scope": item["product_scope"], "source": source,
                    "reviewed_at": item["reviewed_at"], "status": item["status"],
                }
            else:
                row = item
            relationships.append(row)
        if focus:
            relationships = [
                item for item in relationships
                if focus in {
                    str((item.get("from") or {}).get("symbol") or "").upper(),
                    str((item.get("to") or {}).get("symbol") or "").upper(),
                }
            ]
        return add_graph({
            "topic": catalog.get("title", "產業關係圖"),
            "coverage_note": "本圖只包含已審核且有來源的關係，未涵蓋公司不代表不存在關係。",
            "stages": [{"name": name, "nodes": nodes} for name, nodes in stages.items()],
            "relationships": relationships,
            "research_leads": list(catalog.get("research_leads") or []),
        })

    def relationships_page():
        focus = request.args.get("focus", "").strip().upper()
        try:
            raw_catalog = load_relationships() or {}
            known_symbols = {
                str(node.get("symbol") or "").upper()
                for stage in raw_catalog.get("stages", [])
                if isinstance(stage, dict)
                for node in stage.get("nodes", [])
                if isinstance(node, dict) and node.get("symbol")
            }
            known_symbols.update(
                str((endpoint or {}).get("symbol") or "").upper()
                for item in raw_catalog.get("relationships", [])
                if isinstance(item, dict)
                for endpoint in (item.get("from"), item.get("to"))
                if isinstance(endpoint, dict) and endpoint.get("symbol")
            )
            if focus and focus not in known_symbols:
                return jsonify({"field": "focus", "reason": "unknown_company"}), 400
            catalog = relationship_view(raw_catalog, focus=focus or None)
        except Exception:
            catalog = {
                "topic": "產業關係圖",
                "coverage_note": "產業關係資料暫時無法驗證，請稍後再試。",
                "stages": [], "relationships": [], "graph_nodes": [],
                "graph_edges": [], "research_leads": [], "unavailable": True,
            }
        return render_template(
            "industry_relationships.html",
            catalog=catalog,
            relationships=list(catalog.get("relationships") or []),
            research_leads=list(catalog.get("research_leads") or []),
            focus=focus,
        )

    def relationships_api():
        focus = request.args.get("focus", "").strip().upper()
        try:
            raw_catalog = load_relationships() or {}
            known_symbols = {
                str(node.get("symbol") or "").upper()
                for stage in raw_catalog.get("stages", [])
                if isinstance(stage, dict)
                for node in stage.get("nodes", [])
                if isinstance(node, dict) and node.get("symbol")
            }
            known_symbols.update(
                str((endpoint or {}).get("symbol") or "").upper()
                for item in raw_catalog.get("relationships", [])
                if isinstance(item, dict)
                for endpoint in (item.get("from"), item.get("to"))
                if isinstance(endpoint, dict) and endpoint.get("symbol")
            )
            if focus and focus not in known_symbols:
                return jsonify({"field": "focus", "reason": "unknown_company"}), 400
            catalog = relationship_view(raw_catalog, focus=focus or None)
        except Exception:
            return jsonify({
                "status": "unavailable",
                "message": "產業關係資料暫時無法驗證",
            }), 503
        return jsonify(catalog)

    def compare_page():
        raw = request.args.get("symbols", "")
        symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
        permitted = {str(item).upper() for item in (allowed_symbols() or set())}
        if not 2 <= len(symbols) <= 4 or len(set(symbols)) != len(symbols):
            return jsonify({"error": "請選擇 2 至 4 檔不同公司"}), 400
        if any(symbol not in permitted for symbol in symbols):
            return jsonify({"error": "公司代碼無法驗證"}), 400
        rows = []
        for symbol in symbols:
            observation = stock_observation(symbol)
            if not isinstance(observation, dict):
                observation = {"code": symbol, "name": get_stock_name(symbol)}
            else:
                observation = dict(observation)
                observation.setdefault("code", symbol)
                observation.setdefault("name", get_stock_name(symbol))
            rows.append(observation)
        return render_template("stock_compare.html", rows=rows, symbols=symbols)

    def events_page():
        if callable(load_events_status):
            try:
                raw_events, event_status = load_events_status()
            except Exception:
                raw_events, event_status = [], "unavailable"
        else:
            try:
                raw_events = load_events() or []
                event_status = "available" if raw_events else "empty"
            except Exception:
                raw_events, event_status = [], "unavailable"
        source_events = raw_events if isinstance(raw_events, list) else []
        events = source_events
        symbol = request.args.get("symbol", "").strip().upper()
        event_type = request.args.get("event_type", "").strip()
        if symbol:
            events = [item for item in events if item.get("symbol") == symbol]
            if not events and event_status == "available" and not any(item.get("symbol") for item in source_events if isinstance(item, dict)):
                event_status = "not_covered"
        if event_type:
            events = [item for item in events if item.get("event_type") == event_type]
        try:
            window = split_event_window(events, as_of=request.args.get("as_of") or None)
        except CompanyEventSchemaError:
            window = {
                "as_of": request.args.get("as_of") or "",
                "past_start": "",
                "future_end": "",
                "past": [],
                "upcoming": [],
                "undated": [],
            }
        return render_template(
            "events.html",
            events=events,
            past_events=window["past"],
            upcoming_events=window["upcoming"],
            undated_events=window["undated"],
            event_window=window,
            selected_symbol=symbol,
            selected_event_type=event_type,
            event_status=event_status,
        )

    def _bad(field, reason):
        return jsonify({"field": field, "reason": reason}), 400

    def _load_catalog():
        try:
            catalog = load_opinions()
        except Exception:
            return {}, "unavailable"
        if not isinstance(catalog, dict):
            return {}, "unavailable"
        if (
            catalog.get("schema_version") != 2
            or not str(catalog.get("catalog_version") or "").strip()
            or not isinstance(catalog.get("creators"), list)
            or not isinstance(catalog.get("opinions"), list)
            or not isinstance(catalog.get("coverage"), list)
        ):
            return {}, "unavailable"
        if not catalog.get("creators") and not catalog.get("opinions"):
            return catalog, "empty"
        return catalog, "available"

    def _parse_cutoff(value):
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    def _security_known(market, symbol):
        if market == "TW":
            return is_taiwan_symbol(symbol)
        if market == "US":
            try:
                validate_us_ticker(symbol)
            except ValueError:
                return False
            return True
        return False

    def _parse_query(
        args, *, path_market=None, path_symbol=None,
        creator_ids=None, forced_creator_id=None,
    ):
        market = (path_market if path_market is not None else args.get("market", "")).strip().upper()
        symbol = (path_symbol if path_symbol is not None else args.get("symbol", "")).strip().upper()
        if market and market not in _MARKETS:
            return None, _bad("market", "invalid")
        if (path_market is not None or symbol) and not market:
            return None, _bad("market", "required")
        if symbol and not _security_known(market, symbol):
            return None, _bad("symbol", "unknown_security")

        try:
            window = int(args.get("window", "7") or 7)
        except ValueError:
            return None, _bad("window", "invalid")
        if window not in _WINDOWS:
            return None, _bad("window", "invalid")

        view = (args.get("view", "latest") or "latest").strip().lower()
        if view not in _VIEWS:
            return None, _bad("view", "invalid")

        stance = (args.get("stance", "") or "").strip().lower()
        if stance and stance not in _STANCES:
            return None, _bad("stance", "invalid")
        content_type = (args.get("content_type", "") or "").strip()
        if content_type and content_type not in _CONTENT_TYPES:
            return None, _bad("content_type", "invalid")

        cutoff_at = _parse_cutoff(args.get("cutoff_at"))
        if cutoff_at is None:
            return None, _bad("cutoff_at", "timezone_required")

        creator_id = forced_creator_id or (args.get("creator_id", "") or "").strip()
        if creator_id and creator_ids is not None and creator_id not in creator_ids:
            return None, _bad("creator_id", "unknown")
        query = {
            "market": market,
            "symbol": symbol,
            "creator_id": creator_id,
            "stance": stance,
            "content_type": content_type,
            "window": window,
            "view": view,
            "cutoff_at": cutoff_at.isoformat().replace("+00:00", "Z"),
            "cutoff_at_dt": cutoff_at,
        }
        query["query_string"] = urlencode({
            key: value for key, value in query.items()
            if key != "cutoff_at_dt" and value not in ("", None)
        })
        return query, None

    def _coverage_by_creator(catalog):
        coverage = {}
        for row in list(catalog.get("coverage") or []):
            if isinstance(row, dict) and row.get("creator_id"):
                coverage[row["creator_id"]] = row
        return coverage

    def _opinion_text(item):
        return item.get("summary") or item.get("text") or item.get("raw_text") or ""

    def _display_opinion(item, creators_by_id=None):
        creators_by_id = creators_by_id or {}
        creator = creators_by_id.get(item.get("creator_id"), {})
        source = item.get("source_url") or item.get("original_source_url") or item.get("source") or ""
        return {
            **item,
            "name": item.get("name") or item.get("security_name") or item.get("symbol") or "",
            "creator_name": creator.get("name") or item.get("creator_id") or "",
            "summary": _opinion_text(item),
            "source": source,
            "source_url": source,
            "market": item.get("market") or "",
            "symbol": item.get("symbol") or "",
            "stance": item.get("stance") or item.get("classification") or "unclear",
            "content_type": item.get("content_type") or "",
        }

    def _opinion_category(item):
        content_type = item.get("content_type")
        if content_type == "news_relay":
            return "news"
        if content_type == "flow_observation":
            return "flow"
        if content_type == "trade_disclosure":
            return "trade"
        if item.get("recommendation_kind") == "conditional":
            return "conditional"
        return item.get("stance") or item.get("classification") or "unclear"

    def _query_matches_opinion(item, query):
        if query.get("creator_id") and item.get("creator_id") != query["creator_id"]:
            return False
        if query.get("stance") and _opinion_category(item) != query["stance"]:
            return False
        if query.get("content_type") and item.get("content_type") != query["content_type"]:
            return False
        return True

    def _consensus_catalog(catalog, query):
        if not any(query.get(key) for key in ("creator_id", "stance", "content_type")):
            return catalog
        filtered = copy.deepcopy(catalog)
        filtered["opinions"] = [
            item for item in list(catalog.get("opinions") or [])
            if isinstance(item, dict) and _query_matches_opinion(item, query)
        ]
        return filtered

    def _filtered_opinions(catalog, query):
        creators_by_id = {
            item.get("id"): item for item in list(catalog.get("creators") or [])
            if isinstance(item, dict) and item.get("id")
        }
        rows = []
        for item in list(catalog.get("opinions") or []):
            if not isinstance(item, dict):
                continue
            if query.get("market") and item.get("market") != query["market"]:
                continue
            if query.get("symbol") and str(item.get("symbol") or "").upper() != query["symbol"]:
                continue
            if not _query_matches_opinion(item, query):
                continue
            rows.append(_display_opinion(item, creators_by_id))
        rows.sort(key=lambda item: (str(item.get("published_at") or ""), str(item.get("opinion_id") or "")), reverse=True)
        return rows

    def _parse_activity_window(args):
        raw = (args.get("activity_window", "") or "").strip().lower()
        if not raw or raw == "all":
            return None, None
        try:
            window = int(raw)
        except ValueError:
            return None, _bad("activity_window", "invalid")
        if window not in _ACTIVITY_WINDOWS:
            return None, _bad("activity_window", "invalid")
        return window, None

    def _parse_page(args):
        raw = (args.get("page", "") or "").strip()
        if not raw:
            return 1, None
        try:
            page = int(raw)
        except ValueError:
            return None, _bad("page", "invalid")
        if page < 1:
            return None, _bad("page", "invalid")
        return page, None

    def _parse_activity_tab(args):
        tab = (args.get("tab", "") or "latest").strip().lower()
        if tab not in _ACTIVITY_TABS:
            return None, _bad("tab", "invalid")
        return tab, None

    def _subjects_by_id(catalog):
        result = {}
        for row in list(catalog.get("subjects") or []):
            if isinstance(row, dict) and row.get("subject_id"):
                result[row["subject_id"]] = row
        return result

    def _query_activities_for_page(catalog, *, query, activity_window, tab, subject_id=None):
        if not isinstance(catalog, dict):
            return []
        try:
            rows = query_activities(
                catalog,
                subject_id=subject_id or None,
                market=query.get("market") or None,
                symbol=query.get("symbol") or None,
                cutoff_at=query["cutoff_at_dt"],
                window_days=activity_window,
            )
        except ValueError:
            return []
        if tab == "trades":
            rows = [r for r in rows if r.get("activity_type") in {"trade_disclosure", "self_reported_trade"}]
        elif tab == "holdings":
            rows = [r for r in rows if r.get("activity_type") == "holding_snapshot"]
        return rows

    def _display_activity(item, subjects_by_id=None):
        subjects_by_id = subjects_by_id or {}
        subject = subjects_by_id.get(item.get("subject_id"), {})
        activity_type = item.get("activity_type") or ""
        return {
            **item,
            "type_label": _ACTIVITY_LABELS.get(activity_type, activity_type or "動態"),
            "subject_name": subject.get("subject_name") or item.get("subject_id") or "未知對象",
            "transaction_label": item.get("transaction_date") or "交易日未提供",
            "holdings_label": item.get("holdings_as_of") or "",
            "public_label": item.get("public_at") or "",
            "reviewed_label": item.get("reviewed_at") or "",
        }

    def perspectives_page():
        catalog, catalog_status = _load_catalog()
        creator_ids = {
            item.get("id") for item in list(catalog.get("creators") or [])
            if isinstance(item, dict) and item.get("id")
        } if catalog_status != "unavailable" else None
        query, error = _parse_query(request.args, creator_ids=creator_ids)
        if error:
            return error
        creators = [item for item in list(catalog.get("creators") or []) if isinstance(item, dict)]
        coverage = _coverage_by_creator(catalog)
        opinions = [] if catalog_status != "available" else _filtered_opinions(catalog, query)
        consensus = None
        if catalog_status == "available" and query.get("market") and query.get("symbol"):
            try:
                consensus = build_consensus(
                    _consensus_catalog(catalog, query),
                    market=query["market"],
                    symbol=query["symbol"],
                    window_days=query["window"],
                    cutoff_at=query["cutoff_at_dt"],
                )
            except ValueError:
                consensus = None
        activity_window, error = _parse_activity_window(request.args)
        if error:
            return error
        tab, error = _parse_activity_tab(request.args)
        if error:
            return error
        page, error = _parse_page(request.args)
        if error:
            return error
        subjects_by_id = _subjects_by_id(catalog) if catalog_status == "available" else {}
        subject_filter = (request.args.get("subject_id", "") or "").strip() or None
        if subject_filter and subject_filter not in subjects_by_id and catalog_status == "available":
            # Unknown subject filter yields empty, not error, to preserve round-trip.
            activities_all = []
        else:
            activities_all = [] if catalog_status != "available" else _query_activities_for_page(
                catalog, query=query, activity_window=activity_window, tab=tab,
                subject_id=subject_filter)
        total_pages = max(1, (len(activities_all) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if page > total_pages and activities_all:
            return _bad("page", "out_of_range")
        start = (page - 1) * _PAGE_SIZE
        activities = [_display_activity(item, subjects_by_id) for item in activities_all[start:start + _PAGE_SIZE]]
        subjects = [item for item in list(catalog.get("subjects") or []) if isinstance(item, dict)] if catalog_status == "available" else []
        return render_template(
            "perspectives.html",
            catalog_status=catalog_status,
            creators=creators,
            coverage_by_creator=coverage,
            opinions=opinions if tab in {"latest", "opinions"} else [],
            activities=activities,
            activities_total=len(activities_all),
            subjects=subjects,
            subjects_by_id=subjects_by_id,
            consensus=consensus,
            query=query,
            selected_symbol=query.get("symbol"),
            selected_creator=query.get("creator_id"),
            selected_classification=query.get("stance"),
            activity_window=request.args.get("activity_window", "all") or "all",
            activity_tab=tab,
            activity_page=page,
            activity_pages=total_pages,
            subject_filter=subject_filter or "",
        )

    def stock_perspectives_page(market, symbol):
        catalog, catalog_status = _load_catalog()
        creator_ids = {
            item.get("id") for item in list(catalog.get("creators") or [])
            if isinstance(item, dict) and item.get("id")
        } if catalog_status != "unavailable" else None
        query, error = _parse_query(
            request.args,
            path_market=market,
            path_symbol=symbol,
            creator_ids=creator_ids,
        )
        if error:
            return error
        opinions = []
        consensus = None
        activities = []
        if catalog_status == "available":
            opinions = _filtered_opinions(catalog, query)
            try:
                consensus = build_consensus(
                    _consensus_catalog(catalog, query),
                    market=query["market"],
                    symbol=query["symbol"],
                    window_days=query["window"],
                    cutoff_at=query["cutoff_at_dt"],
                )
            except ValueError as exc:
                return _bad("symbol", str(exc))
            try:
                raw_activities = query_activities(
                    catalog, subject_id=None, market=query["market"], symbol=query["symbol"],
                    cutoff_at=query["cutoff_at_dt"], window_days=None)
            except ValueError:
                raw_activities = []
            subjects_by_id = _subjects_by_id(catalog)
            activities = [_display_activity(item, subjects_by_id) for item in raw_activities]
        return render_template(
            "stock_perspectives.html",
            catalog_status=catalog_status,
            query=query,
            consensus=consensus,
            opinions=opinions,
            activities=activities,
        )

    def creator_page(creator_id):
        catalog, catalog_status = _load_catalog()
        creators = list(catalog.get("creators") or []) if catalog_status == "available" else []
        creator = next((item for item in creators if isinstance(item, dict) and item.get("id") == creator_id), None)
        if catalog_status == "unavailable":
            creator = {"id": creator_id, "name": creator_id, "identity_status": "unavailable"}
        elif creator is None:
            abort(404)
        coverage = _coverage_by_creator(catalog).get(creator_id)
        creator_ids = {item.get("id") for item in creators if isinstance(item, dict) and item.get("id")}
        query, error = _parse_query(
            request.args,
            creator_ids=creator_ids if catalog_status != "unavailable" else None,
            forced_creator_id=creator_id,
        )
        if error:
            return error
        opinions = _filtered_opinions(catalog, query) if catalog_status == "available" else []
        related_activities = []
        if catalog_status == "available":
            try:
                raw_all = query_activities(catalog, subject_id=None, market=None, symbol=None,
                                           cutoff_at=query["cutoff_at_dt"], window_days=None)
            except ValueError:
                raw_all = []
            subjects_by_id = _subjects_by_id(catalog)
            related_activities = [_display_activity(item, subjects_by_id) for item in raw_all
                                  if str(item.get("publisher_creator_id") or "") == creator_id]
        return render_template(
            "creator.html",
            creator=creator,
            ingestion=(catalog.get("ingestion") or {}).get(creator_id),
            coverage=coverage,
            catalog_status=catalog_status,
            opinions=opinions,
            related_activities=related_activities,
            query=query,
        )

    def subject_page(subject_id):
        catalog, catalog_status = _load_catalog()
        if catalog_status == "unavailable":
            return render_template(
                "subject.html",
                catalog_status=catalog_status,
                subject=None,
                activities=[],
                query={"cutoff_at": "", "window": 7},
            )
        subjects_by_id = _subjects_by_id(catalog)
        subject = subjects_by_id.get(subject_id)
        if subject is None:
            abort(404)
        query, error = _parse_query(request.args, creator_ids=None)
        if error:
            return error
        activity_window, error = _parse_activity_window(request.args)
        if error:
            return error
        try:
            raw_activities = query_activities(
                catalog, subject_id=subject_id, market=query.get("market") or None,
                symbol=query.get("symbol") or None, cutoff_at=query["cutoff_at_dt"],
                window_days=activity_window)
        except ValueError:
            raw_activities = []
        activities = [_display_activity(item, subjects_by_id) for item in raw_activities]
        return render_template(
            "subject.html",
            catalog_status=catalog_status,
            subject=subject,
            activities=activities,
            query=query,
        )

    app.add_url_rule(
        "/industries/ai-server/relationships",
        "industry_relationships_page", relationships_page,
    )
    app.add_url_rule(
        "/api/research/relationships",
        "industry_relationships_api", relationships_api,
    )
    app.add_url_rule("/compare", "stock_compare_page", compare_page)
    app.add_url_rule("/events", "research_events_page", events_page)
    app.add_url_rule("/perspectives", "perspectives_page", perspectives_page)
    app.add_url_rule("/perspectives/stocks/<market>/<symbol>", "stock_perspectives_page", stock_perspectives_page)
    app.add_url_rule("/perspectives/<creator_id>", "creator_page", creator_page)
    app.add_url_rule("/perspectives/subjects/<subject_id>", "subject_page", subject_page)
