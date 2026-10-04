import copy
import unittest


class EventContextTests(unittest.TestCase):
    def rows(self):
        original = dict(id='old', source_id='old', market='TW', symbol='2330',
                        title='公告本公司取得設備', summary='金額為100萬元',
                        published_at='2026-10-01T10:00:00+08:00', status='confirmed')
        correction = dict(original, id='new', source_id='new',
                          title='更正115/10/1公告本公司取得設備', summary='金額為120萬元',
                          published_at='2026-10-02T10:00:00+08:00')
        return [correction, original]

    def test_explicit_same_company_date_title_links_and_preserves_input(self):
        from stock_papi.services.event_context import annotate_events
        rows = self.rows(); before = copy.deepcopy(rows)
        result = annotate_events(rows)
        self.assertEqual(result[0]['correction_original']['id'], 'old')
        self.assertTrue(result[0]['correction_notice'])
        self.assertIn('summary', result[0]['correction_changes'])
        self.assertEqual(result[0]['category'], '投資與資產')
        self.assertEqual(rows, before)

    def test_ambiguous_or_other_company_target_remains_unlinked(self):
        from stock_papi.services.event_context import annotate_events
        rows = self.rows()
        self.assertIsNone(annotate_events(rows + [dict(rows[1], id='another', source_id='another')])[0]['correction_original'])
        rows[1]['symbol'] = '2317'
        self.assertIsNone(annotate_events(rows)[0]['correction_original'])

    def test_explicit_reference_cannot_link_different_market_or_future(self):
        from stock_papi.services.event_context import annotate_events
        rows = self.rows(); rows[0]['correction_of'] = 'old'; rows[1]['market'] = 'US'
        self.assertIsNone(annotate_events(rows)[0]['correction_original'])
        rows[1]['market'] = 'TW'; rows[1]['published_at'] = '2099-01-01T00:00:00Z'
        self.assertIsNone(annotate_events(rows)[0]['correction_original'])

    def test_page_renders_correction_comparison_and_category_filter(self):
        from flask import Flask
        from pathlib import Path
        from stock_papi.web.routes.research import register_research_routes
        rows = self.rows()
        for row in rows:
            row.update(name='台積電', event_type='重大訊息', source='https://openapi.twse.com.tw/v1/opendata/t187ap04_L')
        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
        register_research_routes(app, load_relationships=lambda: {}, load_events=lambda: rows,
            load_opinions=lambda: {}, stock_observation=lambda _: {}, get_stock_name=lambda code: code,
            allowed_symbols=['2330'])
        response = app.test_client().get('/events?as_of=2026-10-03&category=投資與資產')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('更正前後對照', html)
        self.assertIn('金額為100萬元', html)
        self.assertIn('金額為120萬元', html)
