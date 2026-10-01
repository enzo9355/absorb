"""Fetch official TW company announcements; never replace good data on failure."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from stock_papi.batch.x_opinions_cli import _write_json
from stock_papi.services.company_events import MAX_EVENTS, validate_event_catalog
from stock_papi.services.research_catalog import MAX_RESEARCH_BYTES

SOURCES = {
    'TWSE': 'https://openapi.twse.com.tw/v1/opendata/t187ap04_L',
    'TPEx': 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O',
}
TAIPEI = timezone(timedelta(hours=8))


def fetch_source(source):
    with requests.get(SOURCES[source], timeout=(10, 30), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise ValueError(f'{source}: HTTP {response.status_code}')
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 5_000_000:
                raise ValueError(f'{source}: response too large')
    rows = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError(f'{source}: invalid rows')
    return rows


def _published(date, time):
    if not isinstance(date, str) or re.fullmatch(r'\d{7}', date) is None:
        raise ValueError('invalid ROC announcement date')
    if not isinstance(time, str) or re.fullmatch(r'\d{1,6}', time) is None:
        raise ValueError('invalid announcement time')
    clock = time.zfill(6)
    return datetime(int(date[:3]) + 1911, int(date[3:5]), int(date[5:]),
                    int(clock[:2]), int(clock[2:4]), int(clock[4:]), tzinfo=TAIPEI).isoformat()


def build_catalog(source_rows, *, checked_at, previous=None):
    checked = datetime.fromisoformat(checked_at)
    if checked.tzinfo is None:
        raise ValueError('checked_at must include timezone')
    events = {}
    if previous is not None:
        for event in validate_event_catalog(previous)['events']:
            if event['symbol'] and event['status'] != 'source_snapshot':
                events[event['source_id']] = event
    for source, rows in source_rows.items():
        if source not in SOURCES or not isinstance(rows, list):
            raise ValueError('unknown source or invalid rows')
        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError('invalid announcement row')
            row = {key.strip(): value for key, value in raw.items()}
            symbol = row.get('公司代號', row.get('SecuritiesCompanyCode'))
            name = row.get('公司名稱', row.get('CompanyName'))
            if not isinstance(symbol, str) or re.fullmatch(r'\d{4,6}', symbol) is None:
                raise ValueError('invalid company code')
            if not isinstance(name, str) or not name.strip():
                raise ValueError('missing company name')
            published = _published(row.get('發言日期'), row.get('發言時間'))
            if datetime.fromisoformat(published) > checked:
                raise ValueError('announcement is later than acquisition')
            title = row.get('主旨')
            if not isinstance(title, str) or not title.strip():
                raise ValueError('missing announcement title')
            title = ' '.join(title.split())[:300]
            description = row.get('說明', '')
            if not isinstance(description, str):
                raise ValueError('invalid announcement description')
            summary = ' '.join(description.split())[:300] or title
            identity = {key: value for key, value in row.items() if key not in {'Date', '出表日期'}}
            digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            event_id = f'{source.lower()}-{symbol}-{digest[:24]}'
            events[event_id] = {
                'id': event_id, 'source_id': event_id, 'symbol': symbol, 'name': name.strip(),
                'market': 'TW', 'event_type': '重大訊息', 'title': title, 'summary': summary,
                'published_at': published, 'effective_at': None, 'period_start': None, 'period_end': None,
                'source': SOURCES[source], 'source_title': f'{source} 官方重大訊息',
                'source_publisher': '臺灣證券交易所' if source == 'TWSE' else '櫃買中心',
                'source_locator': f'{symbol} / {published} / sha256:{digest}',
                'source_checked_at': checked_at, 'source_status': 'available',
                'status': 'confirmed', 'correction_of': None,
            }
    # ponytail: bounded recent catalog; use an archive reader when full history is needed.
    ordered = sorted(events.values(), key=lambda item: (datetime.fromisoformat(item['published_at']), item['id']), reverse=True)[:MAX_EVENTS]
    document = {'schema_version': 1, 'catalog_id': 'company-events', 'updated_at': checked_at,
                'coverage_note': '台股官方重大訊息近期快照及已累積公告，最多 1000 筆且受檔案大小上限限制；不代表完整歷史。生效日期未由來源明確提供時不推測。',
                'events': ordered}
    while len(json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')) + 1 > MAX_RESEARCH_BYTES:
        document['events'].pop()
    return validate_event_catalog(document)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/research/events.json'))
    args = parser.parse_args(argv)
    checked_at = datetime.now(TAIPEI).isoformat()
    status = {'checked_at': checked_at, 'sources': {}}
    rows = {}
    for source in SOURCES:
        try:
            rows[source] = fetch_source(source)
            status['sources'][source] = {'status': 'available', 'rows': len(rows[source])}
        except (ValueError, requests.RequestException) as exc:
            status['sources'][source] = {'status': 'unavailable', 'error': type(exc).__name__}
    try:
        if len(rows) != len(SOURCES):
            raise ValueError('official source unavailable; previous catalog retained')
        previous = json.loads(args.output.read_text(encoding='utf-8-sig')) if args.output.exists() else None
        catalog = build_catalog(rows, checked_at=checked_at, previous=previous)
        _write_json(args.output, catalog)
        status['status'] = 'available'
        status['published_at'] = checked_at
    except (ValueError, OSError) as exc:
        status['status'] = 'unavailable'
        status['error'] = str(exc)
    try:
        _write_json(args.output.with_name('events-status.json'), status)
    except OSError:
        status['status'] = 'unavailable'
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status['status'] == 'available' else 2


if __name__ == '__main__':
    raise SystemExit(main())
