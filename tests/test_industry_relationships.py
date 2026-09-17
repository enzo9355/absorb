import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from stock_papi.services.industry_relationships import (
    ALLOWED_SOURCE_HOSTS,
    MAX_CATALOG_BYTES,
    IndustryRelationshipLoadError,
    IndustryRelationshipSchemaError,
    is_allowed_source_url,
    load_relationships,
    relationship_is_current,
    relationships_for,
    validate_relationship_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "research" / "ai-server.json"


class IndustryRelationshipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_default_catalog_loads_and_has_bounded_shape(self):
        catalog = load_relationships()

        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["catalog_id"], "ai-server")
        self.assertEqual(catalog["topic"], "AI 伺服器產業鏈")
        self.assertTrue(catalog["stages"])
        self.assertTrue(catalog["sources"])
        self.assertTrue(catalog["relationships"])
        self.assertLessEqual(
            sum(len(stage["nodes"]) for stage in catalog["stages"]), 100
        )
        self.assertLessEqual(len(catalog["sources"]), 200)
        self.assertLessEqual(len(catalog["relationships"]), 300)

    def test_default_sources_use_only_allowlisted_official_hosts(self):
        self.assertEqual(
            ALLOWED_SOURCE_HOSTS,
            frozenset(
                {
                    "nvidianews.nvidia.com",
                    "news.skhynix.com",
                    "investor.nvidia.com",
                }
            ),
        )
        for source in self.document["sources"]:
            self.assertTrue(is_allowed_source_url(source["url"]))

    def test_source_allowlist_rejects_untrusted_and_non_https_urls(self):
        for url in (
            "https://example.com/news",
            "http://nvidianews.nvidia.com/news/article",
            "https://nvidianews.nvidia.com.evil.example/news/article",
            "https://nvidianews.nvidia.com/private/article",
            "https://investor.nvidia.com.evil.example/news/article",
        ):
            self.assertFalse(is_allowed_source_url(url), url)

        document = copy.deepcopy(self.document)
        document["sources"][0]["url"] = "https://example.com/forged"
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

    def test_relationship_types_are_explicit_and_unknown_types_fail_closed(self):
        allowed = {
            "supply", "partnership", "competition", "same_segment",
            "供應關係", "合作關係", "競爭關係", "同一環節／題材",
        }
        self.assertTrue(
            {item["type"] for item in self.document["relationships"]}
            <= allowed
        )

        document = copy.deepcopy(self.document)
        document["relationships"][0]["type"] = "rumor"
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

    def test_relationships_reference_known_entities_and_sources(self):
        document = copy.deepcopy(self.document)
        document["relationships"][0]["from"]["symbol"] = "UNKNOWN"
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

        document = copy.deepcopy(self.document)
        document["relationships"][0]["source"]["id"] = "unknown-source"
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

    def test_duplicate_relationship_identity_is_rejected(self):
        document = copy.deepcopy(self.document)
        duplicate = copy.deepcopy(document["relationships"][0])
        duplicate["id"] = "duplicate-id"
        document["relationships"].append(duplicate)
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

    def test_duplicate_source_url_is_rejected(self):
        document = copy.deepcopy(self.document)
        duplicate = copy.deepcopy(document["sources"][0])
        duplicate["id"] = "duplicate-source"
        document["sources"].append(duplicate)
        with self.assertRaises(IndustryRelationshipSchemaError):
            validate_relationship_catalog(document)

    def test_relationship_query_returns_direct_active_relationships_without_duplicates(self):
        catalog = load_relationships()
        company_id = catalog["relationships"][0]["from"]["symbol"]
        result = relationships_for(catalog, company_id=company_id)

        self.assertTrue(result)
        self.assertTrue(
            all(
                company_id
                in (item["from"]["symbol"], item["to"]["symbol"])
                for item in result
            )
        )
        keys = {
            (
                item["type"],
                tuple(sorted((item["from"]["symbol"], item["to"]["symbol"]))),
                item["product_scope"],
            )
            for item in result
        }
        self.assertEqual(len(keys), len(result))

    def test_relationship_review_window_and_valid_to_remove_stale_edges(self):
        catalog = load_relationships()
        item = copy.deepcopy(catalog["relationships"][0])
        self.assertTrue(relationship_is_current(item, as_of=dt.date(2026, 9, 17)))
        self.assertFalse(relationship_is_current(item, as_of=dt.date(2026, 12, 17)))
        item["valid_to"] = "2026-09-16"
        self.assertFalse(relationship_is_current(item, as_of=dt.date(2026, 9, 17)))

    def test_loader_rejects_oversized_file_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "too-large.json"
            path.write_bytes(b"{" + b" " * MAX_CATALOG_BYTES + b"}")

            with self.assertRaises(IndustryRelationshipLoadError):
                load_relationships(path)


if __name__ == "__main__":
    unittest.main()
