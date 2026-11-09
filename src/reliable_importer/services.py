import logging
from collections import Counter
from collections.abc import Generator, Iterable
from contextlib import ExitStack, closing
from decimal import Decimal
from typing import Protocol

from reliable_importer.config import AppConfig
from reliable_importer.exceptions import DataExportError, RecordValidationError
from reliable_importer.exporters import EXPORTERS, AtomicWriter, ErrorReport, Exporter, write_json
from reliable_importer.models import ImportStatistics, StudentRecord
from reliable_importer.readers import RawRow, importer_for
from reliable_importer.validators import RecordValidator

logger = logging.getLogger(__name__)


class ValidationPolicy(Protocol):
    def on_invalid(self, error: RecordValidationError, row: RawRow) -> None: ...


class StrictPolicy:
    def on_invalid(self, error: RecordValidationError, row: RawRow) -> None:
        raise error


class TolerantPolicy:
    def __init__(self, report: ErrorReport) -> None:
        self._report = report

    def on_invalid(self, error: RecordValidationError, row: RawRow) -> None:
        logger.warning("Некоректний запис пропущено: %s", error)
        self._report.add(error, row.get("student_id"))


def import_records(
    rows: Iterable[tuple[int, RawRow]],
    validator: RecordValidator,
    policy: ValidationPolicy,
    stats: ImportStatistics,
    progress_every: int = 10_000,
) -> Generator[StudentRecord, None, None]:
    for line_number, row in rows:
        stats.total += 1
        try:
            record = validator.validate(line_number, row)
        except RecordValidationError as error:
            stats.invalid += 1
            stats.errors[error.code] += 1
            policy.on_invalid(error, row)
        else:
            stats.valid += 1
            yield record
        if stats.total % progress_every == 0:
            logger.info("Прогрес: %d записів (некоректних %d)", stats.total, stats.invalid)


def filter_by_grade(
    records: Iterable[StudentRecord],
    minimum_grade: Decimal,
    stats: ImportStatistics,
    groups: Counter[str],
) -> Generator[StudentRecord, None, None]:
    for record in records:
        if record.average_grade < minimum_grade:
            stats.below_minimum += 1
            continue
        groups[record.group] += 1
        yield record


def run_import_export(
    config: AppConfig,
    *,
    exporter: Exporter | None = None,
    stats: ImportStatistics | None = None,
) -> ImportStatistics:
    stats = ImportStatistics() if stats is None else stats
    importer = importer_for(config.input.path, config.input.format)
    exporter = exporter if exporter is not None else EXPORTERS[config.output.format]()
    validator = RecordValidator(config.processing)
    mode = "tolerant" if config.processing.skip_invalid else "strict"
    logger.info("Імпорт %s (режим %s)", config.input.path.name, mode)
    by_group: Counter[str] = Counter()
    written = 0

    with ExitStack() as stack:
        output = stack.enter_context(AtomicWriter(config.output.path, backup=config.output.backup))
        errors = config.output.errors_path
        report = ErrorReport(stack.enter_context(AtomicWriter(errors)) if errors else None)
        policy = TolerantPolicy(report) if config.processing.skip_invalid else StrictPolicy()
        rows = stack.enter_context(closing(importer.read(config.input.path)))
        valid = stack.enter_context(
            closing(
                import_records(rows, validator, policy, stats, config.processing.progress_every)
            )
        )
        selected = stack.enter_context(
            closing(filter_by_grade(valid, config.processing.minimum_grade, stats, by_group))
        )
        try:
            written = exporter.write(selected, output)
        except OSError as error:
            raise DataExportError(f"Помилка запису {config.output.path.name}") from error

    stats.exported = written
    stats.groups.update(by_group)

    if config.output.summary_path is not None:
        write_json(
            {"input": config.input.path.name, "mode": mode, **stats.to_dict()},
            config.output.summary_path,
        )
    return stats
