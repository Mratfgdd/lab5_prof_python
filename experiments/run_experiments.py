import argparse
import contextlib
import csv
import gc
import hashlib
import io
import json
import logging
import random
import shutil
import sys
import time
import traceback
import tracemalloc
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import Any, TextIO

import yaml

from reliable_importer.config import AppConfig, load_config
from reliable_importer.exceptions import ApplicationError, RecordValidationError
from reliable_importer.exporters import DecimalJSONEncoder, JsonExporter
from reliable_importer.main import main as app_main
from reliable_importer.models import ImportStatistics, StudentRecord
from reliable_importer.services import run_import_export
from reliable_importer.validators import RecordValidator

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data" / "generated"
RESULTS = ROOT / "results"
HEADER = ["student_id", "first_name", "last_name", "group", "average_grade"]
FIRST_NAMES = ("Олена", "Андрій", "Ірина", "Тарас", "Максим", "Софія", "Дмитро", "Катерина")
LAST_NAMES = ("Коваленко", "Мельник", "Бондар", "Гриценко", "Ткаченко", "Гнатюк", "Бойко")
GROUPS = ("PI-21", "PI-22", "PI-23", "PI-24")


def write_config(path: Path, input_path: Path, **processing: Any) -> Path:
    raw = {
        "schema_version": 1,
        "input": {"path": str(input_path)},
        "output": {"path": str(path.parent / "out" / "students.json"), "backup": False},
        "processing": {
            "skip_invalid": True,
            "minimum_grade": 60,
            "group_pattern": r"PI-\d{2}",
            "progress_every": 1_000_000,
        }
        | processing,
        "logging": {"level": "INFO", "path": str(path.parent / "logs" / "experiment.log")},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def valid_row(index: int, rng: random.Random) -> list[str]:
    return [
        str(index + 1),
        rng.choice(FIRST_NAMES),
        rng.choice(LAST_NAMES),
        rng.choice(GROUPS),
        f"{rng.uniform(60, 100):.2f}",
    ]


def write_rows(path: Path, rows: Iterable[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def short(text: str) -> str:
    return text.replace(str(ROOT) + "\\", "").replace(str(ROOT), ".")


def strict_vs_tolerant() -> dict[str, Any]:
    rng = random.Random(1)
    rows: list[list[str]] = []
    for index in range(1000):
        rows.append(valid_row(index, rng))
        if index % 100 == 49:
            rows.append([f"{5000 + index}", "Олена", "Коваль", "XX-1", "80"])
    data = write_rows(WORK / "exp1" / "students.csv", rows)
    result: dict[str, Any] = {}
    for mode, skip in (("strict", False), ("tolerant", True)):
        config_path = write_config(WORK / "exp1" / mode / "config.yaml", data, skip_invalid=skip)
        stats = ImportStatistics()
        outcome = "успішно"
        try:
            run_import_export(load_config(config_path, environ={}), stats=stats)
        except RecordValidationError as error:
            outcome = f"зупинка: {error}"
        exit_code = app_main(["--config", str(config_path)])
        output = WORK / "exp1" / mode / "out" / "students.json"
        result[mode] = stats.to_dict() | {
            "outcome": outcome,
            "exit_code": exit_code,
            "output_exists": output.exists(),
        }
    return result


def eager_import(config: AppConfig) -> int:
    with config.input.path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    validator = RecordValidator(config.processing)
    records: list[StudentRecord] = []
    for line_number, row in enumerate(rows, start=2):
        try:
            record = validator.validate(line_number, dict(row))
        except RecordValidationError:
            continue
        if record.average_grade >= config.processing.minimum_grade:
            records.append(record)
    config.output.path.parent.mkdir(parents=True, exist_ok=True)
    with config.output.path.open("w", encoding="utf-8") as out:
        json.dump([r.to_dict() for r in records], out, cls=DecimalJSONEncoder, ensure_ascii=False)
    return len(records)


def streaming_import(config: AppConfig) -> int:
    return run_import_export(config).exported


def timed(func: Callable[[], object]) -> float:
    gc.collect()
    start = time.perf_counter()
    func()
    return time.perf_counter() - start


def best_times(
    first: Callable[[], object], second: Callable[[], object], repeat: int
) -> tuple[float, float]:
    best_first = best_second = float("inf")
    for _ in range(repeat):
        best_first = min(best_first, timed(first))
        best_second = min(best_second, timed(second))
    return best_first, best_second


def peak(func: Callable[[], object]) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        func()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def streaming_vs_eager(sizes: list[int]) -> list[dict[str, Any]]:
    rows_out = []
    logging.disable(logging.WARNING)
    try:
        for size in sizes:
            rng = random.Random(size)
            data = write_rows(
                WORK / "exp2" / f"students_{size}.csv", (valid_row(i, rng) for i in range(size))
            )
            config = load_config(write_config(WORK / "exp2" / "config.yaml", data), environ={})
            exported = streaming_import(config)
            assert exported == eager_import(config)
            eager, lazy = partial(eager_import, config), partial(streaming_import, config)
            eager_time, streaming_time = best_times(eager, lazy, repeat=5)
            rows_out.append(
                {
                    "records": size,
                    "exported": exported,
                    "eager_time": eager_time,
                    "streaming_time": streaming_time,
                    "eager_peak": peak(eager),
                    "streaming_peak": peak(lazy),
                }
            )
            print(rows_out[-1], flush=True)
    finally:
        logging.disable(logging.NOTSET)
    return rows_out


def exception_chaining() -> str:
    config = load_config(
        write_config(WORK / "exp3" / "config.yaml", ROOT / "data" / "students.csv"), environ={}
    )
    row: dict[str, object] = {
        "student_id": "1",
        "first_name": "Анна",
        "last_name": "Коваль",
        "group": "PI-21",
        "average_grade": "wrong",
    }
    try:
        RecordValidator(config.processing).validate(2, row)
    except RecordValidationError as error:
        return short("".join(traceback.format_exception(error)))
    raise AssertionError("очікувалась помилка")


class FailingExporter:
    def write(self, records: Iterable[StudentRecord], file: TextIO) -> int:
        for index, record in enumerate(records):
            if index == 5:
                raise OSError(28, "No space left on device (імітація)")
            JsonExporter().write([record], file)
        return 0


def atomic_output() -> dict[str, Any]:
    config = load_config(
        write_config(WORK / "exp4" / "config.yaml", ROOT / "data" / "students.csv"), environ={}
    )
    run_import_export(config)
    target = config.output.path
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(f"{record.levelname}: {record.getMessage()}")
    logging.getLogger().addHandler(handler)
    try:
        run_import_export(config, exporter=FailingExporter())
        error_text = "помилки не було"
    except ApplicationError as error:
        error_text = f"{type(error).__name__}: {error} <- {type(error.__cause__).__name__}"
    finally:
        logging.getLogger().removeHandler(handler)
    return {
        "error": error_text,
        "output_unchanged": hashlib.sha256(target.read_bytes()).hexdigest() == before,
        "tmp_files": [p.name for p in target.parent.glob("*.tmp")],
        "log": [line for line in records if "скасовано" in line],
    }


def configuration_errors() -> list[dict[str, Any]]:
    base = WORK / "exp5"
    data = ROOT / "data" / "students.csv"
    cases: list[tuple[str, Path]] = []
    cases.append(("відсутній config.yaml", base / "absent.yaml"))
    broken = base / "broken.yaml"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("input: [path: data.csv\nprocessing: {", encoding="utf-8")
    cases.append(("неправильний YAML", broken))
    no_input = write_config(base / "no_input" / "config.yaml", data)
    raw = yaml.safe_load(no_input.read_text(encoding="utf-8"))
    raw.pop("input")
    no_input.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cases.append(("немає ключа input", no_input))
    cases.append(
        (
            "minimum_grade = 150",
            write_config(base / "limit" / "config.yaml", data, minimum_grade=150),
        )
    )
    cases.append(
        (
            "input file відсутній",
            write_config(base / "missing_input" / "config.yaml", base / "nope.csv"),
        )
    )
    out_dir = base / "new_output_dir"
    config = write_config(out_dir / "config.yaml", data)
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw["output"]["path"] = str(out_dir / "does" / "not" / "exist" / "students.json")
    config.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    cases.append(("output directory не існує", config))

    results = []
    for name, path in cases:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = app_main(["--config", str(path)])
        lines = [
            ln
            for ln in stderr.getvalue().splitlines()
            if "| ERROR" in ln or "Каталог" in ln or "Створюється" in ln
        ]
        message = lines[0].split("| ", 3)[-1] if lines else "успішно, вихідні файли створено"
        results.append({"case": name, "exit_code": code, "message": short(message)})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000, 500_000])
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    for name in ("exp1", "exp3", "exp4", "exp5"):
        shutil.rmtree(WORK / name, ignore_errors=True)
    report = {
        "strict_vs_tolerant": strict_vs_tolerant(),
        "exception_chaining": exception_chaining(),
        "atomic_output": atomic_output(),
        "configuration_errors": configuration_errors(),
    }
    streaming = streaming_vs_eager(args.sizes)
    with (RESULTS / "streaming.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(streaming[0]))
        writer.writeheader()
        writer.writerows(streaming)
    (RESULTS / "experiments.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
