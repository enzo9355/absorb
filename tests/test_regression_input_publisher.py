"""Failure-injection tests for the immutable regression input publisher."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import reporting.regression_input_publisher as publisher_module
from reporting.regression_input_publisher import (
    _validate_readback,
    publish_regression_input_dataset,
)
from reporting.regression_input_schema import serialize_regression_input_dataset
from tests.regression_fixtures import make_input_document, trading_calendar


class TestRegressionInputPublisher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calendar = trading_calendar()
        self.document = make_input_document(calendar=self.calendar)
        self.payload = serialize_regression_input_dataset(self.document)
        self.object_sha = hashlib.sha256(self.payload).hexdigest()
        self.object_path = self.root / "objects" / "regression-input" / f"{self.object_sha}.json"

    def tearDown(self):
        self.temp.cleanup()

    def publish(self):
        return publish_regression_input_dataset(
            self.document,
            publish_root=self.root,
            trading_calendar=self.calendar,
        )

    def race_after_exists_check(self, content):
        real_exists = Path.exists
        raced = False

        def exists(path):
            nonlocal raced
            if path == self.object_path and not raced:
                raced = True
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                return False
            return real_exists(path)

        return exists

    def test_publish_and_identical_reuse_do_not_rewrite_immutable_object(self):
        pointer = self.publish()
        self.assertEqual(pointer["sha256"], self.object_sha)
        self.assertEqual(self.object_path.read_bytes(), self.payload)

        with mock.patch("reporting.regression_input_publisher._write_atomic") as writer:
            reused = self.publish()
        writer.assert_not_called()
        self.assertEqual(reused, pointer)

    def test_immutable_conflict_fails_without_deleting_existing_object(self):
        self.object_path.parent.mkdir(parents=True)
        self.object_path.write_bytes(b"pre-existing different bytes")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.publish()
        self.assertEqual(self.object_path.read_bytes(), b"pre-existing different bytes")

    def test_same_content_race_is_reused_without_cleanup_ownership(self):
        with mock.patch.object(
            Path,
            "exists",
            autospec=True,
            side_effect=self.race_after_exists_check(self.payload),
        ), mock.patch(
            "reporting.regression_input_publisher._validate_readback",
            side_effect=ValueError("read-back failure"),
        ):
            with self.assertRaisesRegex(ValueError, "read-back"):
                self.publish()
        self.assertEqual(self.object_path.read_bytes(), self.payload)

    def test_different_content_race_fails_closed_without_deleting_competitor(self):
        competitor = b"concurrent writer bytes"
        with mock.patch.object(
            Path,
            "exists",
            autospec=True,
            side_effect=self.race_after_exists_check(competitor),
        ):
            with self.assertRaisesRegex(ValueError, "immutable"):
                self.publish()
        self.assertEqual(self.object_path.read_bytes(), competitor)

    def test_concurrent_writers_use_distinct_temps_and_only_one_owns_object(self):
        writer = getattr(publisher_module, "_write_immutable", None)
        self.assertIsNotNone(writer)
        real_link = os.link
        temporary_paths = []

        def race(source, target):
            temporary_paths.append(Path(source))
            if len(temporary_paths) == 1:
                self.assertTrue(writer(Path(target), self.payload))
            return real_link(source, target)

        with mock.patch.object(publisher_module.os, "link", side_effect=race):
            self.assertFalse(writer(self.object_path, self.payload))

        self.assertEqual(len(temporary_paths), 2)
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertEqual(self.object_path.read_bytes(), self.payload)

    def test_atomic_writes_use_unique_temporary_paths(self):
        temporary_paths = []

        def record(source, _target):
            temporary_paths.append(Path(source))

        with mock.patch.object(publisher_module.os, "replace", side_effect=record):
            publisher_module._write_atomic(self.root / "latest.json", b"one")
            publisher_module._write_atomic(self.root / "latest.json", b"two")

        self.assertEqual(len(temporary_paths), 2)
        self.assertEqual(len(set(temporary_paths)), 2)

    def test_oversized_write_link_and_readback_failures_clean_new_objects(self):
        with mock.patch("reporting.regression_input_publisher.MAX_REGRESSION_INPUT_DATASET_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "size"):
                self.publish()

        with mock.patch("reporting.regression_input_publisher._write_immutable", side_effect=OSError("write")):
            with self.assertRaisesRegex(RuntimeError, "write"):
                self.publish()
        self.assertFalse(self.object_path.exists())

        with mock.patch("reporting.regression_input_publisher.os.link", side_effect=OSError("link")):
            with self.assertRaisesRegex(RuntimeError, "link"):
                self.publish()
        self.assertFalse(self.object_path.exists())
        self.assertFalse(any(self.root.rglob("*.tmp")))

        with mock.patch.object(Path, "read_bytes", side_effect=OSError("read-back")):
            with self.assertRaisesRegex(RuntimeError, "read-back"):
                self.publish()
        self.assertFalse(self.object_path.exists())

    def test_readback_verifier_rejects_size_sha_utf8_json_and_schema_failures(self):
        invalid_cases = (
            (self.payload + b"x", len(self.payload), hashlib.sha256(self.payload + b"x").hexdigest(), "size"),
            (self.payload, len(self.payload), "0" * 64, "SHA256"),
            (b"\xff", 1, hashlib.sha256(b"\xff").hexdigest(), "UTF-8"),
            (b"{", 1, hashlib.sha256(b"{").hexdigest(), "JSON"),
            (b"[]", 2, hashlib.sha256(b"[]").hexdigest(), "schema"),
        )
        for payload, size, sha, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    _validate_readback(
                        payload,
                        expected_size=size,
                        expected_sha256=sha,
                        trading_calendar=self.calendar,
                    )

    def test_readback_verifier_recomputes_content_and_rows_hashes(self):
        for field in ("content", "rows"):
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                if field == "content":
                    document["identity"]["dataset_id"] += "-tampered"
                else:
                    document["rows"][0]["factor_values"]["volume_surge_ratio"] += 0.1
                payload = json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                with self.assertRaisesRegex(ValueError, "content_sha256|canonical_rows_sha256"):
                    _validate_readback(
                        payload,
                        expected_size=len(payload),
                        expected_sha256=hashlib.sha256(payload).hexdigest(),
                        trading_calendar=self.calendar,
                    )

    def test_cleanup_failure_is_reported_and_existing_objects_are_never_deleted(self):
        original_unlink = Path.unlink

        def fail_object_cleanup(path, *args, **kwargs):
            if path.suffix == ".json":
                raise OSError("cleanup")
            return original_unlink(path, *args, **kwargs)

        with mock.patch(
            "reporting.regression_input_publisher._validate_readback",
            side_effect=ValueError("schema mismatch"),
        ), mock.patch.object(Path, "unlink", fail_object_cleanup):
            with self.assertRaisesRegex(RuntimeError, "cleanup"):
                self.publish()


if __name__ == "__main__":
    unittest.main()
