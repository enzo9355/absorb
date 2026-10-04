"""Loopback operator review UI. Candidate access and writes never run on the website."""

import argparse
import copy
import hashlib
import hmac
import json
import secrets
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from flask import Flask, abort, make_response, redirect, render_template, request

from stock_papi.batch.opinion_review_cli import prepare, publish
from stock_papi.batch.x_watch_cli import SOURCES
from stock_papi.batch.x_opinions_cli import _write_json
from stock_papi.repositories.research_refresh import SnapshotStore
from stock_papi.repositories.reviewed_opinions import REVIEWED_OBJECT, publish_review, validate_catalog
from stock_papi.services.research_catalog import _read_local_json


def create_review_app(catalog, candidates, save_review, token, *, port=8767):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / 'templates'))
    app.config['MAX_CONTENT_LENGTH'] = 32_000
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    completed = set()
    review_lock = threading.Lock()
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError('operator token is too short')
    for row in candidates['opinions']:
        source = urlsplit(str(row.get('source_url') or ''))
        if source.scheme != 'https' or source.hostname not in {'x.com', 'twitter.com', 'www.x.com', 'www.twitter.com'} or source.username or source.password:
            raise ValueError('invalid candidate source URL')

    @app.before_request
    def protect():
        if request.host not in allowed_hosts or request.remote_addr not in {'127.0.0.1', '::1'}:
            abort(403)
        origin = request.headers.get('Origin')
        if origin and origin != 'http://' + request.host:
            abort(403)
        if request.method == 'GET' and hmac.compare_digest(request.args.get('token', ''), token):
            response = redirect('/')
            response.set_cookie('research_operator', token, httponly=True, samesite='Strict')
            return response
        if not hmac.compare_digest(request.cookies.get('research_operator', ''), token):
            abort(403)
        if request.method == 'POST' and not hmac.compare_digest(request.form.get('csrf_token', ''), token):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/')
    def index():
        return render_template('research_review.html', rows=candidates['opinions'], completed=completed, token=token,
                               creators={row['id']: row.get('name', row['id']) for row in catalog['creators']})

    @app.post('/review')
    def review():
        with review_lock:
            try:
                index = int(request.form.get('index', '-1'))
                if index < 0 or index >= len(candidates['opinions']):
                    abort(400)
                if index in completed:
                    abort(409)
                decision = request.form.get('decision')
                if decision == 'skip':
                    completed.add(index)
                    return redirect('/')
                if decision != 'confirmed':
                    abort(400)
                row = copy.deepcopy(candidates['opinions'][index])
                for key in ('summary', 'market', 'symbol', 'stance', 'content_type', 'recommendation_kind'):
                    row[key] = request.form.get(key, '').strip()
                row.update(review_status='confirmed', source_status='available',
                           reviewed_at=datetime.now(timezone.utc).isoformat())
                reviewed = dict(candidates, opinions=[row], reviewer=request.form.get('reviewer', '').strip(),
                                rights_note=request.form.get('rights_note', '').strip())
                # Run the existing validator before any callback can write externally.
                publish(catalog, candidates['base_sha256'], reviewed)
                save_review(reviewed)
                completed.add(index)
            except (ValueError, KeyError, TypeError):
                return make_response('核對資料不完整或基線已變更。請確認證券、摘要、立場及審核資訊；必要時重新取得候選。', 400)
            except requests.RequestException:
                return make_response('發布未確認成功。請先重新讀取雲端版本，再決定是否重試。', 503)
        return redirect('/')

    return app


def _session():
    executable = shutil.which('gcloud')
    if not executable:
        raise ValueError('gcloud is required for operator authentication')
    result = subprocess.run([executable, 'auth', 'print-access-token'], check=True, capture_output=True, text=True)
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + result.stdout.strip()
    return session


def private_workspace(workspace):
    root = Path(__file__).resolve().parents[2]
    private = root / '.research-review'
    if private.resolve() != private:
        raise ValueError('private workspace root must not be a link')
    resolved = workspace.resolve()
    if private not in resolved.parents:
        raise ValueError('workspace must be a child of .research-review')
    return resolved


def save_workspace_review(store, workspace, review):
    state = json.loads((workspace / 'state.json').read_text(encoding='utf-8'))
    base_raw = state['base_raw'].encode('utf-8')
    reviewed = dict(review, base_sha256=hashlib.sha256(base_raw).hexdigest())
    receipt = publish_review(store, base_raw, state['generation'], reviewed)
    raw, generation = store.read(REVIEWED_OBJECT)
    if generation != receipt['generation'] or hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('publication changed before local checkpoint; fetch a new workspace')
    record = {'review': reviewed, 'receipt': receipt}
    path = workspace / ('decision-' + secrets.token_hex(8) + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False)
    # One atomic file binds catalog bytes and generation across restarts.
    _write_json(workspace / 'state.json', {'base_raw': raw.decode('utf-8'), 'generation': generation})
    return receipt


def fetch_workspace(store, workspace):
    workspace = private_workspace(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    raw, generation = store.read(REVIEWED_OBJECT)
    if raw:
        catalog = validate_catalog(json.loads(raw))
    else:
        catalog = _read_local_json('public-opinions.json')
        raw = json.dumps(catalog, ensure_ascii=False).encode()
    (workspace / 'base.json').write_bytes(raw)
    paths = []
    for handle in SOURCES:
        candidate, _ = store.read(f'research/v1/private/latest/{handle}.json')
        if candidate:
            path = workspace / (handle + '.json')
            path.write_bytes(candidate)
            paths.append(path)
    if not paths:
        raise ValueError('no private candidates available')
    draft = prepare(catalog, hashlib.sha256(raw).hexdigest(), paths)
    (workspace / 'review.json').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
    _write_json(workspace / 'state.json', {'generation': generation, 'base_raw': raw.decode('utf-8')})
    return len(draft['opinions'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['fetch', 'serve'])
    parser.add_argument('--workspace', type=Path, required=True, help='Private directory outside deployment inputs')
    parser.add_argument('--bucket', default='line-stock-bot-498908-quant-snapshots')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    args.workspace = private_workspace(args.workspace)
    if args.action == 'fetch':
        with _session() as session:
            count = fetch_workspace(SnapshotStore(args.bucket, session), args.workspace)
        print(json.dumps({'ok': True, 'pending': count}))
        return 0
    draft = json.loads((args.workspace / 'review.json').read_text(encoding='utf-8'))
    state = json.loads((args.workspace / 'state.json').read_text(encoding='utf-8'))
    base_raw = state['base_raw'].encode('utf-8')
    catalog = json.loads(base_raw)
    draft['base_sha256'] = hashlib.sha256(base_raw).hexdigest()
    known = {row['opinion_id'] for row in catalog['opinions']}
    draft['opinions'] = [row for row in draft['opinions'] if row['opinion_id'] not in known]

    def save(review):
        with _session() as session:
            store = SnapshotStore(args.bucket, session)
            return save_workspace_review(store, args.workspace, review)

    token = secrets.token_urlsafe(32)
    app = create_review_app(catalog, draft, save, token, port=args.port)
    print(f'Private review: http://127.0.0.1:{args.port}/?token={token}', flush=True)
    # No request logs: the initial local access token must not enter access logs.
    import logging
    logging.getLogger('werkzeug').disabled = True
    app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False, threaded=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
