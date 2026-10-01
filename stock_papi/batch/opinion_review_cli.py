"""Prepare private review batches and publish only explicitly reviewed summaries."""

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from stock_papi.batch.x_opinions_cli import _write_json
from stock_papi.services.public_opinions import build_catalog
from stock_papi.services.research_catalog import MAX_RESEARCH_BYTES


def _read(path, limit=MAX_RESEARCH_BYTES):
    raw = Path(path).read_bytes()
    if len(raw) > limit:
        raise ValueError('input too large')
    document = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(document, dict):
        raise ValueError('input must be a JSON object')
    return document, hashlib.sha256(raw).hexdigest()


def prepare(catalog, digest, paths):
    creators = {item['id']: item for item in build_catalog(catalog)['creators'] if item.get('id')}
    known = {item.get('opinion_id') for item in catalog.get('opinions', [])}
    opinions, ingestion = [], {}
    for path in paths:
        candidate, _ = _read(path, 2_000_000)
        if candidate.get('catalog_id') != 'public-opinions-fxtwitter-candidate':
            raise ValueError('unsupported candidate catalog')
        meta = candidate.get('fetch_meta') or {}
        rows = candidate.get('opinions')
        if not isinstance(rows, list):
            raise ValueError('invalid candidates')
        fetched = datetime.fromisoformat(str(meta.get('fetched_at', '')).replace('Z', '+00:00'))
        if fetched.tzinfo is None:
            raise ValueError('candidate fetch time requires timezone')
        for row in rows:
            creator = creators.get(row.get('creator_id')) if isinstance(row, dict) else None
            if not creator or creator.get('handle') != meta.get('username') or row.get('review_status') != 'pending_review':
                raise ValueError('candidate creator or review state mismatch')
            ingestion[creator['id']] = {'fetched_at': meta['fetched_at'], 'count': len(rows),
                                        'has_more': bool(meta.get('has_more')), 'provider': 'FxTwitter'}
            if not row.get('opinion_id') or row['opinion_id'] in known:
                continue
            known.add(row['opinion_id'])
            opinions.append(dict(row, summary='', reviewed_at='', review_status='pending_review'))
    return {'base_sha256': digest, 'reviewer': '', 'rights_note': '',
            'ingestion': ingestion, 'opinions': opinions}


def publish(catalog, digest, review):
    if review.get('base_sha256') != digest:
        raise ValueError('catalog changed since review preparation')
    if not str(review.get('reviewer') or '').strip() or not str(review.get('rights_note') or '').strip():
        raise ValueError('reviewer and rights_note required')
    rows = review.get('opinions')
    if not isinstance(rows, list) or not rows:
        raise ValueError('reviewed opinions required')
    published = copy.deepcopy(catalog)
    existing = {row.get('opinion_id') for row in published['opinions']}
    additions = []
    for row in rows:
        if not isinstance(row, dict) or row.get('review_status') != 'confirmed':
            raise ValueError('every selected row must be confirmed')
        summary = row.get('summary')
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 1000:
            raise ValueError('reviewed summary required, maximum 1000 characters')
        if row.get('opinion_id') in existing:
            raise ValueError('duplicate opinion_id; use a new revision with supersedes_id')
        existing.add(row.get('opinion_id'))
        clean = {key: value for key, value in row.items()
                 if key not in {'raw_text', 'raw_payload', 'validation_errors', 'is_confirmed', 'classification', 'outcome'}}
        clean.update(text=summary.strip(), summary=summary.strip(), reviewer=review['reviewer'], rights_note=review['rights_note'])
        additions.append(clean)
    published['opinions'].extend(additions)
    now = datetime.now(timezone.utc)
    published['catalog_version'] = 'public-opinions-v2-' + now.strftime('%Y%m%dT%H%M%S%fZ')
    published['published_at'] = now.isoformat()
    published['ingestion'] = review.get('ingestion') or {}
    for coverage in published.get('coverage', []):
        if isinstance(coverage, dict):
            coverage['catalog_version'] = published['catalog_version']
    validated = build_catalog(published)
    for row in validated['opinions'][-len(additions):]:
        if not row.get('is_confirmed'):
            raise ValueError('reviewed row invalid: ' + ','.join(row.get('validation_errors', [])))
        available = [datetime.fromisoformat(row[key].replace('Z', '+00:00'))
                     for key in ('published_at', 'first_seen_at', 'reviewed_at')]
        if max(available) > now:
            raise ValueError('reviewed row is not yet available')
    if len(json.dumps(published, ensure_ascii=False, indent=2).encode()) + 1 > MAX_RESEARCH_BYTES:
        raise ValueError('published catalog exceeds reader size limit')
    return published


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'publish'])
    parser.add_argument('--catalog', type=Path, default=Path('data/research/public-opinions.json'))
    parser.add_argument('--candidates', type=Path, nargs='*', default=[])
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--status-output', type=Path, help='Optional public ingestion metadata only; excludes candidate text')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare' and args.output.resolve() == args.catalog.resolve():
            raise ValueError('review output must not overwrite public catalog')
        if args.output.exists():
            raise ValueError('output must be a new file')
        if args.review and args.output.resolve() == args.review.resolve():
            raise ValueError('output must differ from review input')
        if any(args.output.resolve() == path.resolve() for path in args.candidates):
            raise ValueError('output must differ from candidate input')
        if args.action == 'prepare' and args.status_output:
            protected = [args.catalog, args.output, *args.candidates]
            if any(args.status_output.resolve() == path.resolve() for path in protected):
                raise ValueError('status output must differ from all inputs and review output')
        catalog, digest = _read(args.catalog)
        if args.action == 'prepare':
            if not args.candidates:
                raise ValueError('candidate files required')
            result = prepare(catalog, digest, args.candidates)
        else:
            if not args.review:
                raise ValueError('review file required')
            review, _ = _read(args.review, 5_000_000)
            result = publish(catalog, digest, review)
        # Exclusive creation prevents parallel reviews from replacing one another.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if args.action == 'prepare' and args.status_output:
            _write_json(args.status_output, {'catalog_version': catalog['catalog_version'], 'ingestion': result['ingestion']})
        print(json.dumps({'ok': True, 'action': args.action, 'opinions': len(result['opinions'])}))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
