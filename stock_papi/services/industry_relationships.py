"""Fail-closed reader for the reviewed AI-server relationship catalog."""

from __future__ import annotations

import copy
import datetime as dt
import json
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
    {"nvidianews.nvidia.com", "news.skhynix.com", "investor.nvidia.com"}
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
    """Accept only HTTPS URLs on the three approved official domains."""
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
    if not isinstance(node, dict) or set(node) != {"symbol", "name"}:
        raise IndustryRelationshipSchemaError("relationship node schema is invalid")
    symbol = _text(node.get("symbol"), "relationship node symbol", 20)
    if not symbol.isascii() or symbol != symbol.upper() or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.^-_" for c in symbol):
        raise IndustryRelationshipSchemaError("relationship node symbol is invalid")
    return {"symbol": symbol, "name": _text(node.get("name"), "relationship node name", 120)}


def _stage(stage):
    if not isinstance(stage, dict) or set(stage) != {"id", "name", "nodes"}:
        raise IndustryRelationshipSchemaError("relationship stage schema is invalid")
    nodes = stage.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES_PER_STAGE:
        raise IndustryRelationshipSchemaError("relationship stage nodes are invalid")
    nodes = [_node(node) for node in nodes]
    if len({node["symbol"] for node in nodes}) != len(nodes):
        raise IndustryRelationshipSchemaError("duplicate relationship node")
    return {"id": _id(stage["id"], "stage id", 50), "name": _text(stage["name"], "stage name", 120), "nodes": nodes}


def _source(source):
    required = {"id", "url", "title", "publisher", "published_at", "locator", "checked_at", "status"}
    if not isinstance(source, dict) or set(source) != required:
        raise IndustryRelationshipSchemaError("source schema is invalid")
    url = _text(source["url"], "source url", 2048)
    if not is_allowed_source_url(url):
        raise IndustryRelationshipSchemaError("source url is not allowlisted")
    if source["status"] not in SOURCE_STATUSES:
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
        or from_node["symbol"] not in nodes
        or to_node["symbol"] not in nodes
        or from_node["symbol"] == to_node["symbol"]
        or nodes[from_node["symbol"]] != from_node
        or nodes[to_node["symbol"]] != to_node
    ):
        raise IndustryRelationshipSchemaError("relationship references are invalid")
    if item["type"] not in RELATION_TYPES or item["status"] not in RELATION_STATUSES:
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
        or not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES
        or not isinstance(relationships, list) or not 1 <= len(relationships) <= MAX_RELATIONSHIPS
    ):
        raise IndustryRelationshipSchemaError("relationship catalog size is invalid")
    stages = [_stage(stage) for stage in stages]
    stage_ids = [stage["id"] for stage in stages]
    if len(set(stage_ids)) != len(stage_ids):
        raise IndustryRelationshipSchemaError("duplicate relationship stage id")
    all_nodes = [node for stage in stages for node in stage["nodes"]]
    if len(all_nodes) > MAX_NODES or len({node["symbol"] for node in all_nodes}) != len(all_nodes):
        raise IndustryRelationshipSchemaError("relationship catalog nodes are invalid")
    nodes = {node["symbol"]: node for node in all_nodes}
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
        endpoints = tuple(sorted((item["from"]["symbol"], item["to"]["symbol"]))) if item["type"] in _UNDIRECTED else (item["from"]["symbol"], item["to"]["symbol"])
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
    target = as_of or dt.date.today()
    if isinstance(target, dt.datetime):
        target = target.date()
    if not isinstance(target, dt.date):
        raise IndustryRelationshipSchemaError("relationship as_of is invalid")
    valid_to = item.get("valid_to")
    if valid_to and target > dt.date.fromisoformat(valid_to):
        return False
    reviewed_at = item.get("reviewed_at")
    if reviewed_at:
        try:
            reviewed = dt.date.fromisoformat(reviewed_at)
        except ValueError:
            return False
        if target > reviewed + dt.timedelta(days=review_days):
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
    "relationship_is_current",
    "relationships_for", "validate_relationship_catalog",
]
