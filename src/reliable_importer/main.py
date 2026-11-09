import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from reliable_importer.config import load_config
from reliable_importer.exceptions import ApplicationError
from reliable_importer.logging_config import configure_bootstrap_logging, configure_logging
from reliable_importer.models import ImportStatistics
from reliable_importer.services import run_import_export
from reliable_importer.utils import logged_operation

logger = logging.getLogger("reliable_importer")


def describe(error: BaseException) -> str:
    cause = error.__cause__
    return f"{error} (причина: {type(cause).__name__})" if cause is not None else str(error)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Імпорт/експорт студентів")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args(argv)

    configure_bootstrap_logging()
    stats = ImportStatistics()
    try:
        config = load_config(args.config)
        configure_logging(config.logging)
        with logged_operation("Імпорт/експорт студентів"):
            run_import_export(config, stats=stats)
    except ApplicationError as error:
        logger.error("Помилка застосунку: %s", describe(error))
        if stats.total:
            logger.error("Оброблено до зупинки: %s; вихідні файли не змінено", stats.to_dict())
        return 1
    except Exception:
        logger.exception("Непередбачена помилка")
        return 2
    logger.info(
        "Підсумок: total=%d, valid=%d, invalid=%d, below_minimum=%d, exported=%d, помилки=%s",
        stats.total,
        stats.valid,
        stats.invalid,
        stats.below_minimum,
        stats.exported,
        dict(stats.errors),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
