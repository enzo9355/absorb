import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_research_routes


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.counter = 0

    def read(self, name):
        return self.objects.get(name, (None, '0'))

    def write(self, name, raw, *, generation):
        if self.read(name)[1] != generation:
            raise ValueError('concurrent update')
        self.counter += 1
        self.objects[name] = (raw, str(self.counter))
        return str(self.counter)


def fixture():
    catalog = test_research_routes.ResearchRouteTests()._opinion_catalog()
    row = dict(catalog['opinions'][0], id='new', opinion_id='x:999',
               source_url='https://x.com/alpha/status/999', summary='人工核對摘要',
               text='PRIVATE ORIGINAL', raw_text='PRIVATE RAW', review_status='confirmed')
    raw = json.dumps(catalog).encode()
    review = {'base_sha256': hashlib.sha256(raw).hexdigest(), 'reviewer': 'operator',
              'rights_note': '人工摘要與來源', 'opinions': [row]}
    return catalog, raw, review


class ResearchReviewTests(unittest.TestCase):
    def test_published_object_strips_candidate_text_and_rejects_stale_generation(self):
        from stock_papi.repositories.reviewed_opinions import publish_review, REVIEWED_OBJECT, validate_catalog
        _, raw, review = fixture(); store = MemoryStore()
        receipt = publish_review(store, raw, '0', review)
        public, generation = store.read(REVIEWED_OBJECT)
        self.assertEqual(receipt['generation'], generation)
        self.assertNotIn(b'PRIVATE', public)
        catalog = validate_catalog(json.loads(public))
        self.assertEqual(catalog['opinions'][-1]['text'], '人工核對摘要')
        with self.assertRaises(ValueError):
            publish_review(store, raw, '0', review)
        self.assertEqual(store.read(REVIEWED_OBJECT)[0], public)

    def test_pending_or_private_fields_rejected_and_no_live_write(self):
        from stock_papi.repositories.reviewed_opinions import publish_review, validate_catalog, REVIEWED_OBJECT
        _, raw, review = fixture(); store = MemoryStore()
        review['opinions'][0]['review_status'] = 'pending_review'
        with self.assertRaises(ValueError):
            publish_review(store, raw, '0', review)
        self.assertEqual(store.read(REVIEWED_OBJECT), (None, '0'))
        review['opinions'][0]['review_status'] = 'confirmed'
        publish_review(store, raw, '0', review)
        document = json.loads(store.read(REVIEWED_OBJECT)[0])
        document['opinions'][0]['raw_payload'] = {'private': 'secret'}
        with self.assertRaises(ValueError):
            validate_catalog(document)

    def test_reader_retains_successful_review_on_outage(self):
        from stock_papi.repositories import reviewed_opinions as repo
        from stock_papi.services import research_catalog
        _, raw, review = fixture(); store = MemoryStore()
        repo.publish_review(store, raw, '0', review)
        public = store.read(repo.REVIEWED_OBJECT)[0]
        repo._cache.clear()
        with patch.dict('os.environ', {'ABSORB_RESEARCH_REFRESH_ENABLED': 'true', 'QUANT_SNAPSHOT_BUCKET': 'test-bucket'}), \
                patch.object(repo, 'get_allowed_object', return_value=public), patch.object(repo.time, 'monotonic', return_value=0):
            self.assertEqual(research_catalog._read_json('public-opinions.json')['opinions'][-1]['opinion_id'], 'x:999')
        with patch.dict('os.environ', {'ABSORB_RESEARCH_REFRESH_ENABLED': 'true', 'QUANT_SNAPSHOT_BUCKET': 'test-bucket'}), \
                patch.object(repo, 'get_allowed_object', return_value=None), patch.object(repo.time, 'monotonic', return_value=61):
            self.assertEqual(repo.read_reviewed_catalog()['opinions'][-1]['opinion_id'], 'x:999')
            self.assertEqual(repo.read_reviewed_catalog()['reviewed_refresh_status'], 'source_error')
        repo._cache.clear()

    def test_daily_refresh_uses_current_review_version_without_republishing_it(self):
        from stock_papi.batch import research_refresh_cli as cli
        from stock_papi.repositories.reviewed_opinions import publish_review, REVIEWED_OBJECT
        from tests.test_x_watch import XWatchTests
        _, raw, review = fixture(); store = MemoryStore()
        publish_review(store, raw, '0', review)
        before = store.read(REVIEWED_OBJECT)
        with patch.object(cli.company_events_cli, 'fetch_source', return_value=[]), \
                patch.object(cli.x_watch_cli, 'SOURCES', {'alpha': 'alpha'}), \
                patch.object(cli.x_watch_cli.FxTwitterClient, 'fetch_user_posts', return_value=XWatchTests().result('alpha', [999, 1000])):
            result = cli.run_once(store)
        self.assertTrue(result['ok'])
        status = json.loads(store.read(cli.PUBLIC_OBJECT)[0])['documents']['public-opinions-status.json']
        self.assertEqual(status['catalog_version'], json.loads(before[0])['catalog_version'])
        self.assertEqual(status['ingestion']['alpha']['count'], 1)
        self.assertEqual(store.read(REVIEWED_OBJECT), before)

    def test_workspace_rejects_public_static_and_symlink_destinations(self):
        from pathlib import Path
        from stock_papi.batch.research_review_cli import private_workspace
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            private_workspace(root / 'static' / 'review')
        with self.assertRaises(ValueError):
            private_workspace(root / '.research-review' / '..' / 'data')
        self.assertEqual(private_workspace(root / '.research-review' / 'batch'), root / '.research-review' / 'batch')

    def test_second_publication_and_restart_use_updated_baseline(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from stock_papi.batch.research_review_cli import save_workspace_review
        _, raw, review = fixture(); store = MemoryStore()
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / 'state.json').write_text(json.dumps({'base_raw': raw.decode(), 'generation': '0'}), encoding='utf-8')
            save_workspace_review(store, workspace, review)
            state = json.loads((workspace / 'state.json').read_text(encoding='utf-8'))
            self.assertNotEqual(state['generation'], '0')
            self.assertEqual(json.loads(state['base_raw'])['opinions'][-1]['opinion_id'], 'x:999')
            next_review = copy.deepcopy(review)
            next_review['opinions'][0].update(id='second', opinion_id='x:1000', source_url='https://x.com/alpha/status/1000')
            save_workspace_review(store, workspace, next_review)
            state = json.loads((workspace / 'state.json').read_text(encoding='utf-8'))
            ids = [r['opinion_id'] for r in json.loads(state['base_raw'])['opinions']]
            self.assertIn('x:999', ids)
            self.assertIn('x:1000', ids)

    def test_workbench_requires_token_origin_and_explicit_decision(self):
        from stock_papi.batch.research_review_cli import create_review_app
        catalog, raw, review = fixture(); submitted = []
        candidate = dict(review['opinions'][0], review_status='pending_review', summary='')
        draft = dict(review, opinions=[candidate])
        app = create_review_app(catalog, draft, lambda result: submitted.append(result) or {'ok': True}, 't' * 40, port=8767)
        app.testing = True; client = app.test_client(); base = 'http://127.0.0.1:8767'
        self.assertEqual(client.get('/', base_url=base).status_code, 403)
        self.assertEqual(client.get('/?token=' + 't'*40, base_url=base).status_code, 302)
        html = client.get('/', base_url=base).get_data(as_text=True)
        self.assertIn('PRIVATE ORIGINAL', html)
        data = {'csrf_token': 't'*40, 'index': '0', 'decision': 'confirmed', 'summary': '人工核對摘要',
                'reviewer': 'operator', 'rights_note': '摘要與來源', 'market': candidate['market'],
                'symbol': candidate['symbol'], 'stance': candidate['stance'],
                'content_type': candidate['content_type'], 'recommendation_kind': candidate['recommendation_kind']}
        self.assertEqual(client.post('/review', data=data, base_url=base, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(client.post('/review', data=dict(data, csrf_token='bad'), base_url=base).status_code, 403)
        self.assertEqual(client.post('/review', data=dict(data, decision='pending_review'), base_url=base).status_code, 400)
        self.assertEqual(submitted, [])
        self.assertEqual(client.get('/', base_url='http://evil.example:8767').status_code, 403)
        self.assertEqual(client.post('/review', data=data, base_url=base).status_code, 302)
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]['opinions'][0]['review_status'], 'confirmed')
        self.assertEqual(client.post('/review', data=data, base_url=base).status_code, 409)
