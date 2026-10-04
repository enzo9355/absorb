"""Reviewed summaries have their own CAS pointer; ingestion cannot overwrite it."""

import copy
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

from stock_papi.repositories.gcs import get_allowed_object
from stock_papi.runtime import get_gcp_access_token
from stock_papi.services.public_opinions import build_catalog

REVIEWED_OBJECT = 'research/v1/public/reviewed-opinions.json'
MAX_BYTES = 1_000_000
_cache = {}
_lock = threading.Lock()
PUBLIC_FIELDS = frozenset('id opinion_id creator_id source_url source_kind source_platform acquisition_method '
    'origin_group_id continuation_of withdraws_id supersedes_id withdrawn_at market symbol company_id security_status '
    'published_at first_seen_at reviewed_at review_status source_status content_type stance recommendation_kind '
    'direction text name summary outcome_status horizon conditions reviewer rights_note'.split())


def _reject_private(value):
    if isinstance(value, dict):
        if {'raw', 'raw_text', 'raw_payload', 'fetch_meta'} & value.keys():
            raise ValueError('private data in reviewed catalog')
        for item in value.values():
            _reject_private(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private(item)


def validate_catalog(document):
    _reject_private(document)
    if not isinstance(document, dict) or document.get('schema_version') != 2:
        raise ValueError('reviewed catalog must use schema v2')
    if not isinstance(document.get('opinions'), list) or not document.get('catalog_version'):
        raise ValueError('invalid reviewed catalog')
    if len(json.dumps(document, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('reviewed catalog exceeds reader limit')
    stamp = datetime.fromisoformat(str(document.get('published_at', '')).replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp > now:
        raise ValueError('invalid publication time')
    for row in document['opinions']:
        if not isinstance(row, dict) or set(row) - PUBLIC_FIELDS:
            raise ValueError('unexpected public opinion field')
    validated = build_catalog(document)
    for row in validated['opinions']:
        if not row.get('is_confirmed'):
            raise ValueError('unreviewed opinion in public object')
        if any(datetime.fromisoformat(row[key].replace('Z', '+00:00')) > stamp
               for key in ('published_at', 'first_seen_at', 'reviewed_at')):
            raise ValueError('opinion was unavailable at publication')
    return document


def publish_review(store, base_raw, generation, review):
    from stock_papi.batch.opinion_review_cli import publish
    current, current_generation = store.read(REVIEWED_OBJECT)
    if current_generation != str(generation) or (current is not None and current != base_raw):
        raise ValueError('review base changed; reload before publishing')
    catalog = json.loads(base_raw)
    result = publish(catalog, hashlib.sha256(base_raw).hexdigest(), review)
    validated = build_catalog(result)
    confirmed = {row['opinion_id'] for row in validated['opinions'] if row.get('is_confirmed')}
    result['opinions'] = [{key: value for key, value in row.items() if key in PUBLIC_FIELDS}
                          for row in result['opinions'] if row.get('opinion_id') in confirmed]
    validate_catalog(result)
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('reviewed catalog exceeds reader limit')
    digest = hashlib.sha256(raw).hexdigest()
    archive = f'research/v1/public/reviewed/{digest}.json'
    old, _ = store.read(archive)
    if old is None:
        store.write(archive, raw, generation='0')
    elif old != raw:
        raise ValueError('immutable reviewed archive mismatch')
    new_generation = store.write(REVIEWED_OBJECT, raw, generation=generation)
    readback, actual_generation = store.read(REVIEWED_OBJECT)
    if readback != raw or actual_generation != new_generation:
        raise ValueError('reviewed publication readback mismatch')
    return {'ok': True, 'generation': new_generation, 'sha256': digest,
            'catalog_version': result['catalog_version'], 'opinions': len(result['opinions'])}


def read_reviewed_catalog():
    bucket = os.getenv('QUANT_SNAPSHOT_BUCKET', '')
    with _lock:
        cached = _cache.get(bucket, {})
        if time.monotonic() >= cached.get('expires', -1):
            raw = get_allowed_object(REVIEWED_OBJECT, MAX_BYTES, 'research/v1/public/',
                bucket=bucket, enabled=True,
                token_provider=lambda: get_gcp_access_token(None, requests), http_get=requests.get)
            try:
                document = validate_catalog(json.loads(raw)) if raw else None
            except (ValueError, TypeError, KeyError):
                document = None
            cached = {'document': document if document is not None else cached.get('document'),
                      'expires': time.monotonic() + 60, 'failed': document is None}
            _cache.clear()
            _cache[bucket] = cached
        document = copy.deepcopy(cached.get('document'))
        if document is not None:
            document['reviewed_refresh_status'] = 'source_error' if cached.get('failed') else 'available'
        return document
