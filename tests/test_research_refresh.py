import copy
import json
import unittest
from unittest.mock import patch

from stock_papi.services import research_catalog


class ResearchRefreshTests(unittest.TestCase):
    def test_refresh_publishes_metadata_only_and_preserves_rows_on_source_failure(self):
        from stock_papi.batch import research_refresh_cli as cli
        from stock_papi.services.x_api import XApiError
        from tests.test_x_watch import XWatchTests

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

        store = MemoryStore()
        sources = cli.x_watch_cli.SOURCES
        def posts(handle, **kwargs):
            return XWatchTests().result(handle, [list(sources).index(handle) + 1])
        row = {'公司代號': '2330', '公司名稱': '台積電', '發言日期': '1151001',
               '發言時間': '050000', '主旨': '每日新公告', '說明': '官方說明'}
        with patch.object(cli.company_events_cli, 'fetch_source', return_value=[row]), \
                patch.object(cli.x_watch_cli.FxTwitterClient, 'fetch_user_posts', side_effect=posts):
            self.assertTrue(cli.run_once(store)['ok'])
        public, _ = store.read(cli.PUBLIC_OBJECT)
        self.assertIn('每日新公告', public.decode())
        self.assertNotIn('post 1', public.decode())
        self.assertNotIn('pending_review', public.decode())
        private_name = 'research/v1/private/latest/unusual_whales.json'
        private, _ = store.read(private_name)
        self.assertIn('post 1', private.decode())
        before = json.loads(public)['documents']['events.json']
        with patch.object(cli.company_events_cli, 'fetch_source', side_effect=ValueError('outage')), \
                patch.object(cli.x_watch_cli.FxTwitterClient, 'fetch_user_posts', side_effect=XApiError('outage')):
            self.assertFalse(cli.run_once(store)['ok'])
        after = json.loads(store.read(cli.PUBLIC_OBJECT)[0])['documents']
        self.assertEqual(after['events.json'], before)
        self.assertEqual(after['events-status.json']['status'], 'unavailable')
        self.assertEqual(store.read(private_name)[0], private)
        with patch.object(cli.company_events_cli, 'fetch_source', return_value=[row]), \
                patch.object(cli.x_watch_cli.FxTwitterClient, 'fetch_user_posts', side_effect=posts):
            self.assertTrue(cli.run_once(store)['ok'])
        self.assertEqual(json.loads(store.read(private_name)[0])['opinions'][0]['first_seen_at'],
                         json.loads(private)['opinions'][0]['first_seen_at'])

    def bundle(self):
        from tests.test_company_events import _catalog, _event
        return {'schema_version': 1, 'documents': {
            'events.json': _catalog([_event()]),
            'events-status.json': {'status': 'available', 'checked_at': '2026-10-01T12:00:00Z'},
            'public-opinions-status.json': {'catalog_version': 'test', 'ingestion': {
                'alpha': {'fetched_at': '2026-10-01T12:00:00Z', 'count': 7, 'has_more': True,
                          'provider': 'FxTwitter'}}}}}

    def test_public_bundle_rejects_private_documents_and_invalid_events(self):
        from stock_papi.repositories.research_refresh import validate_bundle
        bundle = self.bundle()
        self.assertEqual(validate_bundle(bundle), bundle)
        private = copy.deepcopy(bundle)
        private['documents']['x-candidates/alpha.json'] = {'text': 'PRIVATE'}
        with self.assertRaises(ValueError):
            validate_bundle(private)
        invalid = copy.deepcopy(bundle)
        invalid['documents']['events.json']['events'][0]['source'] = 'https://evil.example/'
        with self.assertRaises(ValueError):
            validate_bundle(invalid)
        invalid = copy.deepcopy(bundle)
        invalid['documents']['public-opinions-status.json']['ingestion']['alpha']['raw_text'] = 'PRIVATE'
        with self.assertRaises(ValueError):
            validate_bundle(invalid)

    def test_reader_uses_cloud_snapshot_and_retains_good_data_on_outage(self):
        from stock_papi.repositories import research_refresh as refresh
        refresh._cache.clear()
        bundle = self.bundle()
        with patch.dict('os.environ', {'ABSORB_RESEARCH_REFRESH_ENABLED': 'true',
                                       'QUANT_SNAPSHOT_BUCKET': 'safe-bucket'}), \
                patch.object(refresh, 'get_allowed_object', return_value=json.dumps(bundle).encode()), \
                patch.object(refresh.time, 'monotonic', return_value=0):
            self.assertEqual(research_catalog._read_json('events.json'), bundle['documents']['events.json'])
        with patch.dict('os.environ', {'ABSORB_RESEARCH_REFRESH_ENABLED': 'true',
                                       'QUANT_SNAPSHOT_BUCKET': 'safe-bucket'}), \
                patch.object(refresh, 'get_allowed_object', return_value=None), \
                patch.object(refresh.time, 'monotonic', return_value=61):
            self.assertEqual(research_catalog._read_json('events.json'), bundle['documents']['events.json'])
            self.assertEqual(research_catalog._read_json('events-status.json')['status'], 'unavailable')
        refresh._cache.clear()

    def test_storage_conflict_cannot_overwrite_a_newer_snapshot(self):
        from stock_papi.repositories.research_refresh import SnapshotStore
        from unittest.mock import Mock
        response = Mock(status_code=412)
        store = SnapshotStore('safe-bucket', Mock())
        store.session.post.return_value = response
        with self.assertRaises(ValueError):
            store.write('research/v1/public/latest.json', b'{}', generation='123')
        self.assertEqual(store.session.post.call_args.kwargs['params']['ifGenerationMatch'], '123')
        with self.assertRaises(ValueError):
            store.write('predictions/v1/latest-TW.json', b'{}', generation='123')


if __name__ == '__main__':
    unittest.main()
