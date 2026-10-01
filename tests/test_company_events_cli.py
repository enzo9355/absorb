import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class CompanyEventsImportTests(unittest.TestCase):
    def test_official_rows_have_stable_identity_and_no_guessed_effective_date(self):
        self.assertIsNotNone(importlib.util.find_spec('stock_papi.batch.company_events_cli'))
        from stock_papi.batch.company_events_cli import build_catalog
        row = {'公司代號': '2330', '公司名稱': '台積電', '發言日期': '1150930',
               '發言時間': '60706', '主旨 ': '公告取得設備', '說明': '1.事實發生日：115/09/29'}
        catalog = build_catalog({'TWSE': [row, row], 'TPEx': []}, checked_at='2026-10-01T01:00:00+08:00')
        self.assertEqual(len(catalog['events']), 1)
        event = catalog['events'][0]
        self.assertEqual(event['published_at'], '2026-09-30T06:07:06+08:00')
        self.assertIsNone(event['effective_at'])
        self.assertEqual(event['symbol'], '2330')
        self.assertIn('https://openapi.twse.com.tw/', event['source'])
        repeated = build_catalog({'TWSE': [row], 'TPEx': []}, checked_at='2026-10-02T01:00:00+08:00')
        self.assertEqual(event['id'], repeated['events'][0]['id'])
        with self.assertRaises(ValueError):
            build_catalog({'TWSE': [dict(row, 發言日期='1150230')], 'TPEx': []}, checked_at='2026-10-01T01:00:00+08:00')

    def test_failure_preserves_catalog_and_success_merges_prior_announcements(self):
        self.assertIsNotNone(importlib.util.find_spec('stock_papi.batch.company_events_cli'))
        from stock_papi.batch import company_events_cli as cli
        row = {'SecuritiesCompanyCode': '5345', 'CompanyName': '馥鴻', '發言日期': '1150930',
               '發言時間': '133116', '主旨': '股東臨時會決議', '說明': '重要決議事項'}
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'events.json'
            prior = cli.build_catalog({'TWSE': [], 'TPEx': [row]}, checked_at='2026-10-01T01:00:00+08:00')
            output.write_text(json.dumps(prior), encoding='utf-8')
            before = output.read_bytes()
            with patch.object(cli, 'fetch_source', side_effect=ValueError('source unavailable')):
                self.assertEqual(cli.main(['--output', str(output)]), 2)
            self.assertEqual(output.read_bytes(), before)
            with patch.object(cli, 'fetch_source', return_value=[]):
                self.assertEqual(cli.main(['--output', str(output)]), 0)
            self.assertEqual(len(json.loads(output.read_text(encoding='utf-8'))['events']), 1)


if __name__ == '__main__':
    unittest.main()
