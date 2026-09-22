import hashlib
import json
import unittest

from reporting.exceptions import ReportWebError
from stock_papi.repositories.report_store import (
    load_report_index,
    load_report_metadata,
    load_report_metadata_by_sha,
    load_report_pdf,
)


class ReportRepositoryTests(unittest.TestCase):
    def test_v2_metadata_loaders_require_explicit_expected_market(self):
        with self.assertRaises(ValueError):
            load_report_metadata(
                {"metadata": "metadata/" + "a" * 64 + ".json"},
                load_object=lambda *_: self.fail("must reject before object read"),
                version="v2",
            )
        with self.assertRaises(ValueError):
            load_report_metadata_by_sha(
                "a" * 64,
                load_object=lambda *_: self.fail("must reject before object read"),
            )

    def test_v2_index_market_must_match_requested_object(self):
        for requested_market, document_market in (("US", "TW"), ("TW", "US")):
            with self.subTest(
                requested_market=requested_market,
                document_market=document_market,
            ):
                content = json.dumps({
                    "schema_version": 2,
                    "kind": "absorb-report-index",
                    "market": document_market,
                    "updated_at": "2026-08-24T12:00:00Z",
                    "reports": [],
                }).encode("utf-8")

                with self.assertRaises(ReportWebError):
                    load_report_index(
                        load_object=lambda *_: content,
                        max_bytes=1234,
                        version="v2",
                        market=requested_market,
                    )

    def test_v2_index_uses_fixed_allowlisted_prefix(self):
        calls = []
        self.assertIsNone(
            load_report_index(
                load_object=lambda path, size: calls.append((path, size)) or None,
                max_bytes=1234,
                version="v2",
            )
        )
        self.assertEqual(calls, [("reports/v2/index-TW.json", 1234)])
        with self.assertRaises(ValueError):
            load_report_index(
                load_object=lambda *_: None,
                max_bytes=1234,
                version="../../secret",
            )

    def test_verified_pdf_is_returned_and_bad_hash_fails_closed(self):
        pdf = b"%PDF verified"
        item = {
            "pdf_path": f"objects/{hashlib.sha256(pdf).hexdigest()}.pdf",
            "pdf_size": len(pdf),
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        }
        self.assertEqual(load_report_pdf(item, load_object=lambda *_: pdf), pdf)
        self.assertIsNone(load_report_pdf(item, load_object=lambda *_: b"corrupt"))


class Batch5ListDedupRegressionTests(unittest.TestCase):
    def _item(self, report_type, source, applicable, published, sha):
        return {
            "market": "US",
            "report_type": report_type,
            "source_market_date": source,
            "applicable_trading_date": applicable,
            "published_at": published,
            "metadata": f"metadata/{sha}.json",
            "metadata_sha256": sha,
            "title": f"報告 {source}",
            "summary": ["摘要"],
            "content_sha256": "c" * 64,
        }

    def test_same_source_post_close_keeps_latest_with_notice(self):
        from stock_papi.services.report_view import dedupe_reports_for_list

        older = self._item("post_close", "2026-08-19", "2026-08-19", "2026-08-19T10:00:00Z", "a" * 64)
        newer = self._item("post_close", "2026-08-19", "2026-08-20", "2026-08-20T10:00:00Z", "b" * 64)
        result = dedupe_reports_for_list([older, newer])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["metadata_sha256"], "b" * 64)
        self.assertIn("duplicate_notice", result[0])

    def test_full_identity_conflict_marks_unavailable(self):
        from stock_papi.services.report_view import dedupe_reports_for_list

        first = self._item("post_close", "2026-08-19", "2026-08-20", "2026-08-20T10:00:00Z", "b" * 64)
        second = self._item("post_close", "2026-08-19", "2026-08-20", "2026-08-20T11:00:00Z", "c" * 64)
        result = dedupe_reports_for_list([first, second])
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].get("index_conflict"))
        self.assertIn("duplicate_notice", result[0])

    def test_distinct_reports_all_survive(self):
        from stock_papi.services.report_view import dedupe_reports_for_list

        items = [
            self._item("post_close", "2026-09-11", "2026-09-14", "2026-09-12T04:00:00Z", "d" * 64),
            self._item("pre_market", "2026-09-11", "2026-09-14", "2026-09-14T12:00:00Z", "e" * 64),
        ]
        result = dedupe_reports_for_list(items)
        self.assertEqual(len(result), 2)
        self.assertFalse(any(item.get("index_conflict") for item in result))

    def test_us_inner_templates_share_freshness_banner(self):
        import pathlib

        for template in ("templates/us_market.html", "templates/us_industries.html"):
            text = pathlib.Path(template).read_text(encoding="utf-8")
            self.assertIn("data-freshness-status", text)
            self.assertIn("freshness-warning", text)
            self.assertNotIn("最新交易日", text.replace("目前沒有涵蓋最新交易日的已驗證資料", ""))


if __name__ == "__main__":
    unittest.main()
