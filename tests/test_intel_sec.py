import json
import tempfile
import unittest
from pathlib import Path

from stock_papi.batch.behavioral_intel_cli import run_offline_replay
from stock_papi.intel.sec_form4 import parse_form4, reconcile_rows


ACCESSION = "0000320193-26-000123"
SYNTHETIC_RECORD = {
    "accession": ACCESSION,
    "form_type": "4",
    "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/form4.xml",
    "accepted_at": "2026-09-23T20:00:00Z",
    "source_public_date": "2026-09-23",
    "source_timezone": "America/New_York",
    "first_seen_at": "2026-09-23T21:36:00Z",
    "rights_policy_version": "synthetic-test-only",
    "synthetic": True,
}

# Synthetic Form 4 only. It is not copied from or intended to represent a real filing.
SYNTHETIC_FORM4_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2026-09-21</periodOfReport>
  <issuer><issuerCik>0000320193</issuerCik><issuerName>Example Corp</issuerName>
    <issuerTradingSymbol>EXM</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0000000001</rptOwnerCik><rptOwnerName>Owner One</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther></reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0000000002</rptOwnerCik><rptOwnerName>Owner Two</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>0</isOfficer>
      <isTenPercentOwner>1</isTenPercentOwner><isOther>0</isOther></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-21</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>100.00</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>500</value></sharesOwnedFollowingTransaction>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-21</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>20</value></transactionShares>
        <transactionPricePerShare><footnoteId id="f1"/></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable><derivativeTransaction>
    <securityTitle><value>Option</value></securityTitle>
    <transactionDate><value>2026-09-21</value></transactionDate>
    <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>5</value></transactionShares>
      <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  </derivativeTransaction></derivativeTable>
  <footnotes><footnote id="f1">&lt;script&gt;example&lt;/script&gt;</footnote></footnotes>
</ownershipDocument>"""

SYNTHETIC_AMENDMENT_XML = b"""<ownershipDocument>
  <documentType>4/A</documentType><periodOfReport>2026-09-21</periodOfReport>
  <issuer><issuerCik>0000320193</issuerCik><issuerName>Example Corp</issuerName>
    <issuerTradingSymbol>EXM</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerCik>0000000001</rptOwnerCik>
    <rptOwnerName>Owner One</rptOwnerName></reportingOwnerId></reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>2026-09-21</value></transactionDate>
    <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>15</value></transactionShares>
      <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
    </transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


def parsed_document(raw=SYNTHETIC_FORM4_XML, record=None):
    return parse_form4(raw, dict(record or SYNTHETIC_RECORD))


def row(source_document_id, row_id, shares):
    return {
        "event_id": f"{source_document_id}:{row_id}",
        "event_version_id": f"{source_document_id}:{row_id}:v1",
        "source_document_id": source_document_id,
        "source_row_id": f"{source_document_id}:{row_id}",
        "normalized_payload": {"shares": shares, "transaction_date": "2026-09-21"},
        "aggregation_eligibility": False,
        "linkage_status": "not_applicable",
    }


class IntelSecTests(unittest.TestCase):
    def test_parser_keeps_reporting_owners_as_one_array_and_does_not_multiply_shares(self):
        result = parsed_document()

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filing"]["reporting_owners"]), 2)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["rows"][0]["normalized_payload"]["shares"], "100")
        self.assertEqual(len(result["rows"][0]["reporting_owners"]), 2)
        self.assertFalse(result["rows"][0]["aggregation_eligibility"])

    def test_decimal_values_and_footnote_only_price_stay_distinct(self):
        result = parsed_document()

        self.assertEqual(result["rows"][0]["normalized_payload"]["price_per_share"], "12.5")
        row_with_footnote = result["rows"][1]
        self.assertIsNone(row_with_footnote["normalized_payload"]["price_per_share"])
        self.assertEqual(row_with_footnote["normalized_payload"]["price_status"], "footnote_only")
        self.assertEqual(row_with_footnote["normalized_payload"]["price_footnote_ids"], ["f1"])

    def test_non_purchase_transaction_codes_are_not_mapped_to_purchase(self):
        result = parsed_document()
        self.assertEqual(
            [row["normalized_payload"]["transaction_classification"] for row in result["rows"]],
            ["purchase_disclosed", "sale_disclosed", "other_disclosure"],
        )

    def test_holding_rows_keep_owned_shares_without_becoming_transactions(self):
        holding_xml = SYNTHETIC_FORM4_XML.replace(
            b"</nonDerivativeTable>",
            b"<nonDerivativeHolding><securityTitle><value>Common Stock</value></securityTitle>"
            b"<sharesOwnedFollowingTransaction><value>700</value></sharesOwnedFollowingTransaction>"
            b"<directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>"
            b"</nonDerivativeHolding></nonDerivativeTable>",
        )

        result = parsed_document(holding_xml)
        holding = result["rows"][2]

        self.assertEqual(holding["row_kind"], "holding")
        self.assertEqual(holding["normalized_payload"]["shares"], "700")
        self.assertEqual(holding["normalized_payload"]["transaction_classification"], "other_disclosure")

    def test_partial_amendment_replaces_only_explicitly_linked_row(self):
        original_a = row("original", "A", "10")
        original_b = row("original", "B", "20")
        amended_a = row("amendment", "A2", "15")

        result = reconcile_rows(
            [original_a, original_b], [amended_a],
            [{
                "amendment_source_row_id": amended_a["source_row_id"],
                "original_source_row_id": original_a["source_row_id"],
                "status": "verified",
                "known_at": "2026-09-25T15:00:00Z",
                "evidence_ref": "synthetic-footnote-f1",
            }],
        )

        self.assertEqual(result["unresolved"], [])
        self.assertEqual(len(result["versions"]), 3)
        self.assertEqual(result["versions"][2]["event_id"], amended_a["event_id"])
        self.assertIn(original_b, result["versions"])
        self.assertEqual(result["versions"][2]["normalized_payload"]["shares"], "15")
        self.assertEqual(result["links"][0]["from_event_version_id"], original_a["event_version_id"])

    def test_ambiguous_amendment_link_keeps_all_candidates_ineligible(self):
        original_a = row("original", "A", "10")
        original_b = row("original", "B", "20")
        amended = row("amendment", "A2", "15")
        evidence = [{
            "amendment_source_row_id": amended["source_row_id"],
            "original_source_row_ids": [original_a["source_row_id"], original_b["source_row_id"]],
            "status": "ambiguous",
            "known_at": "2026-09-25T15:00:00Z",
        }]

        result = reconcile_rows([original_a, original_b], [amended], evidence)

        self.assertEqual(len(result["unresolved"]), 1)
        self.assertEqual(len(result["versions"]), 3)
        self.assertTrue(all(item["aggregation_eligibility"] is False for item in result["versions"]))
        self.assertTrue(all(item["linkage_status"] == "unresolved" for item in result["versions"]))

    def test_equal_values_in_separate_documents_are_not_auto_deduplicated(self):
        original = row("filing-a", "row-0", "100")
        separate = row("filing-b", "row-0", "100")

        result = reconcile_rows([original], [separate], [])

        self.assertEqual(len(result["versions"]), 2)
        self.assertNotEqual(result["versions"][0]["event_id"], result["versions"][1]["event_id"])
        self.assertEqual(len(result["unresolved"]), 1)

    def test_external_entities_are_rejected_and_footnote_markup_is_plain_text(self):
        unsafe = b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///C:/windows/win.ini">]><ownershipDocument>&ext;</ownershipDocument>'
        self.assertIn("unsafe_xml", parsed_document(unsafe)["errors"])

        result = parsed_document()
        self.assertEqual(result["filing"]["footnotes"]["f1"], "<script>example</script>")

    def test_malformed_xml_is_distinct_from_unsafe_xml(self):
        malformed = b"<ownershipDocument><documentType>4</documentType>"
        self.assertEqual(parsed_document(malformed)["errors"], ["xml_parse_error"])

    def test_malformed_revision_candidate_ids_are_rejected(self):
        original = row("original", "A", "10")
        amendment = row("amendment", "A2", "15")
        evidence = [{
            "amendment_source_row_id": amendment["source_row_id"],
            "original_source_row_ids": [original["source_row_id"], {"unexpected": "mapping"}],
            "status": "ambiguous",
            "known_at": "2026-09-25T15:00:00Z",
        }]

        with self.assertRaisesRegex(ValueError, "revision candidate ids"):
            reconcile_rows([original], [amendment], evidence)

    def test_metadata_rejects_non_sec_archive_urls(self):
        record = dict(
            SYNTHETIC_RECORD,
            source_url="https://sec.gov.evil.example/Archives/edgar/data/not-sec.xml",
        )
        self.assertIn("source_url_not_allowlisted", parsed_document(record=record)["errors"])

    def test_offline_replay_is_idempotent_and_missing_sidecar_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            for index in range(9):
                accession = f"0000320193-26-{123 + index:06d}"
                record = dict(
                    SYNTHETIC_RECORD,
                    accession=accession,
                    source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-', '')}/form4.xml",
                )
                (input_dir / f"filing-{index}.xml").write_bytes(SYNTHETIC_FORM4_XML)
                (input_dir / f"filing-{index}.record.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )
            (input_dir / "pending.xml").write_bytes(SYNTHETIC_FORM4_XML)

            first = run_offline_replay(
                input_dir, output_dir, "2026-09-26T00:00:00Z"
            )
            parsed_count = len(list((output_dir / "parsed").glob("*.json")))
            second = run_offline_replay(
                input_dir, output_dir, "2026-09-26T00:00:00Z"
            )

            self.assertEqual(first["counts"], {
                "discovered": 10, "parsed": 9, "pending": 1,
                "quarantined": 0, "explicitly_excluded": 0,
            })
            self.assertEqual(first["input_file_acquisition_coverage"], 0.9)
            self.assertEqual(first["source_coverage_status"], "partial")
            self.assertFalse(first["source_coverage_complete"])
            self.assertEqual(second["counts"], first["counts"])
            self.assertEqual(len(list((output_dir / "parsed").glob("*.json"))), parsed_count)
            self.assertEqual(len(list((output_dir / "raw").glob("*.xml"))), 1)
            checkpoint = json.loads((output_dir / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["state"], "complete")
            self.assertTrue((output_dir / checkpoint["discovery_ref"]).is_file())

    def test_offline_replay_excludes_documents_first_seen_after_cutoff(self):
        future_record = dict(
            SYNTHETIC_RECORD,
            first_seen_at="2026-09-26T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "future.xml").write_bytes(SYNTHETIC_FORM4_XML)
            (input_dir / "future.record.json").write_text(
                json.dumps(future_record), encoding="utf-8"
            )

            result = run_offline_replay(input_dir, output_dir, "2026-09-25T00:00:00Z")

            self.assertEqual(result["counts"]["parsed"], 0)
            self.assertEqual(result["counts"]["explicitly_excluded"], 1)
            self.assertEqual(result["items"][0]["status"], "explicitly_excluded")
            self.assertEqual(result["items"][0]["errors"], ["first_seen_after_cutoff"])
            self.assertFalse((output_dir / "raw").exists())

    def test_offline_replay_keeps_unamended_rows_and_versions_an_explicit_4a_link(self):
        amendment_accession = "0000320193-26-000124"
        amendment_record = dict(
            SYNTHETIC_RECORD,
            accession=amendment_accession,
            form_type="4/A",
            source_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000124/form4.xml",
            first_seen_at="2026-09-25T15:00:00Z",
            linkage_evidence=[{
                "amendment_source_row_id": f"{amendment_accession}:non_derivative:0",
                "original_source_row_id": f"{ACCESSION}:non_derivative:0",
                "status": "verified",
                "known_at": "2026-09-25T15:00:00Z",
                "evidence_ref": "synthetic-footnote-f1",
            }],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "a-original.xml").write_bytes(SYNTHETIC_FORM4_XML)
            (input_dir / "a-original.record.json").write_text(
                json.dumps(SYNTHETIC_RECORD), encoding="utf-8"
            )
            (input_dir / "b-amendment.xml").write_bytes(SYNTHETIC_AMENDMENT_XML)
            (input_dir / "b-amendment.record.json").write_text(
                json.dumps(amendment_record), encoding="utf-8"
            )

            result = run_offline_replay(input_dir, output_dir, "2026-09-26T00:00:00Z")
            reconciled = json.loads(
                (output_dir / result["reconciliation_ref"]).read_text(encoding="utf-8")
            )

            self.assertEqual(result["reconciliation"]["unresolved_count"], 0)
            self.assertEqual(result["reconciliation"]["link_count"], 1)
            self.assertEqual(len(reconciled["versions"]), 4)
            self.assertEqual(reconciled["versions"][1]["normalized_payload"]["shares"], "20")
            self.assertEqual(
                reconciled["versions"][3]["supersedes_version_id"],
                reconciled["versions"][0]["event_version_id"],
            )

    def test_offline_replay_does_not_store_when_source_storage_rights_are_unknown(self):
        record = dict(SYNTHETIC_RECORD, synthetic=False)
        record.pop("rights_policy_version")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "filing.xml").write_bytes(SYNTHETIC_FORM4_XML)
            (input_dir / "filing.record.json").write_text(json.dumps(record), encoding="utf-8")

            result = run_offline_replay(input_dir, output_dir, "2026-09-26T00:00:00Z")

            self.assertEqual(result["counts"]["pending"], 1)
            self.assertEqual(result["items"][0]["errors"], ["rights_policy_unknown"])
            self.assertFalse((output_dir / "raw").exists())

    def test_offline_replay_refuses_protected_production_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            input_dir.mkdir()
            with self.assertRaises(ValueError):
                run_offline_replay(input_dir, Path(r"D:\AbsorbData\behavioral-intel"), "2026-09-26T00:00:00Z")

    def test_successful_zero_row_document_is_not_zero_activity_coverage(self):
        # A structurally valid form with no transaction/holding tables is still not an index-wide zero.
        empty = b"""<ownershipDocument><documentType>4</documentType><periodOfReport>2026-09-21</periodOfReport>
        <issuer><issuerCik>0000320193</issuerCik><issuerName>Example</issuerName></issuer>
        <reportingOwner><reportingOwnerId><rptOwnerCik>0000000001</rptOwnerCik><rptOwnerName>Owner</rptOwnerName></reportingOwnerId></reportingOwner>
        </ownershipDocument>"""
        result = parsed_document(empty)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["rows"], [])
        self.assertNotIn("no_event_observed", result["filing"])


if __name__ == "__main__":
    unittest.main()
