import hashlib
import unittest

from stock_papi.repositories.report_store import load_report_index, load_report_pdf


class ReportRepositoryTests(unittest.TestCase):
    def test_verified_pdf_is_returned_and_bad_hash_fails_closed(self):
        pdf = b"%PDF verified"
        item = {
            "pdf_path": f"objects/{hashlib.sha256(pdf).hexdigest()}.pdf",
            "pdf_size": len(pdf),
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        }
        self.assertEqual(load_report_pdf(item, load_object=lambda *_: pdf), pdf)
        self.assertIsNone(load_report_pdf(item, load_object=lambda *_: b"corrupt"))


if __name__ == "__main__":
    unittest.main()
