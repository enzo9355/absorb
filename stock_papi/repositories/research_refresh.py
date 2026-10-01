"""Bounded research snapshots; the website reads only the public prefix."""

import copy
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from stock_papi.repositories.gcs import get_allowed_object
from stock_papi.runtime import get_gcp_access_token
from stock_papi.services.company_events import validate_event_catalog


PUBLIC_OBJECT = 'research/v1/public/latest.json'
MAX_BYTES = 2_000_000
DOCUMENTS = {'events.json', 'events-status.json', 'public-opinions-status.json'}
_cache = {}
_lock = threading.Lock()


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {'schema_version', 'documents'} or bundle['schema_version'] != 1:
        raise ValueError('invalid research bundle')
    docs = bundle['documents']
    if not isinstance(docs, dict) or set(docs) != DOCUMENTS:
        raise ValueError('unexpected research document')
    validate_event_catalog(docs['events.json'])
    status = docs['events-status.json']
    if not isinstance(status, dict) or status.get('status') not in {'available', 'unavailable'}:
        raise ValueError('invalid event status')
    for stamp in (status.get('checked_at'),):
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('invalid refresh timestamp')
    opinion = docs['public-opinions-status.json']
    if not isinstance(opinion, dict) or set(opinion) != {'catalog_version', 'ingestion'} or not isinstance(opinion['catalog_version'], str):
        raise ValueError('invalid public opinion metadata')
    if not isinstance(opinion['ingestion'], dict) or len(opinion['ingestion']) > 100:
        raise ValueError('invalid ingestion metadata')
    for creator, meta in opinion['ingestion'].items():
        if (not isinstance(creator, str) or not isinstance(meta, dict)
                or set(meta) != {'fetched_at', 'count', 'has_more', 'provider'}
                or meta['provider'] != 'FxTwitter' or type(meta['has_more']) is not bool
                or type(meta['count']) is not int or not 0 <= meta['count'] <= 10000
                or not isinstance(meta['fetched_at'], str)
                or datetime.fromisoformat(meta['fetched_at'].replace('Z', '+00:00')).tzinfo is None):
            raise ValueError('invalid public creator metadata')
    return bundle


def read_public_documents():
    bucket = os.getenv('QUANT_SNAPSHOT_BUCKET', '')
    with _lock:
        cached = _cache.get(bucket, {})
        if time.monotonic() >= cached.get('expires', -1):
            raw = get_allowed_object(PUBLIC_OBJECT, MAX_BYTES, 'research/v1/public/',
                                     bucket=bucket, enabled=True,
                                     token_provider=lambda: get_gcp_access_token(None, requests), http_get=requests.get)
            try:
                documents = validate_bundle(json.loads(raw))['documents'] if raw else None
            except (ValueError, TypeError, KeyError):
                documents = None
            failed = documents is None
            cached = {'documents': documents or cached.get('documents', {}),
                      'expires': time.monotonic() + 60, 'failed': failed}
            # ponytail: one configured bucket per process; no general cache needed.
            _cache.clear()
            _cache[bucket] = cached
        documents = copy.deepcopy(cached['documents'])
        if cached['failed']:
            documents['events-status.json'] = {'status': 'unavailable', 'checked_at': datetime.now(timezone.utc).isoformat()}
        return documents


class SnapshotStore:
    def __init__(self, bucket, session):
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', bucket):
            raise ValueError('invalid research bucket')
        self.bucket, self.session = bucket, session

    def _url(self, name):
        if not re.fullmatch(r'research/v1/(public|private)/[a-zA-Z0-9_./-]+\.json', name) or '..' in name:
            raise ValueError('object is outside research prefix')
        return f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{quote(name, safe="")}'

    def read(self, name):
        url = self._url(name)
        with self.session.get(url, timeout=15) as metadata:
            if metadata.status_code == 404:
                return None, '0'
            metadata.raise_for_status()
            meta = metadata.json()
            if int(meta['size']) > MAX_BYTES:
                raise ValueError('research object exceeds size limit')
            generation = str(meta['generation'])
        with self.session.get(url, params={'alt': 'media', 'generation': generation}, stream=True, timeout=15) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError('research object exceeds size limit')
        return bytes(raw), generation

    def write(self, name, raw, *, generation):
        self._url(name)
        if len(raw) > MAX_BYTES or not str(generation).isdigit():
            raise ValueError('invalid research write')
        response = self.session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o',
                                     params={'uploadType': 'media', 'name': name, 'ifGenerationMatch': str(generation)},
                                     data=raw, headers={'Content-Type': 'application/json'}, timeout=30)
        try:
            if response.status_code == 412:
                raise ValueError('research snapshot changed concurrently; refusing overwrite')
            response.raise_for_status()
            return str(response.json()['generation'])
        finally:
            response.close()
