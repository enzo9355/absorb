import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

from stock_papi.integrations.market_data import us_universe as universe


class IpoTerminationTests(unittest.TestCase):
    def setUp(self):
        self.text = (Path(__file__).parent / 'fixtures/opay-ipo-termination.html').read_text(encoding='utf-8')

    def test_verified_cancellation_excludes_only_matching_issuer_after_effective_date(self):
        evidence = universe.parse_opay_ipo_termination(self.text)
        event = evidence['events'][0]
        self.assertEqual((event['symbol'], event['event'], event['issuer_cik']), ('OPAY', 'listing_cancelled', '2103076'))
        self.assertNotIn('last_trading_date', event)
        for date, cik, expected in [('2026-10-29', 2103076, ['AAPL', 'OPAY']), ('2026-10-30', 2103076, ['AAPL']), ('2026-11-10', 2103076, ['AAPL']), ('2026-11-10', 9999999, ['AAPL', 'OPAY'])]:
            with self.subTest(date=date, cik=cik):
                result = universe.parse_sec_us_universe_with_metadata(
                    {'fields': ['cik', 'name', 'ticker', 'exchange'], 'data': [[cik, 'OPay Limited', 'OPAY', 'NYSE'], [320193, 'Apple Inc.', 'AAPL', 'Nasdaq']]},
                    target_market_date=datetime.date.fromisoformat(date), lifecycle_events=evidence['events'])
                self.assertEqual(result.symbols, expected)

    def test_changed_date_identity_or_cancellation_claim_is_rejected(self):
        for old, new in [('October&nbsp;30, 2026', 'November 30, 2026'), ('NYSE: OPAY', 'NYSE: AAPL'), ('will not commence trading', 'will commence trading')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                universe.parse_opay_ipo_termination(self.text.replace(old, new))

    def test_markup_change_does_not_change_verified_claims(self):
        first = universe.parse_opay_ipo_termination(self.text)
        second = universe.parse_opay_ipo_termination(self.text.replace('BGCOLOR="WHITE"', 'BGCOLOR="white"'))
        self.assertEqual(first['events'][0]['evidence_sha256'], second['events'][0]['evidence_sha256'])
        self.assertNotEqual(first['events'][0]['payload_sha256'], second['events'][0]['payload_sha256'])

    def test_fetcher_adds_cancellation_without_replacing_other_events(self):
        nasdaq = {'events': [{'symbol': 'IPCX', 'effective_date': '2026-08-17'}], 'sources': [{'evidence_sha256': universe.NASDAQ_CORPORATE_ACTION_ALERT_CLAIMS_SHA256}]}
        def fetch(url):
            if url == universe.NASDAQ_CORPORATE_ACTION_ALERT_URL:
                return b'nasdaq fixture'
            self.assertEqual(url, universe.OPAY_IPO_TERMINATION_URL)
            return self.text
        with patch.object(universe, 'parse_nasdaq_corporate_action_alert', return_value=nasdaq):
            result = universe.fetch_us_lifecycle_events(datetime.date(2026, 11, 10), fetch_text=fetch)
        self.assertEqual([r['symbol'] for r in result['events']], ['IPCX', 'OPAY'])


if __name__ == '__main__':
    unittest.main()
