import datetime
import hashlib
import json
import unittest
from pathlib import Path
from tests import test_us_market_pipeline as us_fixture
from tests.test_prediction_products import snapshot
from stock_papi.batch.prediction_products import build_research_prediction_product


class CallerTests(unittest.TestCase):
    def test_guard_runs_after_session_check_before_collection(self):
        script = (Path(__file__).parents[1] / 'scripts/run_us_post_close_pipeline.ps1').read_text(encoding='utf-8')
        self.assertLess(script.index('not a US trading session; skipped'),
                        script.index('stock_papi.batch.us_post_close_completion'))
        self.assertLess(script.index('stock_papi.batch.us_post_close_completion'),
                        script.index('us_official_post_close_cli'))
        self.assertIn('verified locally and in GCS', script)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        fixture = us_fixture.USMarketPipelineIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.test_us_observation_dashboard_and_candidate_promotion()
        self.root, self.day = fixture.root, fixture.target_date
        publish = self.root / 'publish'
        pointer = json.loads((publish / 'quant/v1/latest-US.json').read_bytes())
        manifest = json.loads((publish / 'quant/v1' / pointer['manifest']).read_bytes())
        manifest.update(source_manifest='quant/v1/' + pointer['manifest'],
                        source_manifest_sha256=pointer['manifest_sha256'])
        stock = snapshot('AAPL', 'US')
        stock['as_of'] = self.day.isoformat()
        stock['daily'][-1]['Date'] = self.day.isoformat()
        product = build_research_prediction_product(
            'US', manifest, {'AAPL': stock},
            next_session=lambda *_: self.day + datetime.timedelta(days=7),
            generated_at=fixture.now,
        )
        body = json.dumps(product).encode()
        digest = hashlib.sha256(body).hexdigest()
        path = publish / f'predictions/v1/objects/{digest}.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(body)
        pred = {key: product[key] for key in ('schema_version', 'market', 'as_of',
                'source_manifest', 'source_manifest_sha256', 'validation_mode')}
        pred.update(kind='absorb-five-session-predictions-pointer',
                    path=f'objects/{digest}.json', sha256=digest, size=len(body))
        (publish / 'predictions/v1/latest-US.json').write_text(json.dumps(pred))
        self.remote = {p.relative_to(publish).as_posix(): p.read_bytes()
                       for p in publish.rglob('*') if p.is_file()}

    def check(self, reader=None, day=None):
        from stock_papi.batch.us_post_close_completion import is_complete
        return is_complete(self.root, day or self.day,
                           read_remote=reader or (lambda name, limit: self.remote.get(name)))

    def test_complete_publication_skips_even_without_success_receipt(self):
        self.assertTrue(self.check())

    def test_missing_or_tampered_public_objects_do_not_skip(self):
        for name in self.remote:
            with self.subTest(name=name):
                if '/objects/' in name and name.startswith('quant/'):
                    continue
                def read(key, limit):
                    return b'corrupt' if key == name else self.remote.get(key)
                self.assertFalse(self.check(read))

    def test_wrong_date_and_network_failure_do_not_skip(self):
        self.assertFalse(self.check(day=self.day + datetime.timedelta(days=1)))
        def offline(*_):
            raise OSError('offline')
        self.assertFalse(self.check(offline))

    def test_changed_remote_pointer_during_check_does_not_skip(self):
        counts = {}
        def changed(name, limit):
            counts[name] = counts.get(name, 0) + 1
            if name == 'quant/v1/latest-US.json' and counts[name] > 1:
                return b'changed'
            return self.remote.get(name)
        self.assertFalse(self.check(changed))

    def test_unchanged_remote_but_changed_local_prediction_does_not_skip(self):
        path = self.root / 'publish/predictions/v1/latest-US.json'
        pred = json.loads(path.read_bytes())
        pred['as_of'] = '2026-08-18'
        path.write_text(json.dumps(pred))
        self.assertFalse(self.check())

    def test_identical_invalid_documents_do_not_skip(self):
        name = 'quant/v1/latest-US.json'
        pointer = json.loads(self.remote[name])
        pointer['market'] = 'TW'
        body = json.dumps(pointer).encode()
        (self.root / 'publish' / name).write_bytes(body)
        self.remote[name] = body
        self.assertFalse(self.check())

    def test_local_pointer_changes_during_remote_read_do_not_skip(self):
        name = 'predictions/v1/latest-US.json'
        def racing(key, limit):
            if key == name:
                (self.root / 'publish' / name).write_bytes(b'changed')
            return self.remote.get(key)
        self.assertFalse(self.check(racing))

    def test_network_missing_object_does_not_skip(self):
        self.assertFalse(self.check(lambda *_: None))
