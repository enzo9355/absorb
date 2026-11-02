import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from tests import test_free_research_feeds as feeds_test


HTML = b'''<html><meta property="article:published_time" content="2026-10-13T12:00:00Z">
<a rel="author">Ben Carlson</a><div class="entry-content">I mention $NVDA without recommending a trade.</div></html>'''


class CloudReviewTests(unittest.TestCase):
    def test_busy_source_does_not_starve_other_sources(self):
        from stock_papi.services.research_ai_review import run_review
        from tests.test_research_review import MemoryStore
        catalog = feeds_test.FreeFeedTests().catalog()
        rows = [dict(self.row(), opinion_id='busy-' + str(i)) for i in range(21)]
        rows.append(dict(self.row(), opinion_id='other', creator_id='other'))
        catalog['creators'].append(dict(catalog['creators'][0], id='other'))
        with patch('stock_papi.services.research_ai_review.fetch_original', side_effect=ValueError('unavailable')) as fetch:
            run_review(MemoryStore(), catalog, json.dumps(catalog).encode(), '0',
                       {'opinions': rows, 'ingestion': {}})
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual(fetch.call_args_list[1].args[0]['opinion_id'], 'other')

    def test_invalid_model_json_is_an_operational_error(self):
        from stock_papi.services.research_ai_review import gemini_review
        response = Mock(status_code=200)
        response.json.return_value = {'candidates': [{'finishReason': 'STOP',
            'content': {'parts': [{'text': 'not valid json'}]}}]}
        with patch.dict('os.environ', {'RESEARCH_GEMINI_API_KEY': 'test-only'}), \
             patch('stock_papi.services.research_ai_review.requests.post', return_value=response):
            with self.assertRaises(RuntimeError):
                gemini_review('test')

    def test_transient_model_outage_can_recover_without_approving_failed_response(self):
        from stock_papi.services.research_ai_review import gemini_review
        failed = Mock(status_code=503)
        recovered = Mock(status_code=200)
        recovered.json.return_value = {'candidates': [{'finishReason': 'STOP',
            'content': {'parts': [{'text': '{"publish": false}'}]}}]}
        with patch.dict('os.environ', {'RESEARCH_GEMINI_API_KEY': 'test-only'}), \
             patch('stock_papi.services.research_ai_review.requests.post', side_effect=[failed, recovered]), \
             patch('stock_papi.services.research_ai_review.time.sleep'):
            self.assertEqual(gemini_review('test'), {'publish': False})

    def row(self):
        return feeds_test.FreeFeedTests().parse()['opinions'][0]

    def test_source_requires_original_author_date_and_body(self):
        from stock_papi.services.research_ai_review import parse_original
        result = parse_original(self.row(), {'name': 'Ben Carlson'}, HTML)
        self.assertIn('$NVDA', result['text'])
        for raw in (HTML.replace(b'Ben Carlson', b'Other Author'),
                    HTML.replace(b'2026-10-13', b'2026-10-14'),
                    b'<html>Verify you are human</html>'):
            with self.assertRaises(ValueError):
                parse_original(self.row(), {'name': 'Ben Carlson'}, raw)

    def test_external_redirect_is_not_followed(self):
        from stock_papi.services.research_ai_review import fetch_original
        response = Mock(status_code=302)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('stock_papi.services.research_ai_review.requests.get', return_value=response):
            with self.assertRaises(ValueError):
                fetch_original(self.row(), {'name': 'Ben Carlson'})

    def decision(self):
        return {'publish': True, 'market': 'US', 'symbol': 'NVDA',
                'summary': '作者僅提及輝達，未提出交易建議。',
                'content_type': 'original_opinion', 'stance': 'unclear',
                'recommendation_kind': 'mention',
                'evidence_quote': 'I mention $NVDA without recommending a trade.'}

    def test_approval_requires_real_evidence_known_security_and_second_check(self):
        from stock_papi.services.research_ai_review import review_candidate
        original = {'text': 'I mention $NVDA without recommending a trade.', 'author': 'Ben Carlson'}
        registry = {'US:NVDA': {'name': 'NVIDIA Corporation', 'source_id': 'official-test'}}
        reviewer = Mock(side_effect=[self.decision(), {'supported': True}])
        result, _ = review_candidate(self.row(), original, registry, reviewer)
        self.assertEqual(result['review_status'], 'confirmed')
        self.assertEqual(result['first_seen_at'], self.row()['first_seen_at'])
        self.assertEqual(result['published_at'], self.row()['published_at'])
        self.assertEqual(result['recommendation_kind'], 'mention')
        for decision, securities, verdict in [
            (dict(self.decision(), evidence_quote='fabricated'), registry, True),
            (dict(self.decision(), symbol='FAKE'), registry, True),
            (self.decision(), {}, True),
            (self.decision(), registry, False),
            (dict(self.decision(), publish='true'), registry, True),
        ]:
            reviewer = Mock(side_effect=[decision, {'supported': verdict}])
            with self.assertRaises(ValueError):
                review_candidate(self.row(), original, securities, reviewer)

    def test_run_publishes_once_and_keeps_failed_rows_private(self):
        from stock_papi.services.research_ai_review import run_review
        from tests.test_research_review import MemoryStore
        from stock_papi.repositories.reviewed_opinions import REVIEWED_OBJECT
        catalog = feeds_test.FreeFeedTests().catalog()
        base_raw = json.dumps(catalog).encode()
        draft = {'opinions': [self.row()], 'ingestion': {'ben-carlson': {'count': 1}}}
        original = {'text': 'I mention $NVDA without recommending a trade.', 'author': 'Ben Carlson'}
        registry = {'US:NVDA': {'name': 'NVIDIA', 'source_id': 'official-test'}}
        store = MemoryStore()
        with patch('stock_papi.services.research_ai_review.fetch_original', return_value=original), \
             patch('stock_papi.services.research_ai_review.load_securities', return_value=registry):
            result, receipt = run_review(store, catalog, base_raw, '0', draft,
                reviewer=Mock(side_effect=[self.decision(), {'supported': True}]))
            self.assertEqual(receipt['published'], 1)
            self.assertEqual(result['ingestion']['ben-carlson']['count'], 0)
            published, generation = store.read(REVIEWED_OBJECT)
            self.assertNotIn(b'I mention $NVDA', published)
            self.assertEqual(json.loads(published)['opinions'][0]['reviewer'], 'Gemini AI source review')
            _, repeated = run_review(store, result, published, generation,
                {'opinions': [], 'ingestion': {}}, reviewer=Mock())
            self.assertEqual(repeated['published'], 0)
            self.assertEqual(store.read(REVIEWED_OBJECT), (published, generation))

    def test_model_failure_never_publishes_or_changes_review_date(self):
        from stock_papi.services.research_ai_review import run_review
        from tests.test_research_review import MemoryStore
        from stock_papi.repositories.reviewed_opinions import REVIEWED_OBJECT
        catalog = feeds_test.FreeFeedTests().catalog()
        original = {'text': 'I mention $NVDA without recommending a trade.', 'author': 'Ben Carlson'}
        store = MemoryStore()
        with patch('stock_papi.services.research_ai_review.fetch_original', return_value=original), \
             patch('stock_papi.services.research_ai_review.load_securities', return_value={}):
            result, receipt = run_review(store, catalog, json.dumps(catalog).encode(), '0',
                {'opinions': [self.row()], 'ingestion': {}}, reviewer=Mock(side_effect=RuntimeError('quota')))
            retry = Mock(return_value={'publish': False})
            _, retried = run_review(store, catalog, json.dumps(catalog).encode(), '0',
                {'opinions': [self.row()], 'ingestion': {}}, reviewer=retry)
            self.assertEqual(retried['checked'], 1)
            retry.assert_called_once()
        self.assertEqual(result, catalog)
        self.assertEqual(receipt['published'], 0)
        self.assertEqual(receipt['errors'], 1)
        self.assertEqual(store.read(REVIEWED_OBJECT), (None, '0'))


if __name__ == '__main__':
    unittest.main()
