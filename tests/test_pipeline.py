import json
import logging
import os
import tempfile
import unittest
from collections.abc import Callable, Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO
from unittest import mock

from helpers import BELOW_MINIMUM_ROW, INVALID_ROW, VALID_ROWS, base_config, write_config, write_csv

from reliable_importer.config import AppConfig, load_config
from reliable_importer.exceptions import DataExportError, RecordValidationError
from reliable_importer.exporters import (
    AtomicWriter,
    DecimalJSONEncoder,
    JsonExporter,
    JsonLinesExporter,
    replace_file,
)
from reliable_importer.main import describe, main
from reliable_importer.models import ImportStatistics, StudentRecord
from reliable_importer.services import run_import_export
from reliable_importer.utils import logged_operation, retry


class FailingExporter:
    def write(self, records: Iterable[StudentRecord], file: TextIO) -> int:
        for index, record in enumerate(records):
            if index == 1:
                raise OSError("диск переповнено (імітація)")
            JsonExporter().write([record], file)
        return 0


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rows = [VALID_ROWS[0], INVALID_ROW, VALID_ROWS[1], BELOW_MINIMUM_ROW, VALID_ROWS[2]]
        write_csv(self.root / "data" / "students.csv", self.rows)
        self.output = self.root / "output" / "students.json"

    def tearDown(self) -> None:
        logging.shutdown()
        logging.getLogger().handlers.clear()
        self._tmp.cleanup()

    def config(self, **processing: Any) -> AppConfig:
        raw = base_config()
        raw["processing"].update(processing)
        return load_config(write_config(self.root, raw), environ={})

    def test_tolerant_skips_filters_and_reports(self) -> None:
        stats = run_import_export(self.config())
        self.assertEqual(
            (stats.total, stats.valid, stats.invalid, stats.below_minimum, stats.exported),
            (5, 4, 1, 1, 3),
        )
        exported = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual([item["student_id"] for item in exported], [1, 3, 9])
        self.assertEqual(exported[0]["average_grade"], 91.5)
        errors = (self.root / "output" / "errors.csv").read_text(encoding="utf-8")
        self.assertIn("3,5,average_grade,grade_out_of_range", errors)
        summary = json.loads((self.root / "output" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["invalid"], 1)
        self.assertEqual(summary["mode"], "tolerant")
        self.assertEqual(summary["exported_by_group"], {"PI-21": 1, "PI-22": 1, "PI-23": 1})
        self.assertEqual(summary["errors_by_code"], {"grade_out_of_range": 1})

    def test_minimum_grade_controls_export(self) -> None:
        stats = run_import_export(self.config(minimum_grade=93))
        self.assertEqual((stats.valid, stats.below_minimum, stats.exported), (4, 2, 2))
        stats = run_import_export(self.config(minimum_grade=93.1))
        self.assertEqual((stats.below_minimum, stats.exported), (2, 2))
        stats = run_import_export(self.config(minimum_grade=93.2))
        self.assertEqual((stats.below_minimum, stats.exported), (3, 1))
        stats = run_import_export(self.config(minimum_grade=0))
        self.assertEqual((stats.below_minimum, stats.exported), (0, 4))
        stats = run_import_export(self.config(minimum_grade=100))
        self.assertEqual((stats.below_minimum, stats.exported), (4, 0))
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), [])

    def test_strict_aborts_without_output(self) -> None:
        stats = ImportStatistics()
        with self.assertRaises(RecordValidationError):
            run_import_export(self.config(skip_invalid=False), stats=stats)
        self.assertEqual((stats.total, stats.invalid), (2, 1))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob("*.tmp")), [])

    def test_strict_abort_releases_input_file(self) -> None:
        with self.assertRaises(RecordValidationError):
            run_import_export(self.config(skip_invalid=False))
        (self.root / "data" / "students.csv").unlink()

    def test_failed_export_keeps_previous_output(self) -> None:
        config = self.config()
        run_import_export(config)
        before = self.output.read_bytes()
        with self.assertRaises(DataExportError) as caught:
            run_import_export(config, exporter=FailingExporter())
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(list(self.output.parent.glob("*.tmp")), [])

    def test_failed_run_reports_nothing_as_exported(self) -> None:
        stats = ImportStatistics()
        with self.assertRaises(DataExportError):
            run_import_export(self.config(), exporter=FailingExporter(), stats=stats)
        self.assertEqual((stats.exported, dict(stats.groups)), (0, {}))
        stats = ImportStatistics()
        with self.assertRaises(RecordValidationError):
            run_import_export(self.config(skip_invalid=False), stats=stats)
        self.assertEqual((stats.exported, dict(stats.groups)), (0, {}))

    def test_backup_of_previous_output(self) -> None:
        config = self.config()
        run_import_export(config)
        run_import_export(config)
        self.assertTrue(self.output.with_name("students.json.bak").exists())

    def test_jsonl_output_and_missing_optional_paths(self) -> None:
        raw = base_config()
        raw["output"].update(format="jsonl", path="output/students.jsonl")
        raw["output"].pop("errors_path")
        raw["output"].pop("summary_path")
        stats = run_import_export(load_config(write_config(self.root, raw), environ={}))
        lines = (self.root / "output" / "students.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual((stats.exported, len(lines)), (3, 3))
        self.assertEqual(json.loads(lines[0])["last_name"], "Коваль")
        self.assertFalse((self.root / "output" / "errors.csv").exists())

    def test_progress_is_logged(self) -> None:
        with self.assertLogs("reliable_importer.services", level="INFO") as logs:
            run_import_export(self.config(progress_every=2))
        self.assertEqual(sum("Прогрес" in line for line in logs.output), 2)

    def test_main_exit_codes_and_log_without_personal_data(self) -> None:
        config_path = write_config(self.root)
        self.assertEqual(main(["--config", str(config_path)]), 0)
        log = (self.root / "logs" / "application.log").read_text(encoding="utf-8")
        for personal in ("Марія", "Бойко", "Анна", "Коваль", "Ірина", "105"):
            self.assertNotIn(personal, log)
        self.assertIn("grade_out_of_range", log)
        self.assertEqual(main(["--config", str(self.root / "absent.yaml")]), 1)

    def test_main_strict_returns_one_and_unexpected_error_returns_two(self) -> None:
        raw = base_config()
        raw["processing"]["skip_invalid"] = False
        self.assertEqual(main(["--config", str(write_config(self.root, raw))]), 1)
        with mock.patch("reliable_importer.main.run_import_export", side_effect=RuntimeError("x")):
            self.assertEqual(main(["--config", str(write_config(self.root))]), 2)

    def test_describe_adds_cause(self) -> None:
        try:
            try:
                int("x")
            except ValueError as error:
                raise RecordValidationError("плохо", code="bad_id") from error
        except RecordValidationError as error:
            self.assertIn("причина: ValueError", describe(error))
        self.assertEqual(describe(RuntimeError("ok")), "ok")


class AtomicWriterTests(unittest.TestCase):
    def test_exception_inside_block_leaves_target_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.txt"
            target.write_text("old", encoding="utf-8")
            with self.assertRaises(RuntimeError), AtomicWriter(target) as file:
                file.write("new, half")
                raise RuntimeError("збій")
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["out.txt"])

    def test_creates_missing_directory_and_replaces_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "deep" / "er" / "out.txt"
            with AtomicWriter(target, backup=True) as file:
                file.write("first")
            with AtomicWriter(target, backup=True) as file:
                file.write("second")
            self.assertEqual(target.read_text(encoding="utf-8"), "second")
            self.assertEqual(target.with_name("out.txt.bak").read_text(encoding="utf-8"), "first")

    def test_replace_failure_becomes_export_error_with_cause(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.txt"
            with mock.patch(
                "reliable_importer.exporters.os.replace", side_effect=PermissionError("locked")
            ):
                with self.assertRaises(DataExportError) as caught, AtomicWriter(target) as file:
                    file.write("data")
            self.assertIsInstance(caught.exception.__cause__, PermissionError)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_retry_recovers_from_transient_lock(self) -> None:
        calls = {"count": 0}
        real_replace = os.replace

        def flaky(source: str, target: str) -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("тимчасово зайнято")
            real_replace(source, target)

        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "a", Path(folder) / "b"
            source.write_text("x", encoding="utf-8")
            with mock.patch("reliable_importer.exporters.os.replace", side_effect=flaky):
                replace_file(source, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "x")
        self.assertEqual(calls["count"], 2)


class SerializationAndUtilsTests(unittest.TestCase):
    def test_decimal_encoder_writes_numbers(self) -> None:
        text = json.dumps({"grade": Decimal("91.50")}, cls=DecimalJSONEncoder)
        self.assertEqual(text, '{"grade": 91.5}')
        with self.assertRaises(TypeError):
            json.dumps({"x": object()}, cls=DecimalJSONEncoder)

    def test_exporters_handle_empty_input(self) -> None:
        for exporter in (JsonExporter(), JsonLinesExporter()):
            with tempfile.TemporaryDirectory() as folder:
                with AtomicWriter(Path(folder) / "out") as file:
                    self.assertEqual(exporter.write([], file), 0)
        with tempfile.TemporaryDirectory() as folder:
            with AtomicWriter(Path(folder) / "out.json") as file:
                JsonExporter().write([], file)
            self.assertEqual(json.loads((Path(folder) / "out.json").read_text("utf-8")), [])

    def test_logged_operation_reraises_and_logs_failure(self) -> None:
        with self.assertLogs("reliable_importer.utils", level="INFO") as logs:
            with logged_operation("ok"):
                pass
            with self.assertRaises(ValueError), logged_operation("bad"):
                raise ValueError("x")
        self.assertEqual(len(logs.output), 4)
        self.assertIn("перервано", logs.output[-1])

    def test_retry_gives_up_after_attempts(self) -> None:
        attempts = {"count": 0}

        @retry(attempts=2, delay=0)
        def always_locked() -> None:
            attempts["count"] += 1
            raise PermissionError("locked")

        checker: Callable[[], None] = always_locked
        with self.assertRaises(PermissionError):
            checker()
        self.assertEqual(attempts["count"], 2)


if __name__ == "__main__":
    unittest.main()
