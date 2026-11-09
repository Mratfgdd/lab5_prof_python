import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from reliable_importer.exceptions import ConfigurationError

SCHEMA_VERSION = 1
INPUT_FORMATS = frozenset({"auto", "csv", "json", "jsonl", "yaml"})
OUTPUT_FORMATS = frozenset({"json", "jsonl"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "STUDENTIO_INPUT_PATH": ("input", "path"),
    "STUDENTIO_OUTPUT_PATH": ("output", "path"),
    "STUDENTIO_SKIP_INVALID": ("processing", "skip_invalid"),
    "STUDENTIO_MINIMUM_GRADE": ("processing", "minimum_grade"),
    "STUDENTIO_LOG_LEVEL": ("logging", "level"),
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InputConfig:
    path: Path
    format: str


@dataclass(frozen=True, slots=True)
class OutputConfig:
    path: Path
    format: str
    errors_path: Path | None
    summary_path: Path | None
    backup: bool


@dataclass(frozen=True, slots=True)
class ProcessingConfig:
    skip_invalid: bool
    minimum_grade: Decimal
    group_pattern: re.Pattern[str]
    progress_every: int


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str
    path: Path
    max_bytes: int
    backup_count: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    schema_version: int
    input: InputConfig
    output: OutputConfig
    processing: ProcessingConfig
    logging: LoggingConfig


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> AppConfig:
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file)
    except FileNotFoundError as error:
        raise ConfigurationError(f"Файл конфігурації не знайдено: {path}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError(f"Некоректний YAML у {path.name}") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigurationError(f"Не вдалося прочитати {path}") from error

    if not isinstance(raw, dict):
        raise ConfigurationError("Корінь конфігурації має бути словником")
    apply_env_overrides(raw, os.environ if environ is None else environ)
    try:
        config = _build(raw, base=path.resolve().parent)
    except (KeyError, TypeError, ValueError, InvalidOperation, re.error) as error:
        raise ConfigurationError(f"Некоректна структура конфігурації: {error!r}") from error
    validate_config(config)
    return config


def apply_env_overrides(raw: dict[str, Any], environ: Mapping[str, str]) -> None:
    for variable, (section, key) in ENV_OVERRIDES.items():
        if variable in environ:
            raw.setdefault(section, {})[key] = environ[variable]
            logger.info("Параметр %s.%s перевизначено змінною %s", section, key, variable)


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"очікується true/false, отримано {value!r}")


def _path(value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"очікується непорожній шлях, отримано {value!r}")
    path = Path(value)
    return path if path.is_absolute() else base / path


def _build(raw: dict[str, Any], base: Path) -> AppConfig:
    output, processing, log = raw["output"], raw["processing"], raw["logging"]
    errors_path = output.get("errors_path")
    summary_path = output.get("summary_path")
    return AppConfig(
        schema_version=int(raw["schema_version"]),
        input=InputConfig(
            path=_path(raw["input"]["path"], base),
            format=str(raw["input"].get("format", "auto")),
        ),
        output=OutputConfig(
            path=_path(output["path"], base),
            format=str(output.get("format", "json")),
            errors_path=_path(errors_path, base) if errors_path else None,
            summary_path=_path(summary_path, base) if summary_path else None,
            backup=_flag(output.get("backup", False)),
        ),
        processing=ProcessingConfig(
            skip_invalid=_flag(processing["skip_invalid"]),
            minimum_grade=Decimal(str(processing["minimum_grade"])),
            group_pattern=re.compile(str(processing["group_pattern"])),
            progress_every=int(processing.get("progress_every", 10_000)),
        ),
        logging=LoggingConfig(
            level=str(log.get("level", "INFO")).upper(),
            path=_path(log["path"], base),
            max_bytes=int(log.get("max_bytes", 1_048_576)),
            backup_count=int(log.get("backup_count", 3)),
        ),
    )


def validate_config(config: AppConfig) -> None:
    if config.schema_version != SCHEMA_VERSION:
        raise ConfigurationError(
            f"Непідтримувана версія схеми {config.schema_version} (очікується {SCHEMA_VERSION})"
        )
    minimum = config.processing.minimum_grade
    if not minimum.is_finite() or not 0 <= minimum <= 100:
        raise ConfigurationError("minimum_grade має бути числом від 0 до 100")
    if config.processing.progress_every < 1:
        raise ConfigurationError("progress_every має бути >= 1")
    if config.input.format not in INPUT_FORMATS:
        raise ConfigurationError(f"Невідомий формат input: {config.input.format}")
    if config.output.format not in OUTPUT_FORMATS:
        raise ConfigurationError(f"Невідомий формат output: {config.output.format}")
    if config.logging.level not in LOG_LEVELS:
        raise ConfigurationError(f"Невідомий рівень логування: {config.logging.level}")
    if not config.input.path.is_file():
        raise ConfigurationError(f"Вхідний файл не знайдено: {config.input.path.name}")
    if config.input.path.resolve() == config.output.path.resolve():
        raise ConfigurationError("Вхідний і вихідний файли не можуть збігатися")
