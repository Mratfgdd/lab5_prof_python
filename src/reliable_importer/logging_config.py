import logging
import sys
from logging.handlers import RotatingFileHandler

from reliable_importer.config import LoggingConfig

FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_bootstrap_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=FORMAT, stream=sys.stderr, force=True)


def configure_logging(config: LoggingConfig) -> None:
    config.path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        config.path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(FORMAT)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
    logging.basicConfig(
        level=getattr(logging, config.level),
        handlers=[file_handler, console_handler],
        force=True,
    )
