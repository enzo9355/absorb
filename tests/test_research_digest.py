import copy
import datetime as dt
import unittest

from tests import test_research_routes


class DailyDigestTests(unittest.TestCase):
    def digest(self, watchlist, events, catalog=None, **kwargs):
        from stock_papi.services.research_digest import build_daily_digest
        return build_daily_digest(watchlist, events, catalog or {},
            now=dt.datetime.fromisoformat('2026-09-18T01:00:00+08:00'), **kwargs)

    def test_taipei_day_without_effective_date_and_future_exclusion(self):
        base = dict(id='one', market='TW', symbol='2330', status='confirmed',
                    source_status='available', published_at='2026-09-17T16:30:00Z',
                    source_checked_at='2026-09-18T00:45:00+08:00', effective_at=None)
        events = [base, dict(base, id='future', published_at='2026-09-18T02:00:00+08:00'),
                  dict(base, id='other', symbol='1101'), dict(base, id='us', market='US'),
                  dict(base, id='old', published_at='2026-09-17T15:59:59Z')]
        before = copy.deepcopy(events)
        digest = self.digest([{'code': '2330'}], events)
        self.assertEqual(digest['date'], '2026-09-18')
        self.assertEqual([r['id'] for r in digest['announcements']], ['one'])
        self.assertEqual(events, before)
        self.assertEqual(self.digest([], events)['announcements'], [])

    def test_newly_reviewed_old_opinion_pending_and_future_hidden(self):
        catalog = test_research_routes.ResearchRouteTests()._opinion_catalog()
        row = dict(catalog['opinions'][0], reviewed_at='2026-09-18T00:30:00+08:00')
        catalog['opinions'] = [row, dict(row, opinion_id='pending', is_confirmed=False),
                              dict(row, opinion_id='future', reviewed_at='2099-01-01T00:00:00Z')]
        digest = self.digest([{'code': row['symbol'], 'market': row['market']}], [], catalog)
        self.assertEqual(len(digest['opinions']), 1)
        self.assertEqual(digest['opinions'][0]['opinion_id'], row['opinion_id'])

    def test_unavailable_source_is_not_reported_as_success(self):
        digest = self.digest([{'code': '2330'}], [], event_status='source_error')
        self.assertEqual(digest['event_status'], 'source_error')
        self.assertEqual(digest['opinion_status'], 'unavailable')

    def test_persisted_us_watchlist_without_market_keeps_us_identity(self):
        from line_state import normalize_state
        catalog = test_research_routes.ResearchRouteTests()._opinion_catalog()
        row = dict(catalog['opinions'][0], market='US', symbol='NVDA', reviewed_at='2026-09-18T00:30:00+08:00')
        catalog['opinions'] = [row]
        state = normalize_state({'watchlist': [{'code': 'NVDA', 'name': 'NVIDIA', 'market': 'US', 'added_at': 1}]})
        self.assertNotIn('market', state['watchlist'][0])
        digest = self.digest(state['watchlist'], [], catalog)
        self.assertEqual([r['symbol'] for r in digest['opinions']], ['NVDA'])
