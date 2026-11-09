import csv
import json
from collections.abc import Generator
from pathlib import Path
from typing import Protocol

import yaml

from reliable_importer.exceptions import DataImportError, UnsupportedFormatError

REQUIRED_COLUMNS = ("student_id", "first_name", "last_name", "group", "average_grade")
RawRow = dict[str, object]
RowStream = Generator[tuple[int, RawRow], None, None]


class Importer(Protocol):
    def read(self, path: Path) -> RowStream: ...


class CsvImporter:
    def read(self, path: Path) -> RowStream:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
                if missing:
                    raise DataImportError(f"{path.name}: бракує колонок {sorted(missing)}")
                for row in reader:
                    yield reader.line_num, dict(row)
        except FileNotFoundError as error:
            raise DataImportError(f"Вхідний файл не знайдено: {path.name}") from error
        except UnicodeDecodeError as error:
            raise DataImportError(f"{path.name}: файл не в кодуванні UTF-8") from error
        except csv.Error as error:
            raise DataImportError(f"{path.name}: пошкоджений CSV") from error
        except OSError as error:
            raise DataImportError(f"Не вдалося прочитати {path.name}") from error


class JsonLinesImporter:
    def read(self, path: Path) -> RowStream:
        try:
            with path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise DataImportError(
                            f"{path.name}: некоректний JSON у рядку {line_number}"
                        ) from error
                    yield line_number, _as_row(item, line_number)
        except FileNotFoundError as error:
            raise DataImportError(f"Вхідний файл не знайдено: {path.name}") from error
        except UnicodeDecodeError as error:
            raise DataImportError(f"{path.name}: файл не в кодуванні UTF-8") from error
        except OSError as error:
            raise DataImportError(f"Не вдалося прочитати {path.name}") from error


class JsonImporter:
    def read(self, path: Path) -> RowStream:
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError as error:
            raise DataImportError(f"Вхідний файл не знайдено: {path.name}") from error
        except json.JSONDecodeError as error:
            raise DataImportError(f"{path.name}: некоректний JSON") from error
        except (OSError, UnicodeDecodeError) as error:
            raise DataImportError(f"Не вдалося прочитати {path.name}") from error
        yield from _items(data, path)


class YamlImporter:
    def read(self, path: Path) -> RowStream:
        try:
            with path.open("r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except FileNotFoundError as error:
            raise DataImportError(f"Вхідний файл не знайдено: {path.name}") from error
        except yaml.YAMLError as error:
            raise DataImportError(f"{path.name}: некоректний YAML") from error
        except (OSError, UnicodeDecodeError) as error:
            raise DataImportError(f"Не вдалося прочитати {path.name}") from error
        yield from _items(data, path)


def _as_row(item: object, number: int) -> RawRow:
    if not isinstance(item, dict):
        raise DataImportError(f"Запис {number} має бути об'єктом, а не {type(item).__name__}")
    return {str(key): value for key, value in item.items()}


def _items(data: object, path: Path) -> RowStream:
    if not isinstance(data, list):
        raise DataImportError(f"{path.name}: очікується список записів")
    for number, item in enumerate(data, start=1):
        yield number, _as_row(item, number)


IMPORTERS: dict[str, type[Importer]] = {
    "csv": CsvImporter,
    "jsonl": JsonLinesImporter,
    "json": JsonImporter,
    "yaml": YamlImporter,
}
EXTENSIONS = {".csv": "csv", ".jsonl": "jsonl", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}


def importer_for(path: Path, file_format: str = "auto") -> Importer:
    name = EXTENSIONS.get(path.suffix.lower()) if file_format == "auto" else file_format
    if name is None or name not in IMPORTERS:
        raise UnsupportedFormatError(f"Непідтримуваний формат вхідного файла: {path.suffix!r}")
    return IMPORTERS[name]()
