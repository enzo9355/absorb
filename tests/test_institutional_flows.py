import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from jinja2 import DictLoader, Environment

from stock_papi.services.institutional_flows import (
    FIELDS, LABELS, MAX_BYTES, fetch_twse_flows, parse_twse_flows, validate_twse_flows,
)


def source_payload():
    # Deliberately nonzero foreign-dealer row: it must not be double counted.
    triples = [(30, 10, 20), (5, 15, -10), (0, 0, 0), (40, 100, -60), (3, 2, 1), (75, 125, -50)]
    return {"stat": "OK", "date": "20260717", "title": "115年07月17日 三大法人買賣金額統計表",
            "fields": FIELDS, "data": [[label, *(str(n * 1_000_000) for n in values)]
                                       for label, values in zip(LABELS, triples)]}


def source_raw(payload=None):
    return json.dumps(source_payload() if payload is None else payload, ensure_ascii=False).encode()


class InstitutionalFlowsTests(unittest.TestCase):
    def test_same_day_amounts_reconcile_and_bind_exact_raw_hash(self):
        raw = source_raw()
        flows = parse_twse_flows(raw, "2026-07-17")
        self.assertEqual((flows["foreign_net"], flows["investment_trust_net"], flows["dealer_net"]), (-60, 0, 10))
        self.assertEqual(flows["scope"], "TWSE")
        self.assertEqual(flows["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(validate_twse_flows(flows, "2026-07-17"), flows)
        for key, value in (("source_sha256", "a" * 64), ("foreign_net", 0), ("scope", "TW"),
                           ("source", "https://evil.example/"), ("source_body", flows["source_body"] + " ")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_twse_flows(dict(flows, **{key: value}), "2026-07-17")

    def test_rejects_wrong_date_fields_missing_duplicates_and_nonconservation(self):
        cases = []
        for key, value in (("date", "20260716"), ("title", "other report"), ("fields", FIELDS[::-1]), ("stat", "NOT_READY")):
            payload = source_payload()
            payload[key] = value
            cases.append(payload)
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.append(rows[0]),
                         lambda rows: rows.__setitem__(1, rows[0]),
                         lambda rows: rows[0].__setitem__(3, "999"),
                         lambda rows: rows[-1].__setitem__(slice(1, 4), ["76", "126", "-50"]),
                         lambda rows: rows[0].__setitem__(1, "NaN"),
                         lambda rows: rows[0].__setitem__(1, True)):
            payload = source_payload()
            mutation(payload["data"])
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_twse_flows(source_raw(payload), "2026-07-17")

    def test_http_boundary_rejects_redirects_and_oversize(self):
        for status, chunks in ((302, []), (200, [b"x" * (MAX_BYTES + 1)])):
            response = Mock(status_code=status)
            response.iter_content.return_value = chunks
            context = Mock()
            context.__enter__ = Mock(return_value=response)
            context.__exit__ = Mock(return_value=False)
            get = Mock(return_value=context)
            with self.assertRaises(ValueError):
                fetch_twse_flows("2026-07-17", http_get=get)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
        response.status_code = 200
        response.iter_content.return_value = [source_raw()]
        self.assertEqual(fetch_twse_flows("2026-07-17", http_get=get)["dealer_net"], 10)

    def test_report_keeps_scope_source_and_rejects_tampered_evidence(self):
        from tests.test_professional_report_html import ProfessionalReportHtmlTests
        from reporting.professional_builder import build_professional_post_close_artifact
        from reporting.professional_html import build_professional_report_view

        metadata = ProfessionalReportHtmlTests()._metadata()
        metadata["content"]["capital_flows"] = parse_twse_flows(source_raw(), "2026-07-17")
        report = build_professional_post_close_artifact(metadata, code_commit_sha="a" * 40)
        view = build_professional_report_view(report)
        self.assertEqual(view["capital_flows"]["data"]["total_institutional_net"], -50)
        env = Environment(loader=DictLoader({
            "report": Path("templates/reports/post_close_professional.html").read_text(encoding="utf-8"),
            "base.html": "{% block content %}{% endblock %}",
        }))
        html = env.get_template("report").render(report=view)
        self.assertIn("僅含上市市場，不含上櫃", html)
        self.assertIn("證交所三大法人買賣金額統計表", html)
        self.assertNotIn("source_body", html)
        metadata["content"]["capital_flows"]["source_sha256"] = "0" * 64
        invalid = build_professional_post_close_artifact(metadata, code_commit_sha="a" * 40)
        self.assertEqual(invalid.capital_flows.status, "unavailable")

    def test_candidate_build_fetches_once_and_preserves_missing_on_failure(self):
        from stock_papi.batch.observation_products_cli import build
        from tests.report_fixtures import stock_document, write_quant_publish
        from tests.test_batch_calendar import calendar_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stock = stock_document("2330", as_of="2026-07-17")
            stock.update(name="台積電", sample_data=False)
            publish = write_quant_publish(root, [stock])
            latest = json.loads((publish / "latest-TW.json").read_text())
            calendar = root / "calendar.json"
            calendar.write_text(json.dumps(calendar_document(2026)), encoding="utf-8")
            args = SimpleNamespace(root=root, source_manifest=f"quant/v1/{latest['manifest']}",
                                   source_manifest_sha256=latest["manifest_sha256"],
                                   source_market_date=dt.date(2026, 7, 17), calendar_artifact=[calendar])
            for failure in (None, ValueError("wrong date"), requests.Timeout("unavailable")):
                loader = Mock(return_value=parse_twse_flows(source_raw(), "2026-07-17"), side_effect=failure)
                with patch("reporting.cli._load_industry_map", return_value={"全市場": ["2330"]}):
                    receipt = build(args, today=dt.date(2026, 7, 17), load_capital_flows=loader)
                loader.assert_called_once()
                metadata = json.loads(Path(receipt["post_close_v2_path"]).read_text(encoding="utf-8"))
                if failure:
                    self.assertNotIn("capital_flows", metadata["content"])
                    self.assertTrue(any("法人金額" in warning for warning in metadata["warnings"]))
                else:
                    self.assertEqual(metadata["content"]["capital_flows"]["foreign_net"], -60)
