import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_papi.batch import public_activity_cli


def _subject():
    return {
        "subject_id": "test-household",
        "subject_kind": "household",
        "subject_name": "Test Household",
        "aliases": [],
        "identity_source_url": "https://ethics.house.gov/test",
        "identity_status": "verified",
    }


def _activity(activity_id="cli-act-001", locator="page:1,row:1", **overrides):
    row = {
        "activity_id": activity_id,
        "activity_type": "trade_disclosure",
        "publisher_creator_id": "",
        "subject_id": "test-household",
        "owner": "spouse",
        "owner_name": "Spouse A",
        "market": "US",
        "symbol": "INTC",
        "instrument_type": "common_stock",
        "security_name": "Intel",
        "security_identifier": "",
        "action": "purchase",
        "transaction_date": "2026-08-28",
        "holdings_as_of": "",
        "public_at": "2026-09-01T20:00:00Z",
        "public_time_precision": "timestamp",
        "first_seen_at": "2026-09-02T01:00:00Z",
        "reviewed_at": "2026-09-02T03:00:00Z",
        "amount_min": 1001,
        "amount_max": 15000,
        "currency": "USD",
        "quantity": None,
        "quantity_unit": "",
        "reported_value": None,
        "option_type": "",
        "strike": None,
        "expiry": "",
        "source_kind": "house_ptr",
        "source_url": "https://ethics.house.gov/cli-001",
        "source_document_id": "cli-001",
        "source_locator": locator,
        "source_sha256": hashlib.sha256(b"cli-evidence").hexdigest(),
        "reviewer": "cli-reviewer",
        "rights_status": "approved",
        "review_status": "confirmed",
        "source_status": "available",
        "supersedes_id": "",
        "withdraws_id": "",
        "summary": "CLI test summary",
        "limitations": "CLI test limitations",
    }
    row.update(overrides)
    return row


class PublicActivityCliTests(unittest.TestCase):
    def _write(self, path, document):
        Path(path).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def test_rejects_bad_input_without_touching_catalog(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            catalog_path = tmp_path / "catalog.json"
            catalog_text = json.dumps({"activities": []}, ensure_ascii=False)
            catalog_path.write_text(catalog_text, encoding="utf-8")
            input_path = tmp_path / "input.json"
            input_path.write_text("{not json", encoding="utf-8")
            output_path = tmp_path / "candidate.json"
            code = public_activity_cli.main(["--input", str(input_path),
                                             "--catalog", str(catalog_path),
                                             "--output", str(output_path)])
            self.assertNotEqual(code, 0)
            self.assertFalse(output_path.exists())
            self.assertEqual(catalog_path.read_text(encoding="utf-8"), catalog_text)

    def test_refuses_when_output_exists(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.json"
            catalog_path = tmp_path / "catalog.json"
            output_path = tmp_path / "candidate.json"
            self._write(input_path, {"subjects": [_subject()], "activities": [_activity()]})
            self._write(catalog_path, {"subjects": [], "activities": []})
            output_path.write_text("{}", encoding="utf-8")
            code = public_activity_cli.main(["--input", str(input_path),
                                             "--catalog", str(catalog_path),
                                             "--output", str(output_path)])
            self.assertNotEqual(code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "{}")

    def test_refuses_when_output_equals_input_or_catalog(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.json"
            self._write(input_path, {"subjects": [], "activities": []})
            code = public_activity_cli.main(["--input", str(input_path),
                                             "--catalog", str(input_path),
                                             "--output", str(input_path)])
            self.assertNotEqual(code, 0)

    def test_same_source_two_rows_produce_two_candidates(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.json"
            catalog_path = tmp_path / "catalog.json"
            output_path = tmp_path / "candidate.json"
            first = _activity("cli-act-001", "page:1,row:1")
            second = _activity("cli-act-002", "page:1,row:2")
            self._write(input_path, {"subjects": [_subject()], "activities": [first, second]})
            self._write(catalog_path, {"subjects": [], "activities": []})
            code = public_activity_cli.main(["--input", str(input_path),
                                             "--catalog", str(catalog_path),
                                             "--output", str(output_path)])
            self.assertEqual(code, 0)
            candidate = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(candidate["summary"]["added"], 2)
            self.assertEqual(candidate["summary"]["rejected"], 0)

    def test_pending_is_never_auto_promoted(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.json"
            catalog_path = tmp_path / "catalog.json"
            output_path = tmp_path / "candidate.json"
            row = _activity(review_status="pending_review")
            self._write(input_path, {"subjects": [_subject()], "activities": [row]})
            self._write(catalog_path, {"subjects": [], "activities": []})
            code = public_activity_cli.main(["--input", str(input_path),
                                             "--catalog", str(catalog_path),
                                             "--output", str(output_path)])
            self.assertEqual(code, 0)
            candidate = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(candidate["summary"]["pending"], 1)
            self.assertEqual(candidate["summary"]["added"], 0)


if __name__ == "__main__":
    unittest.main()
