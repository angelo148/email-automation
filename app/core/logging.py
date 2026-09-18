import logging
import sys

from app.core.request_context import get_request_id

APPLICATION_LOGGER_NAME = "app"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging(level: str = "DEBUG") -> None:
    """
    Configure application logging.

    The application uses its own logger hierarchy instead of
    replacing Uvicorn's logging configuration.
    """

    logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    normalized_level = getattr(logging, level.upper(), logging.DEBUG)
    logger.setLevel(normalized_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(request_id)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return an application logger under the configured ``app`` hierarchy."""

    return logging.getLogger(name)
