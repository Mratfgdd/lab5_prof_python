from pathlib import Path
from typing import Any

import yaml

HEADER = "student_id,first_name,last_name,group,average_grade\n"
VALID_ROWS = [
    "1,Анна,Коваль,PI-21,91.5",
    "3,Ірина,Бондар,PI-22,95.2",
    "9,Катерина,Лисенко,PI-23,93.1",
]
INVALID_ROW = "5,Марія,Бойко,PI-22,105"
BELOW_MINIMUM_ROW = "15,Богдан,Ткачук,PI-23,45.5"


def write_csv(path: Path, rows: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def base_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "input": {"path": "data/students.csv", "format": "auto"},
        "output": {
            "path": "output/students.json",
            "format": "json",
            "errors_path": "output/errors.csv",
            "summary_path": "output/summary.json",
            "backup": True,
        },
        "processing": {
            "skip_invalid": True,
            "minimum_grade": 60,
            "group_pattern": r"PI-\d{2}",
            "progress_every": 1000,
        },
        "logging": {"level": "INFO", "path": "logs/application.log"},
    }


def write_config(root: Path, config: dict[str, Any] | None = None) -> Path:
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config or base_config(), allow_unicode=True), encoding="utf-8")
    return path
