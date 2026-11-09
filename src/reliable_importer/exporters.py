import csv
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Protocol, TextIO

from reliable_importer.exceptions import DataExportError, RecordValidationError
from reliable_importer.models import StudentRecord
from reliable_importer.utils import retry

logger = logging.getLogger(__name__)


class DecimalJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


class Exporter(Protocol):
    def write(self, records: Iterable[StudentRecord], file: TextIO) -> int: ...


class JsonExporter:
    def write(self, records: Iterable[StudentRecord], file: TextIO) -> int:
        count = 0
        file.write("[")
        for record in records:
            file.write(",\n  " if count else "\n  ")
            file.write(json.dumps(record.to_dict(), cls=DecimalJSONEncoder, ensure_ascii=False))
            count += 1
        file.write("\n]\n" if count else "]\n")
        return count


class JsonLinesExporter:
    def write(self, records: Iterable[StudentRecord], file: TextIO) -> int:
        count = 0
        for record in records:
            file.write(json.dumps(record.to_dict(), cls=DecimalJSONEncoder, ensure_ascii=False))
            file.write("\n")
            count += 1
        return count


EXPORTERS: dict[str, type[Exporter]] = {"json": JsonExporter, "jsonl": JsonLinesExporter}


@retry(attempts=3, delay=0.1)
def replace_file(source: Path, target: Path) -> None:
    os.replace(source, target)


class AtomicWriter:
    def __init__(self, path: Path, *, backup: bool = False, encoding: str = "utf-8") -> None:
        self.path = path
        self.backup = backup
        self.encoding = encoding
        self._temp: Path | None = None
        self._file: TextIO | None = None

    def __enter__(self) -> TextIO:
        try:
            if not self.path.parent.exists():
                logger.info("Створюється каталог для %s", self.path.name)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
        except OSError as error:
            raise DataExportError(f"Неможливо підготувати запис {self.path.name}") from error
        self._temp = Path(name)
        self._file = os.fdopen(descriptor, "w", encoding=self.encoding, newline="")
        return self._file

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self._file is not None and self._temp is not None
        try:
            try:
                if exc_type is None:
                    self._file.flush()
                    os.fsync(self._file.fileno())
            finally:
                self._file.close()
            if exc_type is not None:
                logger.warning("%s: запис скасовано, тимчасовий файл видалено", self.path.name)
                return
            if self.backup and self.path.exists():
                shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
            replace_file(self._temp, self.path)
        except OSError as error:
            raise DataExportError(f"Неможливо записати {self.path.name}") from error
        finally:
            self._temp.unlink(missing_ok=True)


class ErrorReport:
    FIELDS = ("line", "student_id", "field", "code", "message")

    def __init__(self, file: TextIO | None) -> None:
        self._writer = csv.writer(file) if file is not None else None
        if self._writer is not None:
            self._writer.writerow(self.FIELDS)

    def add(self, error: RecordValidationError, raw_student_id: object) -> None:
        if self._writer is None:
            return
        student_id = "" if raw_student_id is None else str(raw_student_id)
        self._writer.writerow(
            [error.line_number, student_id, error.field, error.code, error.message]
        )


def write_json(data: object, path: Path) -> None:
    with AtomicWriter(path) as file:
        json.dump(data, file, cls=DecimalJSONEncoder, ensure_ascii=False, indent=2)
