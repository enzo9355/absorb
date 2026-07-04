import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_quant import (
    LAYOUT_DIRS,
    TAIPEI,
    acquire_lock,
    check_free_space,
    ensure_layout,
    load_checkpoint,
    main,
    save_checkpoint,
    validate_data_root,
    window_phase,
)


def at(hour, minute):
    return datetime.datetime(2026, 7, 4, hour, minute, tzinfo=TAIPEI)


class LocalQuantTests(unittest.TestCase):
    def test_data_root_must_be_stock_papi_directory_on_d_drive(self):
        self.assertEqual(
            validate_data_root(Path("D:/StockPapiData")),
            Path("D:/StockPapiData"),
        )
        for invalid in ("C:/StockPapiData", "D:/Other", "StockPapiData"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_data_root(Path(invalid))

    def test_window_phases_enforce_run_drain_checkpoint_and_closed(self):
        self.assertEqual(window_phase(at(5, 29)), "closed")
        self.assertEqual(window_phase(at(5, 30)), "run")
        self.assertEqual(window_phase(at(9, 19)), "run")
        self.assertEqual(window_phase(at(9, 20)), "drain")
        self.assertEqual(window_phase(at(9, 25)), "checkpoint")
        self.assertEqual(window_phase(at(9, 30)), "closed")

    def test_layout_creates_only_expected_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            self.assertEqual(
                {path.name for path in root.iterdir()},
                set(LAYOUT_DIRS),
            )

    def test_free_space_guard_rejects_low_capacity(self):
        with self.assertRaises(RuntimeError):
            check_free_space(Path("D:/StockPapiData"), 100, free_bytes=99 * 1024**3)
        self.assertEqual(
            check_free_space(
                Path("D:/StockPapiData"), 100, free_bytes=101 * 1024**3
            ),
            101 * 1024**3,
        )

    def test_lock_is_single_instance_and_releases_its_own_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            lock = acquire_lock(root, now=at(5, 30))
            with self.assertRaises(RuntimeError):
                acquire_lock(root, now=at(5, 31))
            lock.release()
            replacement = acquire_lock(root, now=at(5, 32))
            replacement.release()

    def test_previous_day_lock_is_archived_before_reacquiring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            lock_path = root / "checkpoints" / "runner.lock"
            lock_path.write_text(
                json.dumps({"token": "old", "started_at": at(5, 30).isoformat()}),
                encoding="utf-8",
            )

            replacement = acquire_lock(
                root,
                now=at(5, 30) + datetime.timedelta(days=1),
            )

            self.assertEqual(len(list(lock_path.parent.glob("runner.lock.stale.*"))), 1)
            replacement.release()

    def test_checkpoint_round_trip_uses_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            save_checkpoint(root, {"stage": "prices", "symbol": "2330"})
            self.assertEqual(
                load_checkpoint(root),
                {"stage": "prices", "symbol": "2330"},
            )
            self.assertFalse(
                (root / "checkpoints" / "progress.json.tmp").exists()
            )

    def test_cli_initializes_layout_and_records_run_ready_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("local_quant.validate_data_root", return_value=root):
                result = main(
                    ["--root", str(root), "--init", "--dry-run"],
                    now=at(5, 30),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            self.assertEqual(load_checkpoint(root)["stage"], "ready")
            self.assertFalse((root / "checkpoints" / "runner.lock").exists())
            status = json.loads(
                (root / "logs" / "runner-status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["phase"], "run")

    def test_cli_outside_window_reports_closed_without_work_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("local_quant.validate_data_root", return_value=root):
                result = main(
                    ["--root", str(root), "--init", "--dry-run"],
                    now=at(22, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            self.assertFalse((root / "checkpoints" / "runner.lock").exists())
            self.assertEqual(load_checkpoint(root), {})

    def test_cli_returns_nonzero_when_free_space_is_below_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("local_quant.validate_data_root", return_value=root):
                result = main(
                    ["--root", str(root), "--init", "--dry-run"],
                    now=at(5, 30),
                    free_bytes=50 * 1024**3,
                )

            self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
