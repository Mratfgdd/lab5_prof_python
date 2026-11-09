import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)


@contextmanager
def logged_operation(operation: str) -> Iterator[None]:
    logger.info("%s: початок", operation)
    start = time.perf_counter()
    try:
        yield
    except Exception:
        logger.error("%s: перервано через %.3f с", operation, time.perf_counter() - start)
        raise
    else:
        logger.info("%s: завершено за %.3f с", operation, time.perf_counter() - start)


def retry(
    attempts: int = 3,
    delay: float = 0.1,
    exceptions: tuple[type[Exception], ...] = (PermissionError,),
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as error:
                    if attempt == attempts:
                        raise
                    logger.warning(
                        "%s: спроба %d/%d невдала (%s), повтор",
                        func.__name__,
                        attempt,
                        attempts,
                        type(error).__name__,
                    )
                    time.sleep(delay * attempt)
            raise AssertionError("unreachable")

        return wrapper

    return decorator
