import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests import test_research_routes


class OpinionReviewTests(unittest.TestCase):
    def test_release_rejects_pending_and_stale_base_preserving_original(self):
        self.assertIsNotNone(importlib.util.find_spec('stock_papi.batch.opinion_review_cli'))
        from stock_papi.batch.opinion_review_cli import main
        import hashlib
        catalog = test_research_routes.ResearchRouteTests()._opinion_catalog()
        row = dict(catalog['opinions'][0], id='new', opinion_id='new',
                   source_url='https://x.com/alpha/status/999', summary='核對後的摘要', review_status='pending_review')
        with TemporaryDirectory() as directory:
            base = Path(directory) / 'catalog.json'; review = Path(directory) / 'review.json'; output = Path(directory) / 'release.json'
            base.write_text(json.dumps(catalog), encoding='utf-8')
            document = {'base_sha256': hashlib.sha256(base.read_bytes()).hexdigest(),
                        'reviewer': 'test-reviewer', 'rights_note': '人工摘要與來源連結', 'opinions': [row]}
            review.write_text(json.dumps(document), encoding='utf-8')
            before = base.read_bytes()
            self.assertEqual(main(['publish', '--catalog', str(base), '--review', str(review), '--output', str(output)]), 2)
            self.assertFalse(output.exists()); self.assertEqual(base.read_bytes(), before)
            document['opinions'][0]['review_status'] = 'confirmed'
            review.write_text(json.dumps(document), encoding='utf-8')
            self.assertEqual(main(['publish', '--catalog', str(base), '--review', str(review), '--output', str(output)]), 0)
            published = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(published['opinions'][-1]['text'], '核對後的摘要')
            self.assertNotIn('raw_text', published['opinions'][-1])
            document['base_sha256'] = '0' * 64
            review.write_text(json.dumps(document), encoding='utf-8')
            self.assertEqual(main(['publish', '--catalog', str(base), '--review', str(review), '--output', str(Path(directory) / 'stale.json')]), 2)


if __name__ == '__main__':
    unittest.main()
