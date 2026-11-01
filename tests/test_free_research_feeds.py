import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


NOW = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)
RSS = b'''<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<title>A Wealth of Common Sense</title><item><title>AI &amp; valuation</title>
<link>https://awealthofcommonsense.com/2026/10/valuation/</link>
<pubDate>Tue, 13 Oct 2026 12:00:00 +0000</pubDate><dc:creator>Ben Carlson</dc:creator>
<description>&lt;p&gt;PRIVATE excerpt&lt;/p&gt;</description></item></channel></rss>'''
ATOM = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<title>Channel</title><yt:channelId>Zn9BeImRq3SDLC8WVrVmUw</yt:channelId>
<entry><yt:channelId>UCZn9BeImRq3SDLC8WVrVmUw</yt:channelId><yt:videoId>abcdefghijk</yt:videoId>
<title>New video</title><published>2026-10-13T12:00:00+00:00</published>
<link rel="alternate" href="https://www.youtube.com/watch?v=abcdefghijk"/></entry></feed>'''


class FreeFeedTests(unittest.TestCase):
    def parse(self, raw=RSS, creator='ben-carlson'):
        from stock_papi.services.free_research_feeds import parse_feed
        return parse_feed(creator, raw, now=NOW)

    def test_rss_is_pending_unmapped_plain_text_and_deduplicated(self):
        doc = self.parse(RSS.replace(b'</channel>', RSS[RSS.index(b'<item>'):RSS.index(b'</item>')+7] + b'</channel>'))
        self.assertEqual(len(doc['opinions']), 1)
        row = doc['opinions'][0]
        self.assertEqual(row['review_status'], 'pending_review')
        self.assertEqual(row['symbol'], '')
        self.assertEqual(row['stance'], 'unclear')
        self.assertEqual(row['text'], 'AI & valuation\nPRIVATE excerpt')
        self.assertEqual(row['published_at'], '2026-10-13T12:00:00+00:00')
        self.assertEqual(row['source_author'], 'Ben Carlson')

    def test_institution_feed_retains_article_author(self):
        raw = RSS.replace(b'A Wealth of Common Sense', b'Alpha Architect').replace(b'awealthofcommonsense.com', b'alphaarchitect.com')
        row = self.parse(raw, 'alpha-architect')['opinions'][0]
        self.assertEqual(row['source_author'], 'Ben Carlson')
        self.assertIn('作者：Ben Carlson', row['text'])

    def test_guest_author_does_not_block_verified_author_entries(self):
        guest = RSS[RSS.index(b'<item>'):RSS.index(b'</item>')+7].replace(
            b'Ben Carlson', b'nelson').replace(b'/valuation/', b'/guest/')
        doc = self.parse(RSS.replace(b'</channel>', guest + b'</channel>'))
        self.assertEqual(len(doc['opinions']), 1)
        self.assertEqual(doc['opinions'][0]['source_author'], 'Ben Carlson')
        self.assertEqual(doc['opinions'][0]['review_status'], 'pending_review')
        self.assertEqual(doc['opinions'][0]['source_url'],
                         'https://awealthofcommonsense.com/2026/10/valuation/')

    def test_wrong_site_author_dates_and_xml_entities_rejected(self):
        for raw in (RSS.replace(b'awealthofcommonsense.com/2026', b'evil.test/2026'),
                    RSS.replace(b'Ben Carlson', b'Impersonator'),
                    RSS.replace(b'A Wealth of Common Sense', b'Other site'),
                    RSS.replace(b' +0000', b''), RSS.replace(b'2026 12:00', b'2099 12:00'),
                    b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///secret">]><rss>&x;</rss>'):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                self.parse(raw)

    def test_empty_source_is_failure_not_a_fresh_empty_snapshot(self):
        with self.assertRaises(ValueError):
            self.parse(b'<rss><channel><title>A Wealth of Common Sense</title></channel></rss>')

    def test_video_channel_binding_and_canonical_url(self):
        row = self.parse(ATOM, 'stock-nobleman')['opinions'][0]
        self.assertEqual(row['source_kind'], 'youtube_video')
        self.assertEqual(row['source_url'], 'https://www.youtube.com/watch?v=abcdefghijk')
        with self.assertRaises(ValueError):
            self.parse(ATOM.replace(b'UCZn9BeImRq3SDLC8WVrVmUw', b'UCwrong'), 'stock-nobleman')

    def test_fetch_rejects_redirect_and_oversize_before_parsing(self):
        from stock_papi.services.free_research_feeds import fetch_candidates
        for status, chunks in [(302, []), (429, []), (200, [b'x' * 2_000_001])]:
            response = Mock(status_code=status)
            response.iter_content.return_value = chunks
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch('stock_papi.services.free_research_feeds.requests.get', return_value=response), self.assertRaises(ValueError):
                fetch_candidates('ben-carlson', now=NOW)

    def catalog(self):
        return {'schema_version': 2, 'catalog_id': 'public-opinions', 'catalog_version': 'test',
                'creators': [{'id': 'ben-carlson', 'name': 'Ben Carlson', 'identity_status': 'verified',
                              'canonical_profile_url': 'https://awealthofcommonsense.com/'}],
                'opinions': [], 'outcomes': [], 'coverage': []}

    def test_prepare_feed_review_binds_creator_and_never_confirms(self):
        from stock_papi.batch.opinion_review_cli import prepare
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.json'
            doc = self.parse()
            path.write_text(json.dumps(doc), encoding='utf-8')
            draft = prepare(self.catalog(), 'digest', [path])
            self.assertEqual(draft['ingestion']['ben-carlson']['provider'], 'RSS')
            self.assertEqual(draft['opinions'][0]['review_status'], 'pending_review')
            self.assertEqual(draft['opinions'][0]['summary'], '')
            doc['opinions'][0]['creator_id'] = 'other'
            path.write_text(json.dumps(doc), encoding='utf-8')
            with self.assertRaises(ValueError):
                prepare(self.catalog(), 'digest', [path])

    def test_review_app_accepts_known_article_but_rejects_unbound_host(self):
        from stock_papi.batch.research_review_cli import create_review_app
        draft = {'opinions': self.parse()['opinions']}
        app = create_review_app(self.catalog(), draft, lambda r: None, 't'*40)
        client = app.test_client()
        self.assertEqual(client.get('/', base_url='http://127.0.0.1:8767').status_code, 403)
        client.get('/?token='+'t'*40, base_url='http://127.0.0.1:8767')
        self.assertIn('PRIVATE excerpt', client.get('/', base_url='http://127.0.0.1:8767').get_data(as_text=True))
        draft['opinions'][0]['source_url'] = 'https://evil.test/article'
        with self.assertRaises(ValueError):
            create_review_app(self.catalog(), draft, lambda r: None, 't'*40)

    def test_refresh_keeps_private_feed_and_last_success_on_outage(self):
        from stock_papi.batch import research_refresh_cli as cli
        from tests.test_research_review import MemoryStore
        from stock_papi.services.free_research_feeds import SOURCES
        store = MemoryStore()
        local_read = cli._read_local_json
        def read(name):
            return self.catalog() if name == 'public-opinions.json' else local_read(name)
        with patch.object(cli, '_read_local_json', side_effect=read), \
             patch.object(cli.x_watch_cli, 'SOURCES', {}), \
             patch.object(cli.feeds, 'SOURCES', {'ben-carlson': SOURCES['ben-carlson']}), \
             patch.object(cli.company_events_cli, 'fetch_source', return_value=[]), \
             patch.object(cli.feeds, 'fetch_candidates', return_value=self.parse()):
            self.assertTrue(cli.run_once(store)['ok'])
        before, generation = store.read('research/v1/private/latest/feed-ben-carlson.json')
        self.assertIn(b'PRIVATE excerpt', before)
        public = store.read(cli.PUBLIC_OBJECT)[0]
        self.assertNotIn(b'PRIVATE excerpt', public)
        with patch.object(cli, '_read_local_json', side_effect=read), \
             patch.object(cli.x_watch_cli, 'SOURCES', {}), \
             patch.object(cli.feeds, 'SOURCES', {'ben-carlson': SOURCES['ben-carlson']}), \
             patch.object(cli.company_events_cli, 'fetch_source', return_value=[]), \
             patch.object(cli.feeds, 'fetch_candidates', side_effect=ValueError('429')):
            self.assertFalse(cli.run_once(store)['ok'])
        self.assertEqual(store.read('research/v1/private/latest/feed-ben-carlson.json'), (before, generation))
        meta = json.loads(store.read(cli.PUBLIC_OBJECT)[0])['documents']['public-opinions-status.json']['ingestion']['ben-carlson']
        self.assertEqual(meta['status'], 'error')
        self.assertEqual(meta['fetched_at'], NOW.isoformat())
        self.assertNotIn(b'PRIVATE excerpt', store.read(cli.PUBLIC_OBJECT)[0])

    def test_article_confirmation_requires_matching_creator_host(self):
        from stock_papi.services.public_opinions import build_catalog
        row = self.parse()['opinions'][0]
        row.update(market='US', symbol='NVDA', reviewed_at=NOW.isoformat(), review_status='confirmed')
        catalog = self.catalog(); catalog['opinions'] = [row]
        self.assertTrue(build_catalog(catalog)['opinions'][0]['is_confirmed'])
        row['source_url'] = 'https://mebfaber.com/2026/10/article/'
        self.assertFalse(build_catalog(catalog)['opinions'][0]['is_confirmed'])

    def test_first_fetch_failure_has_health_without_fake_success_time(self):
        from stock_papi.batch import research_refresh_cli as cli
        from tests.test_research_review import MemoryStore
        from stock_papi.services.free_research_feeds import SOURCES
        store = MemoryStore(); local_read = cli._read_local_json
        with patch.object(cli, '_read_local_json', side_effect=lambda n: self.catalog() if n == 'public-opinions.json' else local_read(n)), \
             patch.object(cli.x_watch_cli, 'SOURCES', {}), \
             patch.object(cli.feeds, 'SOURCES', {'ben-carlson': SOURCES['ben-carlson']}), \
             patch.object(cli.company_events_cli, 'fetch_source', return_value=[]), \
             patch.object(cli.feeds, 'fetch_candidates', side_effect=ValueError('403')):
            self.assertFalse(cli.run_once(store)['ok'])
        meta = json.loads(store.read(cli.PUBLIC_OBJECT)[0])['documents']['public-opinions-status.json']['ingestion']['ben-carlson']
        self.assertIsNone(meta['fetched_at'])
        self.assertEqual(meta['status'], 'error')
        self.assertEqual(meta['count'], 0)
