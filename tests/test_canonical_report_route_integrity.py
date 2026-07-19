import copy
import datetime
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")
os.environ.setdefault("RENDER_GIT_COMMIT", "b" * 40)

import app as stock_app
from stock_papi.application import load_canonical_object
from reporting.observation_v2 import build_post_close_observation_metadata
from reporting.professional_builder import build_professional_post_close_artifact
from reporting.publisher import publish_report_v2
from tests.test_observation_public_surfaces import observation_dashboard


class Calendar:
    def next_session(self, value):
        self.requested = value
        return datetime.date(2026, 7, 16)


class CanonicalReportRouteIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.metadata = build_post_close_observation_metadata(
            observation_dashboard(), Calendar()
        )
        self.prof_report = build_professional_post_close_artifact(
            self.metadata, code_commit_sha="b" * 40
        )
        publish_report_v2(self.root, self.metadata, professional_report=self.prof_report)
        publish = self.root / "publish" / "reports" / "v2"
        self.objects = {
            f"reports/v2/{path.relative_to(publish).as_posix()}": path.read_bytes()
            for path in publish.rglob("*")
            if path.is_file()
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _get_post_close(self, objects_dict=None, date_str="2026-07-15"):
        objs = objects_dict if objects_dict is not None else self.objects
        with patch.object(
            stock_app,
            "_gcs_get_report_v2_object",
            side_effect=lambda path, _size: objs.get(path) if path.startswith("reports/v2/") else objs.get(f"reports/v2/{path}"),
            create=True,
        ):
            client = stock_app.app.test_client()
            return client.get(f"/reports/{date_str}/post-close")

    def test_load_canonical_object_unit(self):
        with patch.object(stock_app, "_gcs_get_report_v2_object", return_value=b'{"test": 1}'):
            data = load_canonical_object("reports/v2/objects/canonical/123.json", max_bytes=5_000_000)
            self.assertEqual(data, b'{"test": 1}')

        with patch.object(stock_app, "_gcs_get_report_v2_object", return_value=None):
            self.assertIsNone(load_canonical_object("reports/v2/objects/canonical/123.json"))

        with patch.object(stock_app, "_gcs_get_report_v2_object", return_value="not_bytes"):
            self.assertIsNone(load_canonical_object("reports/v2/objects/canonical/123.json"))

        with patch.object(stock_app, "_gcs_get_report_v2_object", return_value=b""):
            self.assertIsNone(load_canonical_object("reports/v2/objects/canonical/123.json"))

        with patch.object(stock_app, "_gcs_get_report_v2_object", return_value=b"a" * 10):
            self.assertIsNone(load_canonical_object("reports/v2/objects/canonical/123.json", max_bytes=5))

    def test_valid_bytes_returns_200(self):
        response = self._get_post_close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_none_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(
            k for k in objs if "objects/canonical/" in k
        )
        objs[canonical_key] = None
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Retry-After"], "60")

    def test_non_bytes_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        objs[canonical_key] = "string_payload"
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_empty_bytes_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        objs[canonical_key] = b""
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_oversized_bytes_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        objs[canonical_key] = b"a" * 5_000_001
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_sha_mismatch_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        doc = json.loads(objs[canonical_key].decode("utf-8"))
        doc["identity"]["generator_version"] = "99.0"
        objs[canonical_key] = json.dumps(doc).encode("utf-8")
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_path_sha_mismatch_returns_503(self):
        objs = dict(self.objects)
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = "objects/canonical/0000000000000000000000000000000000000000000000000000000000000000.json"
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        objs["reports/v2/objects/canonical/0000000000000000000000000000000000000000000000000000000000000000.json"] = objs[canonical_key]
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_invalid_utf8_returns_503(self):
        objs = dict(self.objects)
        bad_utf8 = b"\x80\x81\x82\x83"
        raw_sha = hashlib.sha256(bad_utf8).hexdigest()
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = bad_utf8
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_invalid_json_returns_503(self):
        objs = dict(self.objects)
        bad_json = b"{invalid json format"
        raw_sha = hashlib.sha256(bad_json).hexdigest()
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = bad_json
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_json_array_primitive_returns_503(self):
        objs = dict(self.objects)
        array_bytes = b"[1, 2, 3]"
        raw_sha = hashlib.sha256(array_bytes).hexdigest()
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = array_bytes
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_invalid_canonical_schema_returns_503(self):
        objs = dict(self.objects)
        invalid_schema = json.dumps({"invalid_field": True}).encode("utf-8")
        raw_sha = hashlib.sha256(invalid_schema).hexdigest()
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = invalid_schema
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_route_date_mismatch_returns_503(self):
        objs = dict(self.objects)
        index_key = next(k for k in objs if "index-TW.json" in k)
        idx = json.loads(objs[index_key].decode("utf-8"))
        idx["reports"][0]["source_market_date"] = "2026-07-16"
        objs[index_key] = json.dumps(idx).encode("utf-8")
        response = self._get_post_close(objs, date_str="2026-07-16")
        self.assertEqual(response.status_code, 503)

    def test_applicable_date_mismatch_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        canonical_doc = json.loads(objs[canonical_key].decode("utf-8"))
        canonical_doc["identity"]["applicable_trading_date"] = "2026-07-20"
        from reporting.professional_schema import compute_content_sha256
        new_content_sha = compute_content_sha256(canonical_doc)
        canonical_doc["identity"]["content_sha256"] = new_content_sha
        raw_bytes = json.dumps(canonical_doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()

        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        meta["professional_report"]["content_sha256"] = new_content_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = raw_bytes

        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_manifest_mismatch_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        canonical_doc = json.loads(objs[canonical_key].decode("utf-8"))
        canonical_doc["identity"]["source_manifest"] = "quant/v1/other.json"
        from reporting.professional_schema import compute_content_sha256
        new_content_sha = compute_content_sha256(canonical_doc)
        canonical_doc["identity"]["content_sha256"] = new_content_sha
        raw_bytes = json.dumps(canonical_doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()

        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        meta["professional_report"]["content_sha256"] = new_content_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = raw_bytes

        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_manifest_sha_mismatch_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        canonical_doc = json.loads(objs[canonical_key].decode("utf-8"))
        canonical_doc["identity"]["source_manifest_sha256"] = "f" * 64
        from reporting.professional_schema import compute_content_sha256
        new_content_sha = compute_content_sha256(canonical_doc)
        canonical_doc["identity"]["content_sha256"] = new_content_sha
        raw_bytes = json.dumps(canonical_doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()

        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        meta["professional_report"]["content_sha256"] = new_content_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = raw_bytes

        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_pointer_content_sha_mismatch_returns_503(self):
        objs = dict(self.objects)
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["content_sha256"] = "b" * 64
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_generator_mismatch_returns_503(self):
        objs = dict(self.objects)
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["generator_version"] = "9.9.9"
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_code_sha_mismatch_returns_503(self):
        objs = dict(self.objects)
        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["code_commit_sha"] = "c" * 40
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_report_id_mismatch_returns_503(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        canonical_doc = json.loads(objs[canonical_key].decode("utf-8"))
        canonical_doc["identity"]["report_id"] = "WRONG-REPORT-ID"
        from reporting.professional_schema import compute_content_sha256
        new_content_sha = compute_content_sha256(canonical_doc)
        canonical_doc["identity"]["content_sha256"] = new_content_sha
        raw_bytes = json.dumps(canonical_doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()

        meta_key = next(k for k in objs if "metadata/" in k)
        meta = json.loads(objs[meta_key].decode("utf-8"))
        meta["professional_report"]["object"] = f"objects/canonical/{raw_sha}.json"
        meta["professional_report"]["sha256"] = raw_sha
        meta["professional_report"]["content_sha256"] = new_content_sha
        objs[meta_key] = json.dumps(meta).encode("utf-8")
        objs[f"reports/v2/objects/canonical/{raw_sha}.json"] = raw_bytes

        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)

    def test_route_does_not_call_builder(self):
        with patch("reporting.professional_builder.build_professional_post_close_artifact") as mock_builder:
            response = self._get_post_close()
            self.assertEqual(response.status_code, 200)
            mock_builder.assert_not_called()

    def test_route_does_not_read_k_revision(self):
        original_get = os.environ.get
        k_revision_accessed = []

        def mock_get(key, default=None):
            if key == "K_REVISION":
                k_revision_accessed.append(key)
            return original_get(key, default)

        with patch.object(os.environ, "get", side_effect=mock_get):
            response = self._get_post_close()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(k_revision_accessed, [])

    def test_error_body_does_not_leak_object_path(self):
        objs = dict(self.objects)
        canonical_key = next(k for k in objs if "objects/canonical/" in k)
        objs[canonical_key] = b"invalid payload"
        response = self._get_post_close(objs)
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertNotIn("objects/", body)
        self.assertNotIn("reports/v2/", body)
        self.assertNotIn("objects/canonical", body)
        self.assertNotIn("Exception", body)
        self.assertNotIn("Traceback", body)

    def test_pdf_download_url_is_none(self):
        with patch("stock_papi.web.routes.reports.build_professional_report_view") as mock_view:
            mock_view.return_value = {"title": "Test"}
            response = self._get_post_close()
            mock_view.assert_called_once()
            _, kwargs = mock_view.call_args
            self.assertIn("pdf_download_url", kwargs)
            self.assertIsNone(kwargs["pdf_download_url"])


if __name__ == "__main__":
    unittest.main()
