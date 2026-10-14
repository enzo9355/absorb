"""One daily research refresh; publish public metadata, keep candidates private."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

import requests

from stock_papi.batch import company_events_cli, x_watch_cli
from stock_papi.batch.opinion_review_cli import prepare
from stock_papi.batch.x_opinions_cli import _write_json
from stock_papi.repositories.research_refresh import PUBLIC_OBJECT, SnapshotStore, validate_bundle
from stock_papi.repositories.reviewed_opinions import REVIEWED_OBJECT, validate_catalog
from stock_papi.services.research_catalog import _read_local_json
from stock_papi.services import free_research_feeds as feeds


def _encode(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _archive(store, prefix, raw):
    name = prefix + hashlib.sha256(raw).hexdigest() + '.json'
    previous, _ = store.read(name)
    if previous is None:
        store.write(name, raw, generation='0')
    elif previous != raw:
        raise ValueError('immutable research archive mismatch')


def run_once(store):
    raw, generation = store.read(PUBLIC_OBJECT)
    docs = validate_bundle(json.loads(raw))['documents'] if raw else {name: _read_local_json(name) for name in
            ('events.json', 'events-status.json', 'public-opinions-status.json')}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name, document in docs.items():
            _write_json(root / name, document)
        event_exit = company_events_cli.main(['--output', str(root / 'events.json')])
        private_generations = {}
        for handle in x_watch_cli.SOURCES:
            candidate, private_generations[handle] = store.read(f'research/v1/private/latest/{handle}.json')
            if candidate:
                _write_json(root / 'x-candidates' / (handle + '.json'), json.loads(candidate))
        state = x_watch_cli.run_once(root)
        paths = []
        for handle, health in state['accounts'].items():
            path = root / 'x-candidates' / (handle + '.json')
            if not path.exists():
                continue
            paths.append(path)
            if health.get('status') == 'ok':
                candidate = _encode(json.loads(path.read_text(encoding='utf-8')))
                _archive(store, f'research/v1/private/snapshots/{handle}/', candidate)
                store.write(f'research/v1/private/latest/{handle}.json', candidate, generation=private_generations[handle])
        reviewed_raw, _ = store.read(REVIEWED_OBJECT)
        catalog = validate_catalog(json.loads(reviewed_raw)) if reviewed_raw else _read_local_json('public-opinions.json')
        creator_ids = {row['id'] for row in catalog['creators']}
        for creator_id in feeds.SOURCES:
            if creator_id not in creator_ids:
                continue
            key = 'feed-' + creator_id
            name = f'research/v1/private/latest/{key}.json'
            previous, previous_generation = store.read(name)
            path = root / 'feed-candidates' / (creator_id + '.json')
            old_candidate = json.loads(previous) if previous else None
            if old_candidate:
                _write_json(path, old_candidate)
            health = state['accounts'][key] = {'status': 'error'}
            try:
                candidate = feeds.fetch_candidates(creator_id)
                # First-seen belongs to the original capture, not today's fetch.
                old_rows = {r['opinion_id']: r for r in (old_candidate or {}).get('opinions', [])}
                for row in candidate['opinions']:
                    old = old_rows.get(row['opinion_id'])
                    if old and old.get('text') == row['text']:
                        row['first_seen_at'] = old['first_seen_at']
                _write_json(path, candidate)
                prepare(catalog, '', [path])
            except (ValueError, TypeError, KeyError, requests.RequestException):
                if old_candidate:
                    _write_json(path, old_candidate)
                elif path.exists():
                    path.unlink()
            else:
                encoded_candidate = _encode(candidate)
                _archive(store, f'research/v1/private/snapshots/{key}/', encoded_candidate)
                store.write(name, encoded_candidate, generation=previous_generation)
                health['status'] = 'ok'
            if path.exists():
                paths.append(path)
        review = prepare(catalog, '', paths)
        # No candidate summaries or classifications enter the public bundle.
        old_meta = docs['public-opinions-status.json']
        ingestion = dict(old_meta['ingestion']) if old_meta['catalog_version'] == catalog['catalog_version'] else {}
        ingestion.update(review['ingestion'])
        checked_at = datetime.now(timezone.utc).isoformat()
        for key, health in state['accounts'].items():
            creator_id = key.removeprefix('feed-') if key.startswith('feed-') else x_watch_cli.SOURCES[key]
            if creator_id not in ingestion:
                provider = ('YouTube' if 'channel_id' in feeds.SOURCES[creator_id] else 'RSS') if key.startswith('feed-') else 'FxTwitter'
                ingestion[creator_id] = {'fetched_at': None, 'count': 0, 'has_more': False, 'provider': provider}
            ingestion[creator_id].update(status=health['status'], checked_at=checked_at)
        public = {'schema_version': 1, 'documents': {
            'events.json': json.loads((root / 'events.json').read_text(encoding='utf-8')),
            'events-status.json': json.loads((root / 'events-status.json').read_text(encoding='utf-8')),
            'public-opinions-status.json': {'catalog_version': catalog['catalog_version'], 'ingestion': ingestion}}}
        encoded = _encode(validate_bundle(public))
        _archive(store, 'research/v1/public/snapshots/', encoded)
        published_generation = store.write(PUBLIC_OBJECT, encoded, generation=generation)
        readback, actual_generation = store.read(PUBLIC_OBJECT)
        if readback != encoded or actual_generation != published_generation:
            raise ValueError('research publication readback mismatch')
        failed = event_exit != 0 or any(row.get('status') != 'ok' for row in state['accounts'].values())
        result = {'ok': not failed, 'generation': published_generation,
                  'sha256': hashlib.sha256(encoded).hexdigest(),
                  'announcements': len(public['documents']['events.json']['events']),
                  'candidate_counts': {key: value['count'] for key, value in ingestion.items()},
                  'accounts': {key: value.get('status') for key, value in state['accounts'].items()}}
        return result


def main():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    try:
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
        with AuthorizedSession(credentials) as session:
            result = run_once(SnapshotStore(os.environ['QUANT_SNAPSHOT_BUCKET'], session))
        print(json.dumps(result))
        return 0 if result['ok'] else 2
    except Exception as exc:
        # Do not put authenticated response bodies or candidate text in logs.
        print(json.dumps({'ok': False, 'error': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
