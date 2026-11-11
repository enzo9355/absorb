"""Reviewed industry catalogs, shared relationship eligibility and company search."""

from __future__ import annotations

import copy
import datetime as dt
import json
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
MAX_CATALOG_BYTES = 1_000_000
MAX_STAGES = 20
MAX_NODES = 100
MAX_SOURCES = 200
MAX_RELATIONSHIPS = 300
MAX_NODES_PER_STAGE = 30
RELATIONSHIP_REVIEW_DAYS = 90
ALLOWED_SOURCE_HOSTS = frozenset(
    {"nvidianews.nvidia.com", "news.skhynix.com", "investor.nvidia.com",
     "ir.amd.com", "usa.visa.com", "www.pfizer.com", "news.microsoft.com",
     "www.pepsico.com", "www.sec.gov"}
)
RELATION_TYPES = frozenset(
    {
        "supply", "partnership", "competition", "same_segment",
        "供應關係", "合作關係", "競爭關係", "同一環節／題材",
    }
)
RELATION_STATUSES = frozenset({"active", "historical", "pending_review"})
SOURCE_STATUSES = frozenset({"available", "unavailable"})
_UNDIRECTED = frozenset(
    {"partnership", "competition", "same_segment", "合作關係", "競爭關係", "同一環節／題材"}
)
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "research" / "ai-server.json"
CATALOGS = (
    ("ai-server", "AI 伺服器"), ("semiconductors", "半導體"),
    ("electric-vehicles", "電動車與車用科技"), ("energy-storage", "能源與儲能"),
    ("financial-payments", "金融與支付"), ("healthcare", "醫療與製藥"),
    ("shipping-logistics", "航運與物流"), ("consumer-retail", "消費與零售"),
)
TYPE_LABELS = {"supply": "供應關係", "partnership": "合作關係",
               "competition": "競爭關係", "same_segment": "同一環節／題材"}


class IndustryRelationshipError(ValueError):
    """Base error for relationship data."""


class IndustryRelationshipSchemaError(IndustryRelationshipError):
    """The catalog is malformed or contains untrusted data."""


class IndustryRelationshipLoadError(IndustryRelationshipError):
    """The catalog could not be read safely."""


def _text(value, label, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IndustryRelationshipSchemaError(f"{label} is invalid")
    return value.strip()


def _id(value, label, limit=100):
    value = _text(value, label, limit)
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in value):
        raise IndustryRelationshipSchemaError(f"{label} is invalid")
    return value


def _date(value, label):
    if not isinstance(value, str):
        raise IndustryRelationshipSchemaError(f"{label} is invalid")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IndustryRelationshipSchemaError(f"{label} is invalid") from exc
    if parsed.isoformat() != value:
        raise IndustryRelationshipSchemaError(f"{label} is invalid")
    return value


def is_allowed_source_url(value):
    """Accept only HTTPS URLs on explicitly approved official domains."""
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in ALLOWED_SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
        or not parsed.path
        or parsed.path == "/"
    ):
        return False
    return host != "nvidianews.nvidia.com" or parsed.path in ("/news",) or parsed.path.startswith("/news/")


def _node(node):
    if (not isinstance(node, dict) or not {"symbol", "name"} <= set(node)
            or set(node) - {"symbol", "name", "market", "aliases"}):
        raise IndustryRelationshipSchemaError("relationship node schema is invalid")
    symbol = _text(node.get("symbol"), "relationship node symbol", 20)
    if not symbol.isascii() or symbol != symbol.upper() or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.^-_" for c in symbol):
        raise IndustryRelationshipSchemaError("relationship node symbol is invalid")
    result = {"symbol": symbol, "name": _text(node.get("name"), "relationship node name", 120)}
    if "market" in node:
        if not isinstance(node["market"], str) or node["market"] not in {"TW", "US", "KR"}:
            raise IndustryRelationshipSchemaError("company market is invalid")
        result["market"] = node["market"]
    if "aliases" in node:
        if not isinstance(node["aliases"], list) or len(node["aliases"]) > 10:
            raise IndustryRelationshipSchemaError("company aliases are invalid")
        result["aliases"] = [_text(x, "company alias", 120) for x in node["aliases"]]
    return result


def company_market(node):
    # Legacy AI catalog predates explicit markets; its six-digit ticker is Korean.
    return node.get("market") or ("KR" if node["symbol"] == "000660" else
                                  "TW" if node["symbol"].isdigit() and len(node["symbol"]) == 4 else "US")


def company_key(node):
    return f"{company_market(node)}:{node['symbol']}"


def _stage(stage):
    if not isinstance(stage, dict) or set(stage) != {"id", "name", "nodes"}:
        raise IndustryRelationshipSchemaError("relationship stage schema is invalid")
    nodes = stage.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES_PER_STAGE:
        raise IndustryRelationshipSchemaError("relationship stage nodes are invalid")
    nodes = [_node(node) for node in nodes]
    if len({company_key(node) for node in nodes}) != len(nodes):
        raise IndustryRelationshipSchemaError("duplicate relationship node")
    return {"id": _id(stage["id"], "stage id", 50), "name": _text(stage["name"], "stage name", 120), "nodes": nodes}


def _source(source):
    required = {"id", "url", "title", "publisher", "published_at", "locator", "checked_at", "status"}
    if not isinstance(source, dict) or set(source) != required:
        raise IndustryRelationshipSchemaError("source schema is invalid")
    url = _text(source["url"], "source url", 2048)
    if not is_allowed_source_url(url):
        raise IndustryRelationshipSchemaError("source url is not allowlisted")
    if not isinstance(source["status"], str) or source["status"] not in SOURCE_STATUSES:
        raise IndustryRelationshipSchemaError("source status is invalid")
    return {
        "id": _id(source["id"], "source id"),
        "url": url,
        "title": _text(source["title"], "source title", 300),
        "publisher": _text(source["publisher"], "source publisher", 120),
        "published_at": _date(source["published_at"], "source published_at"),
        "locator": _text(source["locator"], "source locator", 300),
        "checked_at": _date(source["checked_at"], "source checked_at"),
        "status": source["status"],
    }


def _relationship(item, nodes, sources):
    required = {"id", "from", "to", "type", "product_scope", "source", "reviewed_at", "status"}
    optional = {"description", "valid_from", "valid_to"}
    if not isinstance(item, dict) or not required <= set(item) or set(item) - required - optional:
        raise IndustryRelationshipSchemaError("relationship schema is invalid")
    source_ref = item["source"]
    if not isinstance(source_ref, dict) or not {"id", "title", "url"} <= set(source_ref):
        raise IndustryRelationshipSchemaError("relationship source reference is invalid")
    source = sources.get(_id(source_ref["id"], "relationship source id"))
    from_node, to_node = _node(item["from"]), _node(item["to"])
    if (
        source is None
        or source["title"] != source_ref["title"]
        or source["url"] != source_ref["url"]
        or company_key(from_node) not in nodes
        or company_key(to_node) not in nodes
        or company_key(from_node) == company_key(to_node)
        or nodes[company_key(from_node)] != from_node
        or nodes[company_key(to_node)] != to_node
    ):
        raise IndustryRelationshipSchemaError("relationship references are invalid")
    if (not isinstance(item["type"], str) or item["type"] not in RELATION_TYPES
            or not isinstance(item["status"], str) or item["status"] not in RELATION_STATUSES):
        raise IndustryRelationshipSchemaError("relationship type or status is invalid")
    result = {
        "id": _id(item["id"], "relationship id"),
        "from": from_node,
        "to": to_node,
        "type": item["type"],
        "product_scope": _text(item["product_scope"], "relationship product_scope", 240),
        "source": copy.deepcopy(source),
        "reviewed_at": _date(item["reviewed_at"], "relationship reviewed_at"),
        "status": item["status"],
    }
    if "description" in item:
        result["description"] = _text(item["description"], "relationship description", 800)
    if "valid_from" in item:
        result["valid_from"] = _date(item["valid_from"], "relationship valid_from")
    if "valid_to" in item:
        result["valid_to"] = None if item["valid_to"] is None else _date(item["valid_to"], "relationship valid_to")
        if result.get("valid_from") and result["valid_to"] and result["valid_to"] < result["valid_from"]:
            raise IndustryRelationshipSchemaError("relationship validity is invalid")
    return result


def validate_relationship_catalog(document):
    """Validate and detach a complete relationship catalog."""
    required = {"schema_version", "catalog_id", "topic", "coverage_note", "updated_at", "stages", "sources", "relationships"}
    if not isinstance(document, dict) or set(document) != required or document.get("schema_version") != SCHEMA_VERSION:
        raise IndustryRelationshipSchemaError("relationship catalog schema is invalid")
    stages, sources, relationships = document["stages"], document["sources"], document["relationships"]
    if (
        not isinstance(stages, list) or not 1 <= len(stages) <= MAX_STAGES
        or not isinstance(sources, list) or not 0 <= len(sources) <= MAX_SOURCES
        or not isinstance(relationships, list) or not 0 <= len(relationships) <= MAX_RELATIONSHIPS
    ):
        raise IndustryRelationshipSchemaError("relationship catalog size is invalid")
    stages = [_stage(stage) for stage in stages]
    stage_ids = [stage["id"] for stage in stages]
    if len(set(stage_ids)) != len(stage_ids):
        raise IndustryRelationshipSchemaError("duplicate relationship stage id")
    all_nodes = [node for stage in stages for node in stage["nodes"]]
    if len(all_nodes) > MAX_NODES or len({company_key(node) for node in all_nodes}) != len(all_nodes):
        raise IndustryRelationshipSchemaError("relationship catalog nodes are invalid")
    nodes = {company_key(node): node for node in all_nodes}
    sources = [_source(source) for source in sources]
    source_ids, source_urls = [source["id"] for source in sources], [source["url"] for source in sources]
    if len(set(source_ids)) != len(source_ids) or len(set(source_urls)) != len(source_urls):
        raise IndustryRelationshipSchemaError("duplicate source")
    sources_by_id = {source["id"]: source for source in sources}
    relationships = [_relationship(item, nodes, sources_by_id) for item in relationships]
    relation_ids = [item["id"] for item in relationships]
    if len(set(relation_ids)) != len(relation_ids):
        raise IndustryRelationshipSchemaError("duplicate relationship id")
    seen = set()
    for item in relationships:
        if item["status"] == "active" and item["source"]["status"] != "available":
            raise IndustryRelationshipSchemaError("active relationship source is unavailable")
        endpoints = (company_key(item["from"]), company_key(item["to"]))
        if item["type"] in _UNDIRECTED:
            endpoints = tuple(sorted(endpoints))
        identity = (item["type"], endpoints, item["product_scope"])
        if identity in seen:
            raise IndustryRelationshipSchemaError("duplicate relationship edge")
        seen.add(identity)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": _id(document["catalog_id"], "catalog id", 80),
        "topic": _text(document["topic"], "catalog topic", 200),
        "coverage_note": _text(document["coverage_note"], "catalog coverage_note", 500),
        "updated_at": _date(document["updated_at"], "catalog updated_at"),
        "stages": stages,
        "sources": sources,
        "relationships": relationships,
    }


def relationship_is_current(item, *, as_of=None, review_days=RELATIONSHIP_REVIEW_DAYS):
    """Return whether an active relationship is inside its review window."""
    if not isinstance(item, dict) or item.get("status") != "active":
        return False
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    if source.get("status") not in (None, "available"):
        return False
    target = as_of or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    if isinstance(target, dt.datetime):
        target = target.date()
    if not isinstance(target, dt.date):
        raise IndustryRelationshipSchemaError("relationship as_of is invalid")
    try:
        if item.get("valid_to") and target > dt.date.fromisoformat(item["valid_to"]):
            return False
        if item.get("valid_from") and target < dt.date.fromisoformat(item["valid_from"]):
            return False
        reviewed = dt.date.fromisoformat(item["reviewed_at"])
        if not reviewed <= target <= reviewed + dt.timedelta(days=review_days):
            return False
        for field in ("published_at", "checked_at"):
            if source.get(field) and dt.date.fromisoformat(source[field]) > target:
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def load_relationships(path=None):
    """Read the default catalog or a supplied path, enforcing the byte limit."""
    catalog_path = Path(path) if path is not None else _DEFAULT_PATH
    try:
        content = catalog_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise IndustryRelationshipLoadError("relationship catalog is unavailable") from exc
    if len(content) > MAX_CATALOG_BYTES:
        raise IndustryRelationshipLoadError("relationship catalog exceeds size limit")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndustryRelationshipLoadError("relationship catalog is not valid JSON") from exc
    return validate_relationship_catalog(document)


def load_relationship_catalog(path=None):
    return load_relationships(path)


def load_relationship_atlas(directory=None):
    """Isolate unreadable catalogs instead of hiding healthy industries."""
    root = Path(directory) if directory is not None else _DEFAULT_PATH.parent
    result = []
    for catalog_id, topic in CATALOGS:
        try:
            catalog = load_relationships(root / f"{catalog_id}.json")
            if catalog["catalog_id"] != catalog_id:
                raise IndustryRelationshipSchemaError("catalog identity mismatch")
        except IndustryRelationshipError:
            catalog = {"catalog_id": catalog_id, "topic": topic, "stages": [],
                       "relationships": [], "sources": [], "unavailable": True,
                       "coverage_note": "此產業資料暫時無法驗證，其他產業仍可查詢。"}
        result.append(catalog)
    return result


def load_all_relationships():
    """Compatibility view for stock details and ASKsorb: current edges only."""
    catalogs = load_relationship_atlas()
    return {
        "schema_version": 1, "catalog_id": "industry-atlas", "topic": "產業關係",
        "updated_at": max((c.get("updated_at", "") for c in catalogs), default=""),
        "coverage_note": "僅收錄有來源的部分公司關係；未收錄不代表沒有關係。",
        "stages": [stage for c in catalogs for stage in c["stages"]],
        "relationships": [edge for c in catalogs for edge in c["relationships"] if relationship_is_current(edge)],
    }


def _search_text(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


def build_atlas_view(catalogs, *, industry="ai-server", query="", market="", focus=None, as_of=None):
    """Build the same bounded, escaped-by-renderer view for HTML and the API."""
    if (not isinstance(query, str) or len(query) > 120
            or not isinstance(market, str) or market not in {"", "TW", "US", "KR"}
            or (focus is not None and (not isinstance(focus, str) or len(focus) > 30))):
        raise IndustryRelationshipSchemaError("invalid atlas query")
    selected = next((c for c in catalogs if c["catalog_id"] == industry), None)
    if selected is None:
        raise IndustryRelationshipSchemaError("unknown industry")
    companies = {}
    industries = []
    for catalog in catalogs:
        membership = {"id": catalog["catalog_id"], "topic": catalog["topic"]}
        catalog_keys = set()
        for stage in catalog.get("stages", []):
            for node in stage.get("nodes", []):
                key = company_key(node)
                catalog_keys.add(key)
                item = companies.setdefault(key, {**node, "key": key, "market": company_market(node),
                                                  "industries": [], "roles": [], "search_names": []})
                if membership not in item["industries"]:
                    item["industries"].append(membership)
                if stage["name"] not in item["roles"]:
                    item["roles"].append(stage["name"])
                item["search_names"].extend([node["name"], *node.get("aliases", [])])
        industries.append({**membership, "company_count": len(catalog_keys),
                           "unavailable": bool(catalog.get("unavailable"))})
    selected_company = None
    if focus:
        matches = [c for c in companies.values() if focus.upper() in (c["key"], c["symbol"])]
        if len(matches) != 1 or industry not in {m["id"] for m in matches[0]["industries"]}:
            raise IndustryRelationshipSchemaError("unknown or ambiguous company")
        selected_company = matches[0]
    terms = _search_text(query).split()
    results = [c for c in companies.values()
               if (not market or c["market"] == market)
               and all(t in _search_text(" ".join([c["symbol"], *c["search_names"]])) for t in terms)] if terms else []
    results.sort(key=lambda c: (_search_text(c["symbol"]) != _search_text(query), c["name"], c["key"]))
    current, archived = [], []
    for edge in selected.get("relationships", []):
        if edge.get("status") == "pending_review":
            continue
        endpoints = (company_key(edge["from"]), company_key(edge["to"]))
        if selected_company and selected_company["key"] not in endpoints:
            continue
        if not selected_company and market and not any(companies[k]["market"] == market for k in endpoints):
            continue
        row = copy.deepcopy(edge)
        row["from"], row["to"] = (companies[k] for k in endpoints)
        row["type_label"] = TYPE_LABELS.get(row["type"], row["type"])
        row["directed"] = row["type"] in {"supply", "供應關係"}
        if relationship_is_current(edge, as_of=as_of):
            row["display_status"] = "已核對來源"
            current.append(row)
        else:
            row["display_status"] = "歷史紀錄" if edge.get("status") == "historical" else "待重新確認／未生效"
            archived.append(row)
    connected_keys = {node["key"] for edge in current for node in (edge["from"], edge["to"])}
    if selected_company:
        connected_keys.add(selected_company["key"])
    stages = [{**s, "nodes": [companies[company_key(n)] for n in s.get("nodes", [])
                              if not market or company_market(n) == market or company_key(n) in connected_keys]}
              for s in selected.get("stages", [])]
    public_catalog = {k: selected[k] for k in ("catalog_id", "topic", "coverage_note", "updated_at", "unavailable") if k in selected}
    return {"industries": industries, "catalog": public_catalog, "stages": stages,
            "relationships": current, "archived_relationships": archived,
            "search_results": results, "query": query.strip(), "selected_market": market,
            "selected_company": selected_company, "focus": selected_company["key"] if selected_company else "",
            "company_count": len(companies), "industry": industry}


def relationships_for(catalog, *, company_id=None, relation_type=None, include_historical=False, as_of=None):
    """Filter a validated catalog by symbol and relation type."""
    catalog = validate_relationship_catalog(catalog)
    if relation_type is not None and relation_type not in RELATION_TYPES:
        raise IndustryRelationshipSchemaError("relationship type is invalid")
    if company_id is not None and not isinstance(company_id, str):
        raise IndustryRelationshipSchemaError("company symbol is invalid")
    return [
        copy.deepcopy(item)
        for item in catalog["relationships"]
        if (include_historical or relationship_is_current(item, as_of=as_of))
        and (company_id is None or company_id in (item["from"]["symbol"], item["to"]["symbol"]))
        and (relation_type is None or item["type"] == relation_type)
    ]


__all__ = [
    "ALLOWED_SOURCE_HOSTS", "IndustryRelationshipError", "IndustryRelationshipLoadError",
    "IndustryRelationshipSchemaError", "MAX_CATALOG_BYTES", "MAX_RELATIONSHIPS", "MAX_SOURCES",
    "RELATION_TYPES", "RELATIONSHIP_REVIEW_DAYS", "is_allowed_source_url", "load_relationship_catalog", "load_relationships",
    "relationship_is_current", "load_relationship_atlas", "load_all_relationships",
    "build_atlas_view", "company_market", "company_key",
    "relationships_for", "validate_relationship_catalog",
]
