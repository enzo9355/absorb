import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_quant import (
    LAYOUT_DIRS,
    TAIPEI,
    acquire_lock,
    build_market_insights_document,
    check_free_space,
    cleanup_expired_data,
    ensure_layout,
    _read_insights_metric,
    load_checkpoint,
    main,
    save_checkpoint,
    validate_data_root,
    window_phase,
)


def at(hour, minute):
    return datetime.datetime(2026, 7, 4, hour, minute, tzinfo=TAIPEI)


class LocalQuantTests(unittest.TestCase):
    def test_insights_metric_keeps_core_values_when_optional_field_is_dirty(self):
        document = {
            "name": "台積電", "as_of": "2026-07-06",
            "latest": {
                "AI_P": 68, "Close": 1000, "MA20": 980,
                "RET_1": "N/A", "INST_NET_RATIO": 0.4,
            },
        }
        with patch("local_quant._validated_artifact", return_value=(None, None, document)):
            result = _read_insights_metric(Path("."), "2330")

        self.assertEqual(result["prob"], 68)
        self.assertEqual(result["close"], 1000)
        self.assertIsNone(result["return_1d"])
        self.assertEqual(result["inst_ratio"], 0.4)

    def test_market_insights_reads_theme_symbols_not_full_universe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            pipeline = type("Pipeline", (), {
                "industry_map": {
                    "全市場": ["9999"],
                    "半導體": ["2330", "2303", "2454", "3034", "2379"],
                },
                "get_stock_name": staticmethod(lambda symbol: f"公司{symbol}"),
            })()
            with patch("local_quant._read_insights_metric") as read_metric:
                read_metric.return_value = None
                document = build_market_insights_document(
                    root, pipeline, now=at(6, 0),
                    fetch_json=lambda _url: [], fetch_etf=lambda _etf: [],
                )

            symbols = {call.args[1] for call in read_metric.call_args_list}
            self.assertNotIn("9999", symbols)
            self.assertEqual(len(symbols & {"2330", "2303", "2454", "3034", "2379"}), 5)
            self.assertEqual(len(document["industries"][0]["leaders"]), 5)
            self.assertEqual(document["industries"][0]["coverage"], 0)
            self.assertIn("2330", symbols)

    def test_cli_insights_builds_and_publishes_without_market_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            pipeline = type("Pipeline", (), {"industry_map": {"全市場": ["2330"]}})()
            document = {
                "schema_version": 1, "as_of": "2026-07-04",
                "industries": [], "mops": [], "etfs": [], "supply_chains": [], "sources": [],
            }
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch("local_quant.cleanup_expired_data", return_value={}),
                patch("local_quant.load_stock_pipeline", return_value=pipeline),
                patch("local_quant.build_market_insights_document", return_value=document) as build,
                patch("local_quant.publish_market_insights") as publish,
                patch("local_quant.run_market_batch") as batch,
            ):
                result = main(
                    ["--root", str(root), "--insights"],
                    now=at(6, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            build.assert_called_once_with(root, pipeline, now=at(6, 0))
            publish.assert_called_once_with(root, document, generated_at=at(6, 0))
            batch.assert_not_called()

    def test_cleanup_expired_data_is_allowlisted_and_age_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "StockPapiData"
            ensure_layout(root)
            now = at(6, 0)

            files = {
                "old_tmp": root / "cache" / "tmp" / "nested" / "old.tmp",
                "new_tmp": root / "cache" / "tmp" / "new.tmp",
                "old_log": root / "logs" / "old.log",
                "artifact": root / "artifacts" / "stocks" / "TW" / "2330.json.gz",
                "secret": root / "secrets" / "token.txt",
                "progress": root / "checkpoints" / "progress.json",
                "active_lock": root / "checkpoints" / "runner.lock",
                "stale_lock": root / "checkpoints" / "runner.lock.stale.20260601T000000",
            }
            for path in files.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(path.name, encoding="utf-8")

            old_2_days = (now - datetime.timedelta(days=2)).timestamp()
            old_31_days = (now - datetime.timedelta(days=31)).timestamp()
            old_8_days = (now - datetime.timedelta(days=8)).timestamp()
            os.utime(files["old_tmp"], (old_2_days, old_2_days))
            os.utime(files["old_log"], (old_31_days, old_31_days))
            os.utime(files["stale_lock"], (old_8_days, old_8_days))
            for name in ("artifact", "secret", "progress", "active_lock"):
                os.utime(files[name], (old_31_days, old_31_days))

            outside = base / "outside.txt"
            outside.write_text("keep", encoding="utf-8")
            link = root / "cache" / "tmp" / "outside-link"
            linked = False
            try:
                link.symlink_to(outside)
                linked = True
            except OSError:
                pass

            with patch("local_quant.validate_data_root", return_value=root):
                summary = cleanup_expired_data(root, now=now)

            self.assertFalse(files["old_tmp"].exists())
            self.assertFalse(files["old_log"].exists())
            self.assertFalse(files["stale_lock"].exists())
            self.assertTrue(files["new_tmp"].exists())
            for name in ("artifact", "secret", "progress", "active_lock"):
                self.assertTrue(files[name].exists())
            self.assertTrue(outside.exists())
            if linked:
                self.assertTrue(link.is_symlink())
            self.assertEqual(
                set(summary),
                {"deleted_files", "reclaimed_bytes", "failed", "skipped_reparse_points"},
            )
            self.assertEqual(summary["deleted_files"], 3)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["skipped_reparse_points"], int(linked))
            self.assertFalse((root / "cache" / "tmp" / "nested").exists())

    def test_data_root_must_be_stock_papi_directory_on_d_drive(self):
        self.assertEqual(
            validate_data_root(Path("D:/StockPapiData")),
            Path("D:/StockPapiData"),
        )
        for invalid in ("C:/StockPapiData", "D:/Other", "StockPapiData"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_data_root(Path(invalid))

    def test_window_phases_enforce_run_drain_checkpoint_and_closed(self):
        self.assertEqual(window_phase(at(2, 29)), "closed")
        self.assertEqual(window_phase(at(2, 30)), "run")
        self.assertEqual(window_phase(at(5, 29)), "run")
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

    def test_cli_initialization_does_not_overwrite_market_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            original = {"stage": "market_batch", "market": "TW", "next_index": 200}
            save_checkpoint(root, original)
            with patch("local_quant.validate_data_root", return_value=root):
                result = main(
                    ["--root", str(root), "--init", "--dry-run"],
                    now=at(5, 30),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            self.assertEqual(load_checkpoint(root), original)
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

    def test_cli_run_loads_pipeline_only_inside_work_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            pipeline = type(
                "Pipeline",
                (),
                {"industry_map": {"全市場": ["2330", "2317", "../bad", "2330"]}},
            )()
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch(
                    "local_quant.cleanup_expired_data",
                    return_value={
                        "deleted_files": 1,
                        "reclaimed_bytes": 10,
                        "failed": 0,
                        "skipped_reparse_points": 0,
                    },
                ) as cleanup,
                patch("local_quant.load_stock_pipeline", return_value=pipeline) as loader,
                patch("local_quant.run_market_batch", return_value={"attempted": 2}) as batch,
            ):
                result = main(
                    [
                        "--root", str(root), "--run", "--market", "TW",
                        "--limit", "2", "--delay", "0",
                    ],
                    now=at(6, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            cleanup.assert_called_once_with(root, now=at(6, 0))
            loader.assert_called_once_with(root)
            self.assertEqual(batch.call_args.args[2], ["2317", "2330"])
            status = json.loads(
                (root / "logs" / "runner-status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["cleanup"]["deleted_files"], 1)

            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch("local_quant.cleanup_expired_data") as closed_cleanup,
                patch("local_quant.load_stock_pipeline") as closed_loader,
            ):
                result = main(
                    ["--root", str(root), "--run", "--market", "TW"],
                    now=at(22, 0),
                    free_bytes=200 * 1024**3,
                )
            self.assertEqual(result, 0)
            closed_cleanup.assert_not_called()
            closed_loader.assert_not_called()

    def test_cli_all_runs_taiwan_then_us_with_independent_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            pipeline = type("Pipeline", (), {"industry_map": {"全市場": ["2330"]}})()
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch(
                    "local_quant.cleanup_expired_data",
                    return_value={
                        "deleted_files": 0,
                        "reclaimed_bytes": 0,
                        "failed": 0,
                        "skipped_reparse_points": 0,
                    },
                ),
                patch("local_quant.load_stock_pipeline", return_value=pipeline) as loader,
                patch("local_quant.get_us_symbols", return_value=["AAPL"]) as us_symbols,
                patch(
                    "local_quant.run_market_batch",
                    side_effect=[{"attempted": 1}, {"attempted": 1}],
                ) as batch,
            ):
                result = main(
                    [
                        "--root", str(root), "--run", "--market", "ALL",
                        "--limit", "5000", "--delay", "0",
                    ],
                    now=at(6, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            loader.assert_called_once_with(root)
            us_symbols.assert_called_once_with(root, now=at(6, 0))
            self.assertEqual(
                [(call.args[1], call.args[2]) for call in batch.call_args_list],
                [("TW", ["2330"]), ("US", ["AAPL"])],
            )

    def test_cli_publishes_only_after_market_batch_is_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            save_checkpoint(
                root,
                {
                    "stage": "market_batch",
                    "market": "TW",
                    "next_index": 1,
                    "failed": [],
                    "cycle_completed_on": "2026-07-04",
                },
            )
            pipeline = type("Pipeline", (), {"industry_map": {"全市場": ["2330"]}})()
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch(
                    "local_quant.cleanup_expired_data",
                    return_value={
                        "deleted_files": 0,
                        "reclaimed_bytes": 0,
                        "failed": 0,
                        "skipped_reparse_points": 0,
                    },
                ),
                patch("local_quant.load_stock_pipeline", return_value=pipeline),
                patch(
                    "local_quant.run_market_batch",
                    return_value={
                        "attempted": 1,
                        "completed": 1,
                        "failed": [],
                        "next_index": 1,
                    },
                ),
                patch("local_quant.publish_market_snapshot") as publish,
            ):
                result = main(
                    ["--root", str(root), "--run", "--market", "TW", "--delay", "0"],
                    now=at(6, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            publish.assert_called_once_with(
                root, "TW", ["2330"], generated_at=at(6, 0), failed_symbols=[]
            )
            checkpoint = load_checkpoint(root)
            self.assertEqual(checkpoint["published_cycle_on"], "2026-07-04")

    def test_cli_publishes_partial_market_below_failure_threshold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            symbols = [f"{number:04d}" for number in range(100)]
            pipeline = type(
                "Pipeline", (), {"industry_map": {"全市場": symbols}}
            )()
            failed = [{"symbol": "0099", "error": "ValueError"}]
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch("local_quant.cleanup_expired_data", return_value={}),
                patch("local_quant.load_stock_pipeline", return_value=pipeline),
                patch(
                    "local_quant.run_market_batch",
                    return_value={"failed": failed, "next_index": 100},
                ),
                patch("local_quant.publish_market_snapshot") as publish,
            ):
                publish.return_value = root / "publish" / "quant" / "v1" / "latest-TW.json"
                result = main(
                    ["--root", str(root), "--run", "--market", "TW", "--delay", "0"],
                    now=at(6, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            publish.assert_called_once_with(
                root,
                "TW",
                symbols,
                generated_at=at(6, 0),
                failed_symbols=["0099"],
            )

    def test_cli_refuses_us_market_before_0530(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_layout(root)
            with (
                patch("local_quant.validate_data_root", return_value=root),
                patch("local_quant.load_stock_pipeline") as loader,
                patch("local_quant.get_us_symbols") as us_symbols,
            ):
                result = main(
                    ["--root", str(root), "--run", "--market", "US"],
                    now=at(3, 0),
                    free_bytes=200 * 1024**3,
                )

            self.assertEqual(result, 0)
            loader.assert_not_called()
            us_symbols.assert_not_called()
            status = json.loads(
                (root / "logs" / "runner-status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["phase"], "closed")


if __name__ == "__main__":
    unittest.main()
