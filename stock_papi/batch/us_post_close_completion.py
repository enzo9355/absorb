"""Read-only proof that a US post-close run is already published end to end."""

import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from reporting.professional_binding import validate_professional_report_binding
from reporting.web import validate_report_index, validate_report_metadata
from stock_papi.batch.observation_products import validate_observation_dashboard
from stock_papi.repositories.prediction_snapshots import load_prediction_snapshot
from stock_papi.repositories.quant_snapshots import published_quant_manifest


POINTERS = ('quant/v1/latest-US.json', 'reports/v2/index-US.json',
            'reports/v2/latest-US-post_close.json', 'dashboard/v1/latest-US.json',
            'predictions/v1/latest-US.json')


def is_complete(root, target, *, read_remote):
    """Any uncertainty means run/recover normally; this function never publishes."""
    root = Path(root) / 'publish'
    pointers = {}

    def read_equal(name, limit):
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('invalid publication path')
        local = root.joinpath(*path.parts)
        if not 0 < local.stat().st_size <= limit:
            raise ValueError('invalid publication size')
        with local.open('rb') as stream:
            body = stream.read(limit + 1)
        if not 0 < len(body) <= limit or body != read_remote(name, limit):
            raise ValueError('publication differs')
        with local.open('rb') as stream:
            if stream.read(limit + 1) != body:
                raise ValueError('publication changed')
        if name in POINTERS:
            pointers.setdefault(name, body)
        return body

    def bound(prefix, path, digest, limit=5_000_000):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('invalid publication hash')
        body = read_equal(prefix + path, limit)
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError('publication hash mismatch')
        return body

    try:
        manifest = published_quant_manifest('US', target, load_object=read_equal, cache={})
        if not manifest or manifest.get('observation_as_of') != target.isoformat():
            return False
        quant = json.loads(pointers[POINTERS[0]])
        source = ('quant/v1/' + quant['manifest'], quant['manifest_sha256'])
        index = validate_report_index(read_equal(POINTERS[1], 1_000_000),
                                      expected_version=2, expected_market='US')
        latest = json.loads(read_equal(POINTERS[2], 100_000))
        if (latest.get('schema_version') != 2 or latest.get('kind') != 'absorb-report'
                or latest.get('product_mode') != 'observation'
                or latest.get('market') != 'US' or latest.get('report_type') != 'post_close'
                or latest.get('source_market_date') != target.isoformat()):
            return False
        item = next(item for item in index if item['metadata'] == latest['metadata']
                    and item['metadata_sha256'] == latest['metadata_sha256']
                    and item['report_type'] == 'post_close'
                    and item['source_market_date'] == target.isoformat())
        metadata = validate_report_metadata(
            bound('reports/v2/', item['metadata'], item['metadata_sha256'], 2_000_000),
            item, expected_version=2, expected_market='US')
        if any(latest.get(key) != metadata.get(key) for key in
               ('applicable_trading_date', 'published_at', 'product_mode')):
            return False
        canonical = metadata.get('professional_report')
        if canonical:
            report = json.loads(bound('reports/v2/', canonical['object'], canonical['sha256']))
            validate_professional_report_binding(metadata=metadata, pointer=canonical,
                                                 report=report, route_source_date=target)
        dashboard_pointer = json.loads(read_equal(POINTERS[3], 100_000))
        if (dashboard_pointer.get('schema_version') != 2
                or dashboard_pointer.get('kind') != 'absorb-observation-dashboard'
                or dashboard_pointer.get('product_mode') != 'observation'
                or dashboard_pointer.get('observation_as_of') != target.isoformat()
                or dashboard_pointer.get('path') != f"objects/{dashboard_pointer.get('sha256')}.json"):
            return False
        dashboard_body = bound('dashboard/v1/', dashboard_pointer['path'],
                               dashboard_pointer['sha256'])
        dashboard = json.loads(dashboard_body)
        validate_observation_dashboard(dashboard)
        prediction = load_prediction_snapshot('US', target, load_object=read_equal, cache={})
        if not prediction or len(dashboard_body) != dashboard_pointer['size']:
            return False
        for document in (metadata, dashboard_pointer, dashboard, prediction):
            if ((document.get('source_manifest'), document.get('source_manifest_sha256')) != source
                    or document.get('market') != 'US'):
                return False
        if dashboard.get('observation_as_of') != target.isoformat() or prediction['as_of'] != target.isoformat():
            return False
        # Re-read both sides after validating the immutable objects to detect publication races.
        return len(pointers) == len(POINTERS) and all(
            read_equal(name, 1_000_000) == original for name, original in pointers.items())
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--target-market-date', type=datetime.date.fromisoformat, required=True)
    args = parser.parse_args()
    if str(args.root) not in (r'D:\AbsorbData', r'D:\StockPapiData'):
        return 1
    try:
        import requests
        from stock_papi.repositories.gcs import get_allowed_object
        token = subprocess.run([shutil.which('gcloud') or 'gcloud', 'auth', 'print-access-token',
                                '--quiet'], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        with requests.Session() as session:
            def remote(name, limit):
                prefix = '/'.join(name.split('/')[:2]) + '/'
                return get_allowed_object(name, limit, prefix,
                    bucket='line-stock-bot-498908-quant-snapshots', enabled=True,
                    token_provider=lambda: token, http_get=session.get)
            complete = is_complete(args.root, args.target_market_date, read_remote=remote)
        print(json.dumps({'us_post_close_published': complete}))
        return 0 if complete else 1
    except Exception:
        print('{"us_post_close_published":false}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
