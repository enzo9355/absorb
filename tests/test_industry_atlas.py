import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from flask import Flask
from stock_papi.web.routes.research import register_research_routes

from stock_papi.services import industry_relationships as service


TODAY = dt.date(2026, 11, 4)


def catalog():
    value = json.loads((Path(__file__).parents[1] / 'data/research/ai-server.json').read_text(encoding='utf-8'))
    return service.validate_relationship_catalog(value)


class IndustryAtlasTests(unittest.TestCase):
    def test_cross_industry_search_is_casefolded_and_deduplicated(self):
        first = catalog()
        second = copy.deepcopy(first)
        second.update(catalog_id='semiconductors', topic='半導體')
        for query in ('nvidia', 'NVDA', 'ｎｖｄａ'):
            view = service.build_atlas_view([first, second], query=query, as_of=TODAY)
            self.assertEqual(1, len(view['search_results']))
            self.assertEqual('US:NVDA', view['search_results'][0]['key'])
            self.assertEqual(2, len(view['search_results'][0]['industries']))
        self.assertEqual('2382', service.build_atlas_view([first], query='廣達', as_of=TODAY)['search_results'][0]['symbol'])

    def test_market_identity_does_not_classify_korean_ticker_as_taiwan(self):
        view = service.build_atlas_view([catalog()], query='000660', as_of=TODAY)
        self.assertEqual('KR', view['search_results'][0]['market'])
        self.assertEqual([], service.build_atlas_view([catalog()], query='000660', market='TW', as_of=TODAY)['search_results'])

    def test_future_pending_stale_and_unavailable_edges_are_not_current(self):
        original = catalog()['relationships'][0]
        for change in ({'reviewed_at': '2027-01-01'}, {'valid_from': '2027-01-01'}, {'reviewed_at': '2026-01-01'}, {'status': 'pending_review'}, {'source': {**original['source'], 'status': 'unavailable'}}):
            with self.subTest(change=change):
                self.assertFalse(service.relationship_is_current({**original, **change}, as_of=TODAY))
        self.assertTrue(service.relationship_is_current(original, as_of=TODAY))

    def test_history_is_labeled_but_pending_is_not_published(self):
        value = catalog()
        value['relationships'][0]['reviewed_at'] = '2026-01-01'
        value['relationships'][1]['status'] = 'pending_review'
        pending_id = value['relationships'][1]['id']
        view = service.build_atlas_view([value], as_of=TODAY)
        self.assertTrue(view['archived_relationships'])
        self.assertNotIn(pending_id, [e['id'] for e in view['relationships'] + view['archived_relationships']])

    def test_focus_keeps_direct_relationships_and_cross_market_counterpart(self):
        view = service.build_atlas_view([catalog()], focus='2382', market='TW', as_of=TODAY)
        self.assertEqual('TW:2382', view['selected_company']['key'])
        self.assertTrue(view['relationships'])
        self.assertTrue(all('2382' in (e['from']['symbol'], e['to']['symbol']) for e in view['relationships']))
        self.assertTrue(any(e['from']['market'] == 'US' for e in view['relationships']))

    def test_unknown_industry_focus_and_oversized_query_fail_closed(self):
        for kwargs in ({'industry': '../secret'}, {'focus': 'BOGUS'}, {'market': 'INVALID'}, {'query': 'a' * 121}):
            with self.subTest(kwargs=kwargs), self.assertRaises(service.IndustryRelationshipSchemaError):
                service.build_atlas_view([catalog()], as_of=TODAY, **kwargs)

    def test_bad_catalog_is_isolated_and_default_has_eight_industries(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'ai-server.json').write_text('{broken', encoding='utf-8')
            result = service.load_relationship_atlas(folder)
        self.assertEqual(8, len(result))
        self.assertTrue(all(c['unavailable'] for c in result))
        loaded = service.load_relationship_atlas()
        self.assertEqual(8, len(loaded))
        self.assertTrue(all(not c.get('unavailable') for c in loaded))

    def test_malformed_field_types_do_not_hide_healthy_industries(self):
        raw = json.loads((Path(__file__).parents[1] / 'data/research/ai-server.json').read_text(encoding='utf-8'))
        for path in (('stages', 0, 'nodes', 0, 'market'), ('sources', 0, 'status'),
                     ('relationships', 0, 'type'), ('relationships', 0, 'status')):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                bad = copy.deepcopy(raw)
                bad['catalog_id'] = 'semiconductors'
                target = bad
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = []
                Path(folder, 'ai-server.json').write_text(json.dumps(raw), encoding='utf-8')
                Path(folder, 'semiconductors.json').write_text(json.dumps(bad), encoding='utf-8')
                result = service.load_relationship_atlas(folder)
                self.assertFalse(result[0].get('unavailable'))
                self.assertTrue(result[1]['unavailable'])

    def test_market_graph_keeps_counterparts_of_visible_relationships(self):
        for focus in (None, '2382'):
            view = service.build_atlas_view([catalog()], market='TW', focus=focus, as_of=TODAY)
            visible = {n['key'] for stage in view['stages'] for n in stage['nodes']}
            for edge in view['relationships']:
                self.assertTrue({edge['from']['key'], edge['to']['key']} <= visible)

    def test_empty_relationship_catalog_remains_a_searchable_directory(self):
        value = catalog()
        value['relationships'] = []
        value['sources'] = []
        parsed = service.validate_relationship_catalog(value)
        view = service.build_atlas_view([parsed], query='NVDA', as_of=TODAY)
        self.assertTrue(view['search_results'])
        self.assertEqual([], view['relationships'])


class IndustryAtlasRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
        app.add_url_rule('/industries', 'industries_page', lambda: '')
        app.add_url_rule('/stock/<code>', 'stock_page', lambda code: code)
        register_research_routes(app, load_relationships=service.load_all_relationships,
                                 load_atlas=service.load_relationship_atlas,
                                 load_events=lambda: [], load_opinions=lambda: {},
                                 stock_observation=lambda x: {}, get_stock_name=lambda x: x,
                                 allowed_symbols=lambda: {'2330', 'AMD'})
        self.client = app.test_client()

    def test_search_works_without_javascript_and_preserves_industry(self):
        response = self.client.get('/industries/relationships?q=tsmc')
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn('台積電', html)
        self.assertIn('industry=semiconductors', html)
        self.assertIn('name="q"', html)
        self.assertIn('method="get"', html)

    def test_compare_action_is_kept_for_supported_companies(self):
        html = self.client.get('/industries/relationships?industry=semiconductors').get_data(as_text=True)
        self.assertIn('比較這兩家公司', html)
        self.assertIn('symbols=2330,AMD', html)

    def test_legacy_url_uses_the_same_searchable_atlas(self):
        response = self.client.get('/industries/ai-server/relationships?focus=2382')
        self.assertEqual(200, response.status_code)
        self.assertIn('跨產業搜尋公司', response.get_data(as_text=True))
        self.assertIn('廣達', response.get_data(as_text=True))

    def test_api_has_no_pending_leak_and_invalid_query_is_400(self):
        response = self.client.get('/api/research/relationships?industry=healthcare&q=pfe')
        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertEqual('PFE', data['search_results'][0]['symbol'])
        self.assertNotIn('relationships', data['catalog'])
        for query in ('q='+'x'*121, 'industry=../../secret', 'market=XX', 'focus=BOGUS'):
            self.assertEqual(400, self.client.get('/industries/relationships?'+query).status_code)

    def test_empty_search_and_xss_are_safe(self):
        response = self.client.get('/industries/relationships', query_string={'q':'<script>alert(1)</script>'})
        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('尚未收錄符合條件的公司', html)

    def test_sourced_non_ai_industry_and_history_are_rendered(self):
        html = self.client.get('/industries/relationships?industry=consumer-retail&focus=US:PEP').get_data(as_text=True)
        self.assertIn('PepsiCo', html)
        self.assertIn('Walmart', html)
        self.assertIn('pepsico-2025-annual-report.pdf', html)
        html = self.client.get('/industries/relationships?industry=shipping-logistics').get_data(as_text=True)
        self.assertIn('歷史紀錄', html)
        self.assertIn('FedEx', html)


if __name__ == '__main__':
    unittest.main()
