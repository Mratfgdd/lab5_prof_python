import re
import tempfile
import unittest
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from helpers import VALID_ROWS, base_config, write_config, write_csv

from reliable_importer.config import ProcessingConfig, load_config
from reliable_importer.exceptions import (
    ConfigurationError,
    DataImportError,
    RecordValidationError,
    UnsupportedFormatError,
)
from reliable_importer.readers import importer_for
from reliable_importer.validators import RecordValidator

PROCESSING = ProcessingConfig(
    skip_invalid=True,
    minimum_grade=Decimal(60),
    group_pattern=re.compile(r"PI-\d{2}"),
    progress_every=1000,
)


def row(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "student_id": "7",
        "first_name": "Олена",
        "last_name": "Коваль",
        "group": "PI-21",
        "average_grade": "91.5",
    }
    return base | changes


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_csv(self.root / "data" / "students.csv", VALID_ROWS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_config_resolves_paths_relative_to_file(self) -> None:
        config = load_config(write_config(self.root), environ={})
        self.assertEqual(config.input.path, self.root.resolve() / "data" / "students.csv")
        self.assertTrue(config.processing.skip_invalid)
        self.assertEqual(config.processing.minimum_grade, Decimal(60))

    def test_environment_override(self) -> None:
        config = load_config(
            write_config(self.root),
            environ={
                "STUDENTIO_SKIP_INVALID": "false",
                "STUDENTIO_LOG_LEVEL": "debug",
                "STUDENTIO_MINIMUM_GRADE": "75.5",
            },
        )
        self.assertFalse(config.processing.skip_invalid)
        self.assertEqual(config.logging.level, "DEBUG")
        self.assertEqual(config.processing.minimum_grade, Decimal("75.5"))

    def test_errors_are_configuration_errors_with_cause(self) -> None:
        with self.assertRaises(ConfigurationError) as missing:
            load_config(self.root / "absent.yaml", environ={})
        self.assertIsInstance(missing.exception.__cause__, FileNotFoundError)

        broken = self.root / "broken.yaml"
        broken.write_text("input: [unclosed", encoding="utf-8")
        with self.assertRaises(ConfigurationError) as invalid_yaml:
            load_config(broken, environ={})
        self.assertIsNotNone(invalid_yaml.exception.__cause__)

        scalar = self.root / "scalar.yaml"
        scalar.write_text("just text", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_config(scalar, environ={})

    def test_semantic_validation(self) -> None:
        cases: dict[str, Callable[[dict[str, Any]], object]] = {
            "без input": lambda c: c.pop("input"),
            "minimum_grade = 150": lambda c: c["processing"].update(minimum_grade=150),
            "minimum_grade < 0": lambda c: c["processing"].update(minimum_grade=-1),
            "minimum_grade = abc": lambda c: c["processing"].update(minimum_grade="abc"),
            "skip_invalid = maybe": lambda c: c["processing"].update(skip_invalid="maybe"),
            "немає файла": lambda c: c["input"].update(path="data/absent.csv"),
            "версія 2": lambda c: c.update(schema_version=2),
            "regex": lambda c: c["processing"].update(group_pattern="PI-(\\d"),
            "формат input": lambda c: c["input"].update(format="xml"),
            "формат output": lambda c: c["output"].update(format="xml"),
            "рівень логу": lambda c: c["logging"].update(level="LOUD"),
            "progress_every = 0": lambda c: c["processing"].update(progress_every=0),
            "input = output": lambda c: c["output"].update(path="data/students.csv"),
        }
        for name, change in cases.items():
            config = base_config()
            change(config)
            with self.subTest(case=name), self.assertRaises(ConfigurationError):
                load_config(write_config(self.root, config), environ={})

    def test_minimum_grade_boundaries_are_allowed(self) -> None:
        for value in (0, 100, 59.5):
            config = base_config()
            config["processing"]["minimum_grade"] = value
            loaded = load_config(write_config(self.root, config), environ={})
            self.assertEqual(loaded.processing.minimum_grade, Decimal(str(value)))


class ValidatorTests(unittest.TestCase):
    validator = RecordValidator(PROCESSING)

    def test_valid_record(self) -> None:
        record = self.validator.validate(2, row())
        self.assertEqual((record.student_id, record.group), (7, "PI-21"))
        self.assertEqual(record.average_grade, Decimal("91.50"))
        self.assertEqual(record.full_name, "Олена Коваль")
        self.assertEqual(record.to_dict()["student_id"], 7)

    def test_each_rule_has_its_code(self) -> None:
        cases = {
            "bad_id": row(student_id="abc"),
            "missing_field": row(first_name="  "),
            "bad_name": row(last_name="Коваль3"),
            "bad_group": row(group="PI-2"),
            "grade_out_of_range": row(average_grade="100.01"),
            "bad_number": row(average_grade="1e"),
        }
        for code, data in cases.items():
            with self.subTest(code=code), self.assertRaises(RecordValidationError) as caught:
                self.validator.validate(7, data)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.line_number, 7)

    def test_boundaries_of_grade_and_id(self) -> None:
        for grade, expected in (
            ("0", "0.00"),
            ("100", "100.00"),
            ("99.996", "100.00"),
            ("50.555", "50.56"),
            (91.5, "91.50"),
            (95, "95.00"),
        ):
            record = self.validator.validate(2, row(average_grade=grade))
            self.assertEqual(record.average_grade, Decimal(expected), grade)
        bad_grades: tuple[object, ...] = ("-0.01", "100.004", "NaN", "Infinity", True, None)
        for bad_grade in bad_grades:
            with self.subTest(grade=bad_grade), self.assertRaises(RecordValidationError):
                self.validator.validate(2, row(average_grade=bad_grade))
        for bad_id in ("0", "-5", "1.5", "", True, None):
            with self.subTest(student_id=bad_id), self.assertRaises(RecordValidationError):
                self.validator.validate(2, row(student_id=bad_id))
        self.assertEqual(self.validator.validate(2, row(student_id=12)).student_id, 12)

    def test_names_allow_apostrophe_hyphen_and_spaces(self) -> None:
        record = self.validator.validate(2, row(first_name="Дем'ян", last_name="Коваль-Мельник"))
        self.assertEqual(record.full_name, "Дем'ян Коваль-Мельник")
        for name in ("Іван!", "Іван_2", "-Іван", "Іван-"):
            with self.subTest(name=name), self.assertRaises(RecordValidationError):
                self.validator.validate(2, row(first_name=name))

    def test_missing_columns_are_reported(self) -> None:
        with self.assertRaises(RecordValidationError) as caught:
            self.validator.validate(2, {"student_id": "1"})
        self.assertEqual(caught.exception.field, "first_name")

    def test_chaining_keeps_original_cause(self) -> None:
        with self.assertRaises(RecordValidationError) as grade:
            self.validator.validate(2, row(average_grade="wrong"))
        self.assertIsInstance(grade.exception.__cause__, InvalidOperation)
        with self.assertRaises(RecordValidationError) as student_id:
            self.validator.validate(2, row(student_id="abc"))
        self.assertIsInstance(student_id.exception.__cause__, ValueError)

    def test_message_contains_no_values(self) -> None:
        with self.assertRaises(RecordValidationError) as caught:
            self.validator.validate(2, row(first_name="Олена", average_grade="999"))
        self.assertNotIn("Олена", str(caught.exception))
        self.assertNotIn("999", str(caught.exception))
        self.assertIn("average_grade", str(caught.exception))


class ImporterTests(unittest.TestCase):
    def test_formats_by_extension(self) -> None:
        data = Path(__file__).resolve().parents[1] / "data"
        for name, expected in (("students.csv", 20), ("students.jsonl", 3), ("students.yaml", 2)):
            with self.subTest(file=name):
                rows = list(importer_for(data / name).read(data / name))
                self.assertEqual(len(rows), expected)
        with self.assertRaises(UnsupportedFormatError):
            importer_for(Path("students.xml"))
        with self.assertRaises(UnsupportedFormatError):
            importer_for(Path("students.csv"), "xml")

    def test_explicit_format_overrides_extension(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "students.txt"
            write_csv(path, VALID_ROWS)
            self.assertEqual(len(list(importer_for(path, "csv").read(path))), 3)

    def test_csv_line_numbers_and_bom(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bom.csv"
            path.write_text(
                "student_id,first_name,last_name,group,average_grade\n1,А,Б,PI-21,90\n",
                encoding="utf-8-sig",
            )
            rows = list(importer_for(path).read(path))
        self.assertEqual([number for number, _ in rows], [2])
        self.assertEqual(rows[0][1]["student_id"], "1")

    def test_broken_inputs_raise_import_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bad_header = root / "a.csv"
            bad_header.write_text("student_id,first_name\n1,A\n", encoding="utf-8")
            bad_json = root / "b.jsonl"
            bad_json.write_text('{"a": 1}\n{oops\n', encoding="utf-8")
            not_utf8 = root / "c.csv"
            not_utf8.write_bytes(
                "student_id,first_name,last_name,group,average_grade\n"
                "1,Олена,Коваль,PI-21,90\n".encode("cp1251")
            )
            not_list = root / "d.json"
            not_list.write_text('{"student_id": 1}', encoding="utf-8")
            bad_yaml = root / "e.yaml"
            bad_yaml.write_text("- a: [unclosed", encoding="utf-8")
            scalar_item = root / "f.jsonl"
            scalar_item.write_text("42\n", encoding="utf-8")
            paths = (bad_header, bad_json, not_utf8, not_list, bad_yaml, scalar_item)
            for path in (*paths, root / "absent.csv"):
                with self.subTest(path=path.name), self.assertRaises(DataImportError):
                    list(importer_for(path).read(path))

    def test_causes_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.jsonl"
            path.write_text("{oops\n", encoding="utf-8")
            with self.assertRaises(DataImportError) as caught:
                list(importer_for(path).read(path))
            self.assertIsNotNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
